from __future__ import annotations

from typing import Sequence

from formai.artifacts import IntakeArtifact, RouteArtifact
from formai.errors import IntegrationUnavailable, VisionProviderError
from formai.llm.base import VisionLLMClient
from formai.models import (
    DocumentFamily,
    DocumentIdentity,
    DocumentKind,
    DocumentLanguage,
    DomainHint,
    LayoutStyle,
    RenderedPage,
    ScriptStyle,
)


def classify_document(
    analysis,
    rendered_pages: Sequence[RenderedPage],
    intake_client: VisionLLMClient | None,
) -> dict[str, object]:
    if intake_client is None:
        return {}
    try:
        return intake_client.classify_document(
            rendered_pages[:2],
            existing_field_count=len(getattr(analysis, "existing_fields", []) or []),
            detected_field_count=len(getattr(analysis, "detected_fields", []) or []),
            embedded_text_chars=sum(getattr(analysis, "page_character_counts", []) or []),
        )
    except (IntegrationUnavailable, VisionProviderError):
        return {}
    except Exception:
        return {}


def intake_document(analysis, classification: dict[str, object] | None = None) -> IntakeArtifact:
    classification = classification or {}
    route_hint = _normalize_route_hint(classification.get("route_hint"))
    route_source = "vlm" if route_hint else "analysis"
    if not route_hint:
        route_hint = _route_from_analysis(analysis)
    identity = _merge_identity(
        analysis.document_identity,
        classification=classification,
        route_hint=route_hint,
    )
    confidence = _resolve_confidence(analysis.confidence, classification.get("confidence"))
    summary = str(classification.get("summary", "")).strip()
    if not summary:
        summary = (
            f"{identity.document_family.value} | "
            f"{identity.profile} | "
            f"route={route_hint}"
        )
    return IntakeArtifact(
        source_path=analysis.source_path,
        document_identity=identity,
        route_hint=route_hint,
        confidence=confidence,
        summary=summary,
        route_source=route_source,
        classifier_payload=dict(classification),
        existing_fields=list(analysis.existing_fields),
        detected_fields=list(analysis.detected_fields),
        issues=list(analysis.issues),
    )


def route_document(intake: IntakeArtifact) -> RouteArtifact:
    requested_review = bool(intake.classifier_payload.get("review_required", False))
    review_required = requested_review or intake.confidence < 0.45
    route = intake.route_hint if not review_required else "low_confidence_review"
    reason = intake.summary or route
    if intake.route_source:
        reason = f"{reason} [{intake.route_source}]"
    return RouteArtifact(
        route=route,
        confidence=intake.confidence,
        reason=reason,
        review_required=review_required,
    )


def _route_from_analysis(analysis) -> str:
    if analysis.document_kind == DocumentKind.ACROFORM and analysis.existing_fields:
        return "existing_acroform"
    if analysis.document_kind == DocumentKind.FLAT and analysis.detected_fields:
        return "blank_template"
    if analysis.document_kind == DocumentKind.FLAT:
        return "filled_document"
    return "low_confidence_review"


def _normalize_route_hint(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {
        "blank_template",
        "existing_acroform",
        "filled_document",
        "low_confidence_review",
    }:
        return normalized
    return ""


def _resolve_confidence(analysis_confidence: float, classified_confidence: object) -> float:
    try:
        model_confidence = float(classified_confidence or 0.0)
    except (TypeError, ValueError):
        model_confidence = 0.0
    if model_confidence > 1.0:
        model_confidence /= 100.0
    if model_confidence <= 0.0:
        return analysis_confidence
    if analysis_confidence <= 0.0:
        return model_confidence
    return max(0.0, min((analysis_confidence + model_confidence) / 2.0, 1.0))


def _merge_identity(
    identity: DocumentIdentity,
    *,
    classification: dict[str, object],
    route_hint: str,
) -> DocumentIdentity:
    document_kind = _coerce_enum(DocumentKind, classification.get("document_kind"), identity.document_kind)
    if route_hint == "existing_acroform":
        document_kind = DocumentKind.ACROFORM
    elif route_hint in {"blank_template", "filled_document"}:
        document_kind = DocumentKind.FLAT
    merged = DocumentIdentity(
        document_kind=document_kind,
        language=_coerce_enum(DocumentLanguage, classification.get("language"), identity.language),
        script_style=_coerce_enum(ScriptStyle, classification.get("script_style"), identity.script_style),
        layout_style=_coerce_enum(LayoutStyle, classification.get("layout_style"), identity.layout_style),
        document_family=_coerce_enum(
            DocumentFamily,
            classification.get("document_family"),
            identity.document_family,
        ),
        domain_hint=_coerce_enum(DomainHint, classification.get("domain_hint"), identity.domain_hint),
        profile=str(classification.get("profile") or identity.profile or "generic_printed_form"),
        confidence=_resolve_confidence(identity.confidence, classification.get("confidence")),
        signals={
            **identity.signals,
            "route_hint": route_hint,
            "route_source": "vlm" if classification else "analysis",
        },
    )
    return merged


def _coerce_enum(enum_cls, value: object, fallback):
    normalized = str(value or "").strip().lower()
    if not normalized:
        return fallback
    try:
        return enum_cls(normalized)
    except ValueError:
        return fallback
