from __future__ import annotations

from formai.artifacts import UserFeedbackArtifact, VerificationArtifact


def build_user_feedback(
    *,
    route: str,
    confidence: float,
    verification: VerificationArtifact | None = None,
) -> UserFeedbackArtifact:
    highlights = []
    review_required = False
    summary_parts = [f"route={route}", f"confidence={confidence:.3f}"]
    if verification is not None:
        review_required = verification.review_required
        summary_parts.append(f"verify_score={verification.overall_score:.3f}")
        summary_parts.append("review=required" if verification.review_required else "review=not_required")
        if verification.passed:
            highlights.append("verification_passed")
        else:
            highlights.append("verification_failed")
        if verification.warnings:
            highlights.extend(verification.warnings[:5])
    summary = " ".join(summary_parts)
    return UserFeedbackArtifact(
        route=route,
        confidence=confidence,
        summary=summary,
        review_required=review_required,
        highlights=highlights,
    )
