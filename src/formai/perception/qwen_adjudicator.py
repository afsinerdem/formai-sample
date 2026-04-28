from __future__ import annotations

from typing import Dict, Sequence

from formai.artifacts import VerificationArtifact
from formai.llm.base import VisionLLMClient
from formai.models import FieldValue, RenderedPage


class QwenRegionAdjudicator:
    def __init__(self, client: VisionLLMClient | None):
        self.client = client

    def adjudicate(
        self,
        *,
        candidate_values: Dict[str, FieldValue],
        expected_keys: Sequence[str],
    ) -> Dict[str, FieldValue]:
        if self.client is None:
            return {
                key: value
                for key, value in candidate_values.items()
                if key in expected_keys and value.value.strip()
            }
        try:
            resolved = self.client.adjudicate_field_candidates(
                candidate_values=candidate_values,
                expected_keys=expected_keys,
            )
        except Exception:
            resolved = {}
        if resolved:
            return resolved
        return {
            key: value
            for key, value in candidate_values.items()
            if key in expected_keys and value.value.strip()
        }


class VLMOutputVerifier:
    def __init__(self, client: VisionLLMClient | None):
        self.client = client

    def verify(
        self,
        *,
        source_pages: Sequence[RenderedPage],
        output_pages: Sequence[RenderedPage],
        expected_values: Dict[str, str],
        profile_name: str,
    ) -> VerificationArtifact:
        if self.client is None:
            return VerificationArtifact(
                passed=False,
                review_required=True,
                warnings=["verification_client_unavailable"],
            )
        try:
            payload = self.client.review_visual_alignment(
                source_pages=source_pages,
                output_pages=output_pages,
                expected_values=expected_values,
                profile_name=profile_name,
                prompt_hint="local vlm verification",
            )
        except Exception:
            return VerificationArtifact(
                passed=False,
                review_required=True,
                warnings=["verification_request_failed"],
            )
        try:
            score = float(payload.get("overall_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score > 1.0 and score <= 10.0:
            score /= 10.0
        elif score > 10.0 and score <= 100.0:
            score /= 100.0
        score = max(0.0, min(score, 1.0))
        return VerificationArtifact(
            passed=score >= 0.7,
            overall_score=score,
            llm_score=score,
            evidence_score=score,
            review_required=score < 0.7,
        )
