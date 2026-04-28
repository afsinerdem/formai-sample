from __future__ import annotations

import io
import json
import random
from pathlib import Path
from typing import Dict, List, Sequence

from formai.benchmarks.base import DatasetAdapter
from formai.benchmarks.models import BenchmarkSample, ExpectedField
from formai.errors import IntegrationUnavailable
from formai.models import BoundingBox, FieldKind, RenderedPage


class LocalManifestAdapter(DatasetAdapter):
    fixture_dir_name: str = ""

    def __init__(self, dataset_dir: Path | None = None):
        self.dataset_dir = Path(dataset_dir) if dataset_dir else None

    def load_samples(self, split: str, max_samples: int | None = None) -> Sequence[BenchmarkSample]:
        manifest_path = self._resolve_manifest_path()
        rows = json.loads(manifest_path.read_text(encoding="utf-8"))
        samples: List[BenchmarkSample] = []

        for index, row in enumerate(rows):
            row_split = row.get("split", "test")
            if split not in {"all", row_split}:
                continue
            sample_id = row.get("sample_id") or f"{self.dataset_name}:{row_split}:{index}"
            samples.append(
                BenchmarkSample(
                    sample_id=sample_id,
                    dataset=self.dataset_name,
                    split=row_split,
                    rendered_pages=self._rendered_pages_from_manifest(row),
                    expected_fields=self._expected_fields_from_manifest(row),
                )
            )

        if max_samples is not None:
            return samples[:max_samples]
        return samples

    def _resolve_manifest_path(self) -> Path:
        candidate = self.dataset_dir / "manifest.json" if self.dataset_dir else None
        if candidate and candidate.exists():
            return candidate
        built_in = Path(__file__).resolve().parent / "fixtures" / self.fixture_dir_name / "manifest.json"
        if built_in.exists():
            return built_in
        raise IntegrationUnavailable(
            f"{self.dataset_name} manifest could not be found. Set a dataset dir or provide built-in fixtures."
        )

    def _expected_fields_from_manifest(self, row: Dict) -> List[ExpectedField]:
        fields: List[ExpectedField] = []
        page_entries = self._page_entries_from_manifest(row)
        if page_entries:
            fallback_fields = row.get("expected_fields", [])
            fallback_used = False
            for index, page_entry in enumerate(page_entries, start=1):
                page_number = int(page_entry.get("page_number", index))
                page_fields = page_entry.get("expected_fields")
                if page_fields is None:
                    if fallback_used:
                        continue
                    page_fields = fallback_fields
                    fallback_used = True
                else:
                    fallback_used = True
                fields.extend(
                    self._expected_fields_from_entries(
                        page_fields,
                        default_page_number=page_number,
                    )
                )
            return self._dedupe_expected_fields(fields)

        fields.extend(
            self._expected_fields_from_entries(
                row.get("expected_fields", []),
                default_page_number=int(row.get("page_number", 1)),
            )
        )
        return self._dedupe_expected_fields(fields)

    def _expected_fields_from_entries(self, entries: Sequence[Dict], *, default_page_number: int) -> List[ExpectedField]:
        fields: List[ExpectedField] = []
        for field in entries:
            page_number = int(field.get("page_number", default_page_number))
            box = None
            if field.get("box"):
                left, top, right, bottom = [float(value) for value in field["box"]]
                box = BoundingBox(
                    page_number=page_number,
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                )
            kind = FieldKind(field.get("kind", "text"))
            fields.append(
                ExpectedField(
                    key=field["key"],
                    value=field["value"],
                    field_kind=kind,
                    box=box,
                    page_number=page_number,
                )
            )
        return fields

    def _rendered_pages_from_manifest(self, row: Dict) -> List[RenderedPage]:
        pages: List[RenderedPage] = []
        page_entries = self._page_entries_from_manifest(row)
        if not page_entries:
            return pages
        for index, page_entry in enumerate(page_entries, start=1):
            page_number = int(page_entry.get("page_number", index))
            pages.append(
                self._rendered_page_from_manifest(
                    row,
                    page_entry,
                    page_number=page_number,
                )
            )
        return pages

    def _page_entries_from_manifest(self, row: Dict) -> List[Dict]:
        pages = row.get("pages")
        if isinstance(pages, list) and pages:
            return [dict(page) for page in pages]
        page = row.get("page")
        if isinstance(page, dict):
            return [dict(page)]
        return []

    def _dedupe_expected_fields(self, fields: Sequence[ExpectedField]) -> List[ExpectedField]:
        deduped: Dict[tuple[str, int], ExpectedField] = {}
        for field in fields:
            deduped[(field.key, field.page_number)] = field
        return list(deduped.values())

    def _rendered_page_from_manifest(self, row: Dict, page_entry: Dict, *, page_number: int) -> RenderedPage:
        try:
            from PIL import Image, ImageDraw, ImageFilter, ImageFont
        except ImportError as exc:
            raise IntegrationUnavailable("Pillow is required to render local benchmark fixtures.") from exc

        page = dict(row)
        page.update(page_entry)
        page["page_number"] = page_number
        style = str(page.get("style", "printed"))
        image = self._background_image_from_manifest(page)
        width, height = image.size
        draw = ImageDraw.Draw(image)

        for guide in page.get("guides", []):
            color = tuple(guide.get("color", [226, 223, 217]))
            if len(color) == 3:
                color = (*color, 255)
            draw.line(tuple(guide["points"]), fill=color, width=int(guide.get("width", 2)))

        rng = random.Random(row.get("seed", row.get("sample_id", self.dataset_name)))
        for item in page.get("content", []):
            text = str(item["text"])
            x = int(item.get("x", 80))
            y = int(item.get("y", 80))
            size = int(item.get("size", 28))
            color = tuple(item.get("color", [31, 31, 35]))
            font = _load_font(ImageFont, size=size)
            if style == "handwritten":
                _draw_handwritten_text(
                    image=image,
                    text=text,
                    x=x,
                    y=y,
                    font=font,
                    color=color,
                    rotation=float(item.get("rotation", rng.uniform(-2.5, 2.5))),
                    blur=float(item.get("blur", 0.45)),
                )
            else:
                draw.text((x, y), text, fill=(*color, 255), font=font)

        buffer = io.BytesIO()
        if style == "handwritten":
            image = image.filter(ImageFilter.GaussianBlur(radius=0.15))
        image.convert("RGB").save(buffer, format="PNG")
        return RenderedPage(
            page_number=page_number,
            mime_type="image/png",
            image_bytes=buffer.getvalue(),
            width=width,
            height=height,
        )

    def _background_image_from_manifest(self, page: Dict):
        from PIL import Image

        background_image = page.get("background_image")
        if background_image:
            image_path = self._resolve_asset_path(background_image)
            return Image.open(image_path).convert("RGBA")

        background_pdf = page.get("background_pdf")
        if background_pdf:
            return self._render_background_pdf(
                self._resolve_asset_path(background_pdf),
                page_number=int(page.get("background_page", 1)),
                dpi=int(page.get("background_dpi", 144)),
            )

        width = int(page.get("width", 1240))
        height = int(page.get("height", 1754))
        background = tuple(page.get("background", [251, 250, 246]))
        return Image.new("RGBA", (width, height), color=(*background, 255))

    def _resolve_asset_path(self, candidate: str) -> Path:
        path = Path(candidate)
        if path.is_absolute():
            return path
        manifest_path = self._resolve_manifest_path()
        return (manifest_path.parent / path).resolve()

    def _render_background_pdf(self, pdf_path: Path, *, page_number: int, dpi: int):
        try:
            from PIL import Image
            import fitz
        except ImportError as exc:
            raise IntegrationUnavailable("PyMuPDF and Pillow are required for PDF-backed fixtures.") from exc

        document = fitz.open(str(pdf_path))
        try:
            page_index = max(0, page_number - 1)
            page = document[page_index]
            scale = max(dpi, 72) / 72.0
            matrix = fitz.Matrix(scale, scale)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            return image.convert("RGBA")
        finally:
            document.close()


def _load_font(image_font_module, size: int):
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for candidate in font_candidates:
        try:
            return image_font_module.truetype(candidate, size)
        except Exception:
            continue
    return image_font_module.load_default()


def _draw_handwritten_text(*, image, text: str, x: int, y: int, font, color, rotation: float, blur: float) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(layer)
    draw.text((x, y), text, fill=(*color, 255), font=font)
    resampling = getattr(Image, "Resampling", Image)
    rotated = layer.rotate(rotation, resample=resampling.BICUBIC)
    if blur > 0:
        rotated = rotated.filter(ImageFilter.GaussianBlur(radius=blur))
    image.alpha_composite(rotated)
