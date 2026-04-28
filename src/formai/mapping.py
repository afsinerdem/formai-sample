from __future__ import annotations

from typing import Dict, List, Sequence, Set, Tuple

from formai.models import (
    AcroField,
    DetectedField,
    FieldMapping,
    FieldValue,
    MappingStatus,
)
from formai.profiles import canonicalize_profile_key
from formai.utils import average_confidence, ensure_unique_slug, text_similarity


def propose_field_names(fields: Sequence[DetectedField]) -> Dict[str, str]:
    used_names: Set[str] = set()
    rename_map: Dict[str, str] = {}
    for field in fields:
        rename_map[field.label] = ensure_unique_slug(field.label, used_names)
    return rename_map


def match_detected_fields_to_acro_fields(
    detected_fields: Sequence[DetectedField],
    acro_fields: Sequence[AcroField],
) -> List[FieldMapping]:
    matches: List[FieldMapping] = []
    remaining_targets: Set[str] = {field.name for field in acro_fields}

    for detected in detected_fields:
        best_field = None
        best_score = 0.0
        for acro_field in acro_fields:
            if acro_field.name not in remaining_targets:
                continue
            if acro_field.box is None:
                continue
            iou = detected.box.intersection_over_union(acro_field.box)
            distance_score = 1.0 - detected.box.center_distance_ratio(acro_field.box)
            score = (iou * 0.7) + (distance_score * 0.3)
            if score > best_score:
                best_score = score
                best_field = acro_field

        if best_field is None:
            matches.append(
                FieldMapping(
                    source_key=detected.label,
                    target_field="",
                    confidence=0.0,
                    status=MappingStatus.UNMAPPED,
                    notes="No overlapping AcroForm widget found.",
                )
            )
            continue

        remaining_targets.remove(best_field.name)
        matches.append(
            FieldMapping(
                source_key=detected.label,
                target_field=best_field.name,
                confidence=average_confidence([best_score, detected.confidence]),
                status=MappingStatus.MAPPED if best_score >= 0.35 else MappingStatus.NEEDS_REVIEW,
                notes="Matched using widget geometry overlap.",
            )
        )

    return matches


def map_extracted_values_to_fields(
    structured_data: Dict[str, FieldValue],
    acro_fields: Sequence[AcroField],
    min_confidence: float,
    profile: str | None = None,
) -> List[FieldMapping]:
    mappings: List[FieldMapping] = []
    claimed_targets: Set[str] = set()

    for source_key, field_value in structured_data.items():
        best_target = None
        best_score = 0.0
        canonical_source = canonicalize_profile_key(source_key, profile)
        for acro_field in acro_fields:
            if acro_field.name in claimed_targets:
                continue
            target_label = acro_field.label or acro_field.name
            label_score = text_similarity(source_key, target_label)
            name_score = text_similarity(source_key, acro_field.name)
            canonical_name = canonicalize_profile_key(acro_field.name, profile)
            canonical_label = canonicalize_profile_key(target_label, profile)
            canonical_score = max(
                text_similarity(canonical_source, canonical_name),
                text_similarity(canonical_source, canonical_label),
            )
            score = max(label_score, name_score, canonical_score)
            if canonical_source and canonical_source in {canonical_name, canonical_label}:
                score = max(score, 1.0)
            if score > best_score:
                best_score = score
                best_target = acro_field

        if best_target is None:
            mappings.append(
                FieldMapping(
                    source_key=source_key,
                    target_field="",
                    confidence=0.0,
                    status=MappingStatus.UNMAPPED,
                    notes="No candidate target field available.",
                )
            )
            continue

        claimed_targets.add(best_target.name)
        final_confidence = average_confidence([best_score, field_value.confidence])
        mappings.append(
            FieldMapping(
                source_key=source_key,
                target_field=best_target.name,
                confidence=final_confidence,
                status=(
                    MappingStatus.MAPPED
                    if final_confidence >= min_confidence
                    else MappingStatus.NEEDS_REVIEW
                ),
                notes="Matched using label/name similarity.",
            )
        )

    return mappings


def resolve_filled_values(
    structured_data: Dict[str, FieldValue], mappings: Sequence[FieldMapping]
) -> Tuple[Dict[str, str], float]:
    filled_values: Dict[str, str] = {}
    confidences: List[float] = []

    for mapping in mappings:
        if not mapping.target_field or mapping.source_key not in structured_data:
            continue
        field_value = structured_data[mapping.source_key]
        filled_values[mapping.target_field] = field_value.value
        confidences.append(average_confidence([field_value.confidence, mapping.confidence]))

    return filled_values, average_confidence(confidences)
