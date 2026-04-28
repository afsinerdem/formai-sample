from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Sequence

from formai.models import AcroField, DetectedField, FieldMapping, MappingStatus


@dataclass
class LayoutValidationResult:
    mean_iou: float = 0.0
    geometry_score: float = 0.0
    overlap_pair_count: int = 0
    low_alignment_fields: list[str] = field(default_factory=list)
    tiny_fields: list[str] = field(default_factory=list)
    row_misaligned_fields: list[str] = field(default_factory=list)
    early_start_fields: list[str] = field(default_factory=list)
    table_overflow_fields: list[str] = field(default_factory=list)


def validate_field_layout(
    detected_fields: Sequence[DetectedField],
    acro_fields: Sequence[AcroField],
    mappings: Sequence[FieldMapping],
) -> LayoutValidationResult:
    result = LayoutValidationResult()
    by_name = {field.name: field for field in acro_fields}
    ious: list[float] = []
    alignment_scores: list[float] = []

    for mapping in mappings:
        if mapping.status != MappingStatus.MAPPED or not mapping.target_field:
            continue
        detected = next((field for field in detected_fields if field.label == mapping.source_key), None)
        acro = by_name.get(mapping.target_field)
        if detected is None or acro is None or detected.box is None or acro.box is None:
            continue
        iou = detected.box.intersection_over_union(acro.box)
        ious.append(iou)
        center_distance = detected.box.center_distance_ratio(acro.box)
        width_ratio = _ratio(detected.box.width, acro.box.width)
        height_ratio = _ratio(detected.box.height, acro.box.height)
        alignment_score = max(
            0.0,
            min(
                1.0,
                (iou * 0.52)
                + ((1.0 - center_distance) * 0.26)
                + (width_ratio * 0.14)
                + (height_ratio * 0.08),
            ),
        )
        alignment_scores.append(alignment_score)
        if alignment_score < 0.68:
            result.low_alignment_fields.append(mapping.target_field)
        row_delta_ratio = abs(_center_y(detected.box) - _center_y(acro.box)) / max(detected.box.height, 1.0)
        if row_delta_ratio > 0.45:
            result.row_misaligned_fields.append(mapping.target_field)
        if acro.box.left < (detected.box.left - 4.0):
            result.early_start_fields.append(mapping.target_field)
        if (
            acro.box.right > (detected.box.right + 4.0)
            or acro.box.bottom > (detected.box.bottom + 4.0)
        ):
            result.table_overflow_fields.append(mapping.target_field)

    for field in acro_fields:
        if field.box is None:
            continue
        if field.box.width < 15.0 or field.box.height < 8.0:
            result.tiny_fields.append(field.name)

    overlap_pair_count = 0
    for left, right in combinations([field for field in acro_fields if field.box is not None], 2):
        if left.page_number != right.page_number:
            continue
        if left.box.intersection_over_union(right.box) > 0.04:
            overlap_pair_count += 1

    result.mean_iou = round(sum(ious) / len(ious), 4) if ious else 0.0
    overlap_penalty = min(1.0, overlap_pair_count * 0.18)
    tiny_penalty = min(1.0, len(result.tiny_fields) * 0.12)
    alignment_component = sum(alignment_scores) / len(alignment_scores) if alignment_scores else 0.0
    result.geometry_score = round(
        max(0.0, min(1.0, alignment_component - overlap_penalty - tiny_penalty)),
        4,
    )
    result.overlap_pair_count = overlap_pair_count
    result.low_alignment_fields = sorted(set(result.low_alignment_fields))
    result.tiny_fields = sorted(set(result.tiny_fields))
    result.row_misaligned_fields = sorted(set(result.row_misaligned_fields))
    result.early_start_fields = sorted(set(result.early_start_fields))
    result.table_overflow_fields = sorted(set(result.table_overflow_fields))
    return result


def _ratio(left: float, right: float) -> float:
    maximum = max(left, right, 1.0)
    return min(left, right) / maximum


def _center_y(box) -> float:
    return (box.top + box.bottom) / 2.0
