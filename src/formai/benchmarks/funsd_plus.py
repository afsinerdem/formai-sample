from __future__ import annotations

import io
from collections import defaultdict
from typing import Dict, List, Sequence

from formai.benchmarks.base import DatasetAdapter
from formai.benchmarks.models import BenchmarkSample, ExpectedField
from formai.errors import IntegrationUnavailable
from formai.models import BoundingBox, FieldKind, RenderedPage


LABEL_OTHER = 0
LABEL_HEADER = 1
LABEL_QUESTION = 2
LABEL_ANSWER = 3


class FUNSDPlusAdapter(DatasetAdapter):
    dataset_name = "funsd_plus"

    def load_samples(self, split: str, max_samples: int | None = None) -> Sequence[BenchmarkSample]:
        load_dataset = self._import_load_dataset()
        split_spec = split if max_samples is None else f"{split}[:{max_samples}]"
        dataset = load_dataset("konfuzio/funsd_plus", split=split_spec)
        samples: List[BenchmarkSample] = []

        for index, row in enumerate(dataset):
            sample_id = f"{self.dataset_name}:{split}:{index}"
            samples.append(
                BenchmarkSample(
                    sample_id=sample_id,
                    dataset=self.dataset_name,
                    split=split,
                    rendered_pages=[self._rendered_page_from_row(row)],
                    expected_fields=self._expected_fields_from_row(row),
                )
            )

        return samples

    def _expected_fields_from_row(self, row: dict) -> List[ExpectedField]:
        grouped_text = [self._group_text(row["words"], group) for group in row["grouped_words"]]
        grouped_labels = [self._group_label(row["labels"], group) for group in row["grouped_words"]]
        grouped_boxes = [self._group_bbox(row["bboxes"], group) for group in row["grouped_words"]]
        answers_by_key: Dict[str, List[str]] = defaultdict(list)
        boxes_by_key: Dict[str, BoundingBox] = {}

        for relation in row["linked_groups"]:
            if len(relation) != 2:
                continue
            left_index, right_index = relation
            left_label = grouped_labels[left_index]
            right_label = grouped_labels[right_index]
            if {left_label, right_label} != {LABEL_QUESTION, LABEL_ANSWER}:
                continue

            question_index = left_index if left_label == LABEL_QUESTION else right_index
            answer_index = right_index if question_index == left_index else left_index
            key = grouped_text[question_index].strip()
            value = grouped_text[answer_index].strip()
            if not key or not value:
                continue
            answers_by_key[key].append(value)
            relation_box = _merge_boxes(
                grouped_boxes[question_index],
                grouped_boxes[answer_index],
            )
            if key in boxes_by_key:
                boxes_by_key[key] = _merge_boxes(boxes_by_key[key], relation_box)
            else:
                boxes_by_key[key] = relation_box

        expected_fields: List[ExpectedField] = []
        for key, values in sorted(answers_by_key.items()):
            merged_value = "\n".join(value for value in values if value)
            expected_fields.append(
                ExpectedField(
                    key=key,
                    value=merged_value,
                    field_kind=_infer_field_kind(merged_value),
                    box=boxes_by_key.get(key),
                )
            )
        return expected_fields

    def _rendered_page_from_row(self, row: dict) -> RenderedPage:
        image = row["image"]
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        width, height = image.size
        return RenderedPage(
            page_number=1,
            mime_type="image/png",
            image_bytes=buffer.getvalue(),
            width=width,
            height=height,
        )

    def _group_text(self, words: Sequence[str], indices: Sequence[int]) -> str:
        return " ".join(words[index] for index in indices).strip()

    def _group_label(self, labels: Sequence[int], indices: Sequence[int]) -> int:
        if not indices:
            return LABEL_OTHER
        group_labels = [labels[index] for index in indices]
        return max(set(group_labels), key=group_labels.count)

    def _group_bbox(self, bboxes: Sequence[Sequence[float]], indices: Sequence[int]) -> BoundingBox:
        selected = [bboxes[index] for index in indices if index < len(bboxes)]
        if not selected:
            return BoundingBox(page_number=1, left=0.0, top=0.0, right=1.0, bottom=1.0)
        left = min(float(box[0]) for box in selected)
        top = min(float(box[1]) for box in selected)
        right = max(float(box[2]) for box in selected)
        bottom = max(float(box[3]) for box in selected)
        return BoundingBox(page_number=1, left=left, top=top, right=right, bottom=bottom)

    def _import_load_dataset(self):
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise IntegrationUnavailable(
                "datasets package is not installed. Install with: pip install -e '.[benchmarks]'"
            ) from exc
        return load_dataset


def _infer_field_kind(value: str) -> FieldKind:
    normalized = " ".join(value.strip().lower().split())
    if normalized in {"yes", "no", "true", "false", "on", "off", "checked", "unchecked"}:
        return FieldKind.CHECKBOX
    if "\n" in value:
        return FieldKind.MULTILINE
    return FieldKind.TEXT


def _merge_boxes(left: BoundingBox, right: BoundingBox) -> BoundingBox:
    if left.page_number != right.page_number:
        return left
    return BoundingBox(
        page_number=left.page_number,
        left=min(left.left, right.left),
        top=min(left.top, right.top),
        right=max(left.right, right.right),
        bottom=max(left.bottom, right.bottom),
    )
