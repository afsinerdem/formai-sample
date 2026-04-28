from __future__ import annotations

import io
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from formai.artifacts import FilledLayoutArtifact
from formai.models import (
    BoundingBox,
    FilledDocumentTranscript,
    ProcessingIssue,
    RenderedPage,
    TemplateTextSpan,
)
from formai.pdf.rasterizer import rasterize_pdf
from formai.pdf.structure import build_template_structure_graph


class SuryaLayoutEngine:
    """Optional Surya-backed layout engine with safe fallback behavior.

    If `surya-ocr` is available, this engine uses the official Layout and Table
    predictors. If not, it falls back to page-sized regions plus transcript-based
    density estimates so the node graph remains functional.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._foundation_predictor = None
        self._layout_predictor = None
        self._table_predictor = None
        self._load_error: str | None = None

    def analyze_template(self, pdf_path: Path):
        structure = build_template_structure_graph(pdf_path)
        if not self.enabled:
            return structure
        try:
            self._ensure_predictors()
            pages = rasterize_pdf(pdf_path, dpi=160)
            images = self._pages_to_images(pages)
            layout_predictions = self._layout_predictor(images)
            synthetic_spans: list[TemplateTextSpan] = []
            for index, page in enumerate(pages):
                prediction = layout_predictions[index] if index < len(layout_predictions) else None
                for item in self._prediction_items(prediction):
                    bbox = self._extract_bbox(item, page_number=page.page_number, page=page)
                    if bbox is None:
                        continue
                    synthetic_spans.append(
                        TemplateTextSpan(
                            text=f"[layout:{self._item_label(item)}]",
                            page_number=page.page_number,
                            left=bbox.left,
                            top=bbox.top,
                            right=bbox.right,
                            bottom=bbox.bottom,
                            font_name="surya_layout",
                        )
                    )
            if synthetic_spans:
                structure.spans.extend(synthetic_spans)
        except Exception as exc:
            self._load_error = str(exc)
        return structure

    def analyze_filled_pages(
        self,
        pages: Sequence[RenderedPage],
        transcript: FilledDocumentTranscript | None = None,
    ) -> FilledLayoutArtifact:
        if self.enabled:
            try:
                self._ensure_predictors()
                return self._analyze_with_surya(pages, transcript=transcript)
            except Exception as exc:
                self._load_error = str(exc)
        return self._fallback_layout(pages, transcript=transcript)

    def _ensure_predictors(self) -> None:
        if self._layout_predictor is not None:
            return
        try:
            from surya.foundation import FoundationPredictor
            from surya.layout import LayoutPredictor
            from surya.settings import settings
            from surya.table_rec import TableRecPredictor
        except ImportError as exc:
            raise RuntimeError(
                "surya-ocr is not installed; using fallback layout engine."
            ) from exc
        self._foundation_predictor = FoundationPredictor(
            checkpoint=settings.LAYOUT_MODEL_CHECKPOINT
        )
        self._layout_predictor = LayoutPredictor(self._foundation_predictor)
        try:
            self._table_predictor = TableRecPredictor()
        except Exception:
            self._table_predictor = None

    def _analyze_with_surya(
        self,
        pages: Sequence[RenderedPage],
        *,
        transcript: FilledDocumentTranscript | None,
    ) -> FilledLayoutArtifact:
        images = self._pages_to_images(pages)
        layout_predictions = self._layout_predictor(images)
        table_predictions = self._table_predictor(images) if self._table_predictor is not None else []
        page_regions: dict[int, list[BoundingBox]] = defaultdict(list)
        density: dict[str, float] = {}
        issues: list[ProcessingIssue] = []

        for index, page in enumerate(pages):
            layout_prediction = layout_predictions[index] if index < len(layout_predictions) else None
            regions = self._regions_from_prediction(layout_prediction, page=page)
            if not regions:
                regions = [self._full_page_region(page)]
            page_regions[page.page_number].extend(regions)

            table_prediction = table_predictions[index] if index < len(table_predictions) else None
            table_count = float(len(self._prediction_items(table_prediction)))
            page_area = max(float(page.width * page.height), 1.0)
            region_area = sum(region.area for region in regions)
            density[f"page_{page.page_number}_coverage"] = min(1.0, region_area / page_area)
            if table_count:
                density[f"page_{page.page_number}_table_count"] = table_count
            if transcript is not None:
                text = transcript.page_texts.get(page.page_number, "")
                density[f"page_{page.page_number}_text_density"] = min(1.0, len(" ".join(text.split())) / 1200.0)

        if self._load_error:
            issues.append(
                ProcessingIssue(
                    code="layout.surya.degraded",
                    message=self._load_error,
                )
            )
        return FilledLayoutArtifact(
            page_regions=dict(page_regions),
            region_density=density,
            issues=issues,
        )

    def _fallback_layout(
        self,
        pages: Sequence[RenderedPage],
        *,
        transcript: FilledDocumentTranscript | None,
    ) -> FilledLayoutArtifact:
        page_regions: dict[int, list[BoundingBox]] = defaultdict(list)
        density: dict[str, float] = {}
        issues: list[ProcessingIssue] = []
        if self._load_error:
            issues.append(
                ProcessingIssue(
                    code="layout.surya.unavailable",
                    message=self._load_error,
                )
            )
        if transcript is not None:
            for page_number, text in transcript.page_texts.items():
                compact = " ".join((text or "").split())
                density[f"page_{page_number}_text_density"] = min(1.0, len(compact) / 1200.0)
        for page in pages:
            page_regions[page.page_number].append(self._full_page_region(page))
        return FilledLayoutArtifact(
            page_regions=dict(page_regions),
            region_density=density,
            issues=issues,
        )

    def _regions_from_prediction(self, prediction: Any, *, page: RenderedPage) -> list[BoundingBox]:
        regions: list[BoundingBox] = []
        for item in self._prediction_items(prediction):
            bbox = self._extract_bbox(item, page_number=page.page_number, page=page)
            if bbox is not None:
                regions.append(bbox)
        return regions

    def _pages_to_images(self, pages: Sequence[RenderedPage]):
        from PIL import Image

        return [Image.open(io.BytesIO(page.image_bytes)).convert("RGB") for page in pages]

    def _prediction_items(self, prediction: Any) -> list[Any]:
        if prediction is None:
            return []
        for attr in ("bboxes", "boxes", "layout", "predictions"):
            value = getattr(prediction, attr, None)
            if value:
                return list(value)
            if isinstance(prediction, dict) and prediction.get(attr):
                return list(prediction[attr])
        if isinstance(prediction, list):
            return list(prediction)
        return []

    def _extract_bbox(
        self,
        item: Any,
        *,
        page_number: int,
        page: RenderedPage,
    ) -> BoundingBox | None:
        raw_bbox = getattr(item, "bbox", None)
        if raw_bbox is None and isinstance(item, dict):
            raw_bbox = item.get("bbox")
        if raw_bbox is None:
            polygon = getattr(item, "polygon", None)
            if polygon is None and isinstance(item, dict):
                polygon = item.get("polygon") or item.get("points")
            if polygon:
                coords = [(float(point[0]), float(point[1])) for point in polygon if len(point) >= 2]
                if coords:
                    xs = [coord[0] for coord in coords]
                    ys = [coord[1] for coord in coords]
                    raw_bbox = [min(xs), min(ys), max(xs), max(ys)]
        if raw_bbox is None and isinstance(item, dict):
            maybe = [item.get("x1"), item.get("y1"), item.get("x2"), item.get("y2")]
            if all(value is not None for value in maybe):
                raw_bbox = maybe
        if raw_bbox is None:
            return None
        try:
            left, top, right, bottom = [float(value) for value in raw_bbox[:4]]
        except Exception:
            return None
        left = max(0.0, min(left, float(page.width)))
        right = max(0.0, min(right, float(page.width)))
        top = max(0.0, min(top, float(page.height)))
        bottom = max(0.0, min(bottom, float(page.height)))
        if right <= left or bottom <= top:
            return None
        return BoundingBox(
            page_number=page_number,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            reference_width=float(page.width),
            reference_height=float(page.height),
        )

    def _item_label(self, item: Any) -> str:
        if isinstance(item, dict):
            value = item.get("label") or item.get("kind") or item.get("type")
        else:
            value = getattr(item, "label", None) or getattr(item, "kind", None) or getattr(item, "type", None)
        return str(value or "region")

    def _full_page_region(self, page: RenderedPage) -> BoundingBox:
        return BoundingBox(
            page_number=page.page_number,
            left=0.0,
            top=0.0,
            right=float(page.width),
            bottom=float(page.height),
            reference_width=float(page.width),
            reference_height=float(page.height),
        )
