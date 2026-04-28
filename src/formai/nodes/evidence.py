from __future__ import annotations

from formai.artifacts import AdjudicationArtifact, EvidenceArtifact, ResolutionArtifact
from formai.models import FieldEvidence, FieldEvidenceCandidate, FieldValue
from formai.segmentation import logical_field_name
from formai.utils import average_confidence


def gather_field_evidence(
    *,
    target_fields,
    structured_data: dict[str, FieldValue],
    transcript,
    region_reads,
) -> EvidenceArtifact:
    field_lookup = {}
    for field in target_fields:
        key = logical_field_name(field.label or field.name)
        field_lookup[key] = field
        field_lookup[field.name] = field
    region_values = getattr(region_reads, "values", {}) or {}
    evidence_items: list[FieldEvidence] = []
    conflicts: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for key, value in structured_data.items():
        field = field_lookup.get(key)
        candidates = [
            FieldEvidenceCandidate(
                value=value.value,
                source=value.source_kind,
                confidence=value.confidence,
                region=field.box if field is not None else None,
                raw_text=value.raw_text,
            )
        ]
        region_value = region_values.get(key)
        if region_value is not None and region_value.value.strip():
            candidates.append(
                FieldEvidenceCandidate(
                    value=region_value.value,
                    source=region_value.source_kind,
                    confidence=region_value.confidence,
                    region=field.box if field is not None else None,
                    raw_text=region_value.raw_text,
                )
            )
            if value.value.strip() and region_value.value.strip() and value.value.strip() != region_value.value.strip():
                conflicts[key] = [value.value, region_value.value]
        if not value.value.strip():
            unresolved.append(key)
        evidence_items.append(
            FieldEvidence(
                field_key=key,
                page_number=field.page_number if field is not None else 1,
                anchor_ref=field.name if field is not None else key,
                candidate_regions=[field.box] if field is not None and field.box is not None else [],
                ocr_candidates=candidates,
                resolved_value=value.value,
                resolution_reason=value.source_kind,
                confidence_breakdown={
                    "selected": value.confidence,
                    "candidate_count": float(len(candidates)),
                    "has_region_read": 1.0 if region_value is not None else 0.0,
                },
            )
        )
    return EvidenceArtifact(
        field_evidence=evidence_items,
        unresolved_keys=sorted(set(unresolved)),
        conflicts=conflicts,
    )


def resolve_ambiguous_fields(evidence: EvidenceArtifact, adjudicator) -> AdjudicationArtifact:
    candidate_values: dict[str, FieldValue] = {}
    expected_keys: list[str] = []
    for item in evidence.field_evidence:
        if not item.ocr_candidates:
            continue
        expected_keys.append(item.field_key)
        best = max(item.ocr_candidates, key=lambda candidate: (candidate.confidence, len(candidate.value)))
        candidate_values[item.field_key] = FieldValue(
            value=best.value,
            confidence=best.confidence,
            source_key=item.field_key,
            raw_text=best.raw_text or best.value,
            source_kind=best.source,
        )
    resolved = adjudicator.adjudicate(candidate_values=candidate_values, expected_keys=expected_keys)
    return AdjudicationArtifact(
        values=resolved,
        ambiguity_count=len(evidence.conflicts),
    )


def resolve_field_values(
    *,
    structured_data: dict[str, FieldValue],
    adjudication: AdjudicationArtifact,
) -> ResolutionArtifact:
    resolved = dict(structured_data)
    for key, value in adjudication.values.items():
        current = resolved.get(key)
        if current is None or (value.value.strip() and value.confidence >= current.confidence):
            resolved[key] = value
    confidence = average_confidence((value.confidence for value in resolved.values()), default=0.0)
    return ResolutionArtifact(values=resolved, confidence=confidence)
