from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

from formai.benchmarks.base import DatasetAdapter
from formai.benchmarks.models import BenchmarkSample, ExpectedField
from formai.errors import IntegrationUnavailable
from formai.models import BoundingBox, FieldKind, RenderedPage


FIR_REPO_URL = "https://github.com/LegalDocumentProcessing/FIR_Dataset_ICDAR2023.git"
FIR_FIELD_NAMES = {
    0: "Police Station",
    1: "Year",
    2: "Statutes",
    3: "Complainant Name",
}


class FIRAdapter(DatasetAdapter):
    dataset_name = "fir"

    def __init__(self, dataset_dir: Path | None = None, working_dir: Path | None = None):
        self.dataset_dir = Path(dataset_dir) if dataset_dir else None
        self.working_dir = Path(working_dir) if working_dir else None

    def load_samples(self, split: str, max_samples: int | None = None) -> Sequence[BenchmarkSample]:
        dataset_dir = self._ensure_dataset_dir()
        details_path = dataset_dir / "FIR_details.json"
        image_dir = dataset_dir / "FIR_images_v1"
        if not details_path.exists() or not image_dir.exists():
            raise IntegrationUnavailable(
                f"FIR dataset is incomplete under {dataset_dir}. Expected FIR_details.json and FIR_images_v1/."
            )

        annotations = json.loads(details_path.read_text(encoding="utf-8"))
        grouped: Dict[str, List[dict]] = defaultdict(list)
        for row in annotations:
            grouped[str(row["image_name"])].append(row)

        selected_names = [
            image_name
            for image_name in sorted(grouped)
            if self._in_split(image_name, split)
        ]
        if max_samples is not None:
            selected_names = selected_names[:max_samples]

        samples: List[BenchmarkSample] = []
        for image_name in selected_names:
            image_path = image_dir / image_name
            if not image_path.exists():
                continue
            rows = grouped[image_name]
            samples.append(
                BenchmarkSample(
                    sample_id=f"{self.dataset_name}:{split}:{image_name}",
                    dataset=self.dataset_name,
                    split=split,
                    rendered_pages=[self._rendered_page_from_image(image_path)],
                    expected_fields=self._expected_fields_from_rows(rows),
                )
            )
        return samples

    def _ensure_dataset_dir(self) -> Path:
        if self.dataset_dir and self.dataset_dir.exists():
            return self.dataset_dir
        if self.working_dir is None:
            raise IntegrationUnavailable(
                "FIR dataset directory is not configured. Set FORMAI_FIR_DATASET_DIR or provide a working_dir."
            )
        dataset_dir = self.working_dir / "tmp" / "datasets" / "FIR_Dataset_ICDAR2023"
        if dataset_dir.exists():
            return dataset_dir
        dataset_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", FIR_REPO_URL, str(dataset_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            raise IntegrationUnavailable(
                "FIR dataset could not be prepared automatically. Clone the dataset and set FORMAI_FIR_DATASET_DIR."
            ) from exc
        return dataset_dir

    def _expected_fields_from_rows(self, rows: Sequence[dict]) -> List[ExpectedField]:
        by_category: Dict[int, List[dict]] = defaultdict(list)
        for row in rows:
            category_id = int(row["category_id"])
            if category_id not in FIR_FIELD_NAMES:
                continue
            by_category[category_id].append(row)

        expected_fields: List[ExpectedField] = []
        for category_id, items in sorted(by_category.items()):
            sorted_items = sorted(items, key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0])))
            value = " ".join(str(item.get("text", "")).strip() for item in sorted_items if str(item.get("text", "")).strip())
            if not value:
                continue
            expected_fields.append(
                ExpectedField(
                    key=FIR_FIELD_NAMES[category_id],
                    value=value,
                    field_kind=FieldKind.TEXT,
                    box=self._merge_boxes(
                        [self._bbox_from_row(item) for item in sorted_items]
                    ),
                )
            )
        return expected_fields

    def _rendered_page_from_image(self, image_path: Path) -> RenderedPage:
        try:
            from PIL import Image
        except ImportError as exc:
            raise IntegrationUnavailable("Pillow is required to read FIR images.") from exc

        image_bytes = image_path.read_bytes()
        with Image.open(image_path) as image:
            width, height = image.size
        return RenderedPage(
            page_number=1,
            mime_type="image/jpeg",
            image_bytes=image_bytes,
            width=width,
            height=height,
        )

    def _in_split(self, image_name: str, split: str) -> bool:
        if split == "all":
            return True
        bucket = int(hashlib.md5(image_name.encode("utf-8")).hexdigest(), 16) % 10
        if split == "test":
            return bucket == 0
        if split in {"validation", "val", "dev"}:
            return bucket == 1
        if split == "train":
            return bucket >= 2
        raise ValueError("Unsupported FIR split. Use train, validation, test, or all.")

    def _bbox_from_row(self, row: dict) -> BoundingBox:
        left, top, right, bottom = [float(value) for value in row["bbox"]]
        return BoundingBox(page_number=1, left=left, top=top, right=right, bottom=bottom)

    def _merge_boxes(self, boxes: Sequence[BoundingBox]) -> BoundingBox | None:
        if not boxes:
            return None
        left = min(box.left for box in boxes)
        top = min(box.top for box in boxes)
        right = max(box.right for box in boxes)
        bottom = max(box.bottom for box in boxes)
        return BoundingBox(page_number=1, left=left, top=top, right=right, bottom=bottom)
