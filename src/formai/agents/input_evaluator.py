from __future__ import annotations

from pathlib import Path
from typing import List

from formai.agents.base import BaseAgent
from formai.document_identity import infer_document_identity
from formai.errors import IntegrationUnavailable, VisionProviderError
from formai.llm.base import VisionLLMClient
from formai.models import (
    DocumentKind,
    FieldNameReview,
    InputAnalysis,
    IssueSeverity,
    ProcessingIssue,
)
from formai.pdf.profile_detectors import detect_fields_for_identity
from formai.pdf.heuristic_detector import detect_fields_from_pdf_layout
from formai.pdf.inspector import inspect_pdf_fields
from formai.pdf.rasterizer import rasterize_pdf
from formai.pdf.routing import analyze_pdf_routing
from formai.pdf.structure import build_template_structure_graph
from formai.utils import average_confidence, ensure_unique_slug, is_semantic_field_name


class InputEvaluatorAgent(BaseAgent):
    def __init__(self, config, llm_client: VisionLLMClient):
        super().__init__(config)
        self.llm_client = llm_client

    def evaluate(self, pdf_path: Path) -> InputAnalysis:
        issues: List[ProcessingIssue] = []
        try:
            existing_fields = inspect_pdf_fields(pdf_path)
        except IntegrationUnavailable as exc:
            issues.append(
                ProcessingIssue(
                    code="pdf.inspection.unavailable",
                    message=str(exc),
                    severity=IssueSeverity.ERROR,
                )
            )
            return InputAnalysis(
                source_path=pdf_path,
                document_kind=DocumentKind.UNKNOWN,
                issues=issues,
                confidence=0.0,
            )
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="pdf.inspection.failed",
                    message=f"PDF inspection failed: {exc}",
                    severity=IssueSeverity.ERROR,
                )
            )
            return InputAnalysis(
                source_path=pdf_path,
                document_kind=DocumentKind.UNKNOWN,
                issues=issues,
                confidence=0.0,
            )

        if existing_fields:
            identity = infer_document_identity(pdf_path, DocumentKind.ACROFORM)
            reviews = self._review_existing_fields(existing_fields)
            confidence = average_confidence([1.0 if review.is_valid else 0.55 for review in reviews])
            invalid_count = len([review for review in reviews if not review.is_valid])
            if invalid_count:
                issues.append(
                    ProcessingIssue(
                        code="acroform.naming.review",
                        message=f"{invalid_count} field name(s) should be normalized before downstream mapping.",
                        severity=IssueSeverity.WARNING,
                    )
                )
            return InputAnalysis(
                source_path=pdf_path,
                document_kind=DocumentKind.ACROFORM,
                document_identity=identity,
                existing_fields=existing_fields,
                field_name_reviews=reviews,
                issues=issues,
                confidence=confidence,
            )

        identity = infer_document_identity(pdf_path, DocumentKind.FLAT)
        template_structure = None
        template_structure_summary = {}
        try:
            template_structure = build_template_structure_graph(pdf_path)
            template_structure_summary = template_structure.summary()
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="template.analysis.structure_graph_failed",
                    message=f"Template structure graph build failed: {exc}",
                    severity=IssueSeverity.WARNING,
                )
            )
        try:
            routing = analyze_pdf_routing(pdf_path)
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="template.analysis.routing_failed",
                    message=f"PDF routing analysis failed: {exc}",
                    severity=IssueSeverity.WARNING,
                )
            )
            routing_strategy = "vision_first"
            page_character_counts: List[int] = []
        else:
            routing_strategy = routing.routing_strategy
            page_character_counts = routing.page_character_counts

        if routing_strategy == "structure_first":
            detected_fields = self._detect_structure_first(pdf_path, identity, issues)
        elif routing_strategy == "hybrid":
            detected_fields = self._detect_hybrid(pdf_path, identity, issues)
        else:
            detected_fields = self._detect_vision_first(pdf_path, identity, issues)

        if not detected_fields:
            issues.append(
                ProcessingIssue(
                    code="template.no_fields_detected",
                    message="Template analysis did not return any field candidates.",
                    severity=IssueSeverity.ERROR,
                )
            )

        confidence = average_confidence(
            [field.confidence for field in detected_fields], default=0.0
        )
        return InputAnalysis(
            source_path=pdf_path,
            document_kind=DocumentKind.FLAT,
            document_identity=identity,
            detected_fields=detected_fields,
            routing_strategy=routing_strategy,
            routing_diagnostics={
                "has_embedded_text": str(
                    routing.has_embedded_text if "routing" in locals() else False
                ).lower(),
                "page_count": str(len(page_character_counts)),
                "max_page_characters": str(max(page_character_counts or [0])),
                "min_page_characters": str(min(page_character_counts or [0])),
            },
            template_structure=template_structure,
            template_structure_summary=template_structure_summary,
            page_character_counts=page_character_counts,
            issues=issues,
            confidence=confidence,
        )

    def _detect_vision_first(self, pdf_path: Path, identity, issues: List[ProcessingIssue]):
        try:
            rendered_pages = rasterize_pdf(pdf_path, dpi=self.config.raster_dpi)
            detected_fields = list(self.llm_client.detect_template_fields(rendered_pages))
        except (IntegrationUnavailable, RuntimeError, VisionProviderError) as exc:
            issues.append(
                ProcessingIssue(
                    code="template.analysis.llm_unavailable",
                    message=str(exc),
                    severity=IssueSeverity.WARNING,
                )
            )
            detected_fields = []
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="template.analysis.unexpected_error",
                    message=f"Unexpected template analysis failure: {exc}",
                    severity=IssueSeverity.ERROR,
                )
            )
            return []

        if not detected_fields:
            try:
                detected_fields = detect_fields_for_identity(pdf_path, identity)
            except Exception as exc:
                issues.append(
                    ProcessingIssue(
                        code="template.analysis.profile_detector_failed",
                        message=f"Profile detector failed: {exc}",
                        severity=IssueSeverity.WARNING,
                    )
                )

        if not detected_fields:
            try:
                detected_fields = detect_fields_from_pdf_layout(pdf_path)
            except Exception as exc:
                issues.append(
                    ProcessingIssue(
                        code="template.analysis.heuristic_failed",
                        message=f"Heuristic field detection failed: {exc}",
                        severity=IssueSeverity.ERROR,
                    )
                )
                return []
        return detected_fields

    def _detect_structure_first(self, pdf_path: Path, identity, issues: List[ProcessingIssue]):
        detected_fields = []
        try:
            detected_fields = detect_fields_for_identity(pdf_path, identity)
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="template.analysis.profile_detector_failed",
                    message=f"Profile detector failed: {exc}",
                    severity=IssueSeverity.WARNING,
                )
            )

        if not detected_fields:
            try:
                detected_fields = detect_fields_from_pdf_layout(pdf_path)
            except Exception as exc:
                issues.append(
                    ProcessingIssue(
                        code="template.analysis.heuristic_failed",
                        message=f"Heuristic field detection failed: {exc}",
                        severity=IssueSeverity.WARNING,
                    )
                )

        if not detected_fields:
            try:
                rendered_pages = rasterize_pdf(pdf_path, dpi=self.config.raster_dpi)
                detected_fields = list(self.llm_client.detect_template_fields(rendered_pages))
            except (IntegrationUnavailable, RuntimeError, VisionProviderError) as exc:
                issues.append(
                    ProcessingIssue(
                        code="template.analysis.llm_unavailable",
                        message=str(exc),
                        severity=IssueSeverity.WARNING,
                    )
                )
            except Exception as exc:
                issues.append(
                    ProcessingIssue(
                        code="template.analysis.unexpected_error",
                        message=f"Unexpected template analysis failure: {exc}",
                        severity=IssueSeverity.WARNING,
                    )
                )
        return detected_fields

    def _detect_hybrid(self, pdf_path: Path, identity, issues: List[ProcessingIssue]):
        detected_fields = self._detect_structure_first(pdf_path, identity, issues)
        if detected_fields:
            return detected_fields
        return self._detect_vision_first(pdf_path, identity, issues)

    def _review_existing_fields(self, fields):
        reviews: List[FieldNameReview] = []
        used_names = set()
        for field in fields:
            recommended = ensure_unique_slug(field.label or field.name, used_names)
            is_valid = is_semantic_field_name(field.name) and field.name == recommended
            reason = ""
            if not is_valid:
                reason = "Field name should be semantic, slugified, and unique."
            reviews.append(
                FieldNameReview(
                    current_name=field.name,
                    recommended_name=recommended,
                    is_valid=is_valid,
                    reason=reason,
                )
            )
        return reviews
