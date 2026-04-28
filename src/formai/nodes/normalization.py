from __future__ import annotations

from formai.artifacts import NormalizedValuesArtifact
from formai.postprocessing import apply_domain_postprocessing
from formai.profiles import normalize_structured_data_for_profile
from formai.utils import average_confidence


def normalize_turkish_values(*, resolved_values, profile: str) -> NormalizedValuesArtifact:
    normalized = normalize_structured_data_for_profile(dict(resolved_values), profile)
    normalized = apply_domain_postprocessing(normalized, profile=profile)
    confidence = average_confidence((item.confidence for item in normalized.values()), default=0.0)
    return NormalizedValuesArtifact(values=normalized, confidence=confidence)
