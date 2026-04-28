from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Sequence

from formai.errors import IntegrationUnavailable
from formai.llm.contracts import (
    DocumentTranscript,
    FieldEvidenceGraph,
    RenderPlan,
    TemplatePageSummary,
    TemplateStructureGraph,
)
from formai.models import (
    DetectedField,
    DocumentFamily,
    DocumentKind,
    DocumentLanguage,
    DomainHint,
    FieldValue,
    LayoutStyle,
    RenderedPage,
    ScriptStyle,
)


class VisionLLMClient(ABC):
    @abstractmethod
    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        raise NotImplementedError

    @abstractmethod
    def extract_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        raise NotImplementedError

    def extract_structured_data_with_hint(
        self,
        pages: Sequence[RenderedPage],
        expected_keys: Sequence[str],
        ocr_hint: str,
    ) -> Dict[str, FieldValue]:
        return self.extract_structured_data(pages, expected_keys)

    def detect_template_structure(self, pages: Sequence[RenderedPage]) -> TemplateStructureGraph:
        return TemplateStructureGraph(
            pages=[
                TemplatePageSummary(
                    page_number=page.page_number,
                    width=page.width,
                    height=page.height,
                    mime_type=page.mime_type,
                )
                for page in pages
            ],
            anchor_candidates=list(self.detect_template_fields(pages)),
            source=self.__class__.__name__,
        )

    def resolve_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        return self.extract_structured_data(pages, expected_keys)

    def transcribe_document(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        return DocumentTranscript(
            pages=list(pages),
            provider=self.__class__.__name__,
            metadata={"bridge": "legacy_document_perception"},
        )

    def build_document_transcript(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        return self.transcribe_document(pages)

    def classify_document(
        self,
        pages: Sequence[RenderedPage],
        *,
        existing_field_count: int = 0,
        detected_field_count: int = 0,
        embedded_text_chars: int = 0,
    ) -> Dict[str, object]:
        route_hint = "filled_document"
        document_kind = DocumentKind.FLAT.value
        if existing_field_count > 0:
            route_hint = "existing_acroform"
            document_kind = DocumentKind.ACROFORM.value
        elif detected_field_count > 0:
            route_hint = "blank_template"
        confidence = 0.55 if pages else 0.25
        if existing_field_count > 0:
            confidence = 0.9
        elif detected_field_count > 0:
            confidence = 0.72
        elif embedded_text_chars > 600:
            confidence = 0.64
        return {
            "document_kind": document_kind,
            "route_hint": route_hint,
            "document_family": DocumentFamily.UNKNOWN.value,
            "language": DocumentLanguage.UNKNOWN.value,
            "script_style": ScriptStyle.UNKNOWN.value,
            "layout_style": LayoutStyle.UNKNOWN.value,
            "domain_hint": DomainHint.UNKNOWN.value,
            "profile": "generic_printed_form",
            "confidence": confidence,
            "review_required": confidence < 0.45,
            "summary": f"fallback classification route={route_hint}",
        }

    def adjudicate_field_candidates(
        self,
        *,
        candidate_values: Dict[str, FieldValue],
        expected_keys: Sequence[str],
    ) -> Dict[str, FieldValue]:
        return {
            key: value
            for key, value in candidate_values.items()
            if key in expected_keys and value.value.strip()
        }

    def resolve_field_evidence(
        self,
        transcript: DocumentTranscript,
        expected_keys: Sequence[str],
    ) -> FieldEvidenceGraph:
        structured = self.resolve_structured_data(transcript.pages, expected_keys)
        return FieldEvidenceGraph.from_structured_data(
            source=transcript.metadata.get("source", transcript.provider or self.__class__.__name__),
            profile_name=transcript.metadata.get("profile", transcript.provider or self.__class__.__name__),
            structured_data=structured,
        )

    def compile_render_plan(
        self,
        transcript: DocumentTranscript,
        expected_keys: Sequence[str],
    ) -> RenderPlan:
        structured = self.resolve_structured_data(transcript.pages, expected_keys)
        return RenderPlan(
            items=[],
            source=transcript.metadata.get("source", transcript.provider or self.__class__.__name__),
            profile_name=transcript.metadata.get("profile", transcript.provider or self.__class__.__name__),
            confidence=sum(item.confidence for item in structured.values()) / len(structured)
            if structured
            else 0.0,
        )

    def review_visual_alignment(
        self,
        *,
        source_pages: Sequence[RenderedPage],
        output_pages: Sequence[RenderedPage],
        expected_values: Dict[str, str],
        profile_name: str,
        prompt_hint: str = "",
    ) -> Dict[str, object]:
        raise IntegrationUnavailable("Visual verification is not implemented for this provider.")


class NullVisionLLMClient(VisionLLMClient):
    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        raise IntegrationUnavailable(
            "No vision LLM provider configured. Set OPENAI_API_KEY or provide a custom client."
        )

    def extract_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        raise IntegrationUnavailable(
            "No vision LLM provider configured. Set OPENAI_API_KEY or provide a custom client."
        )

    def resolve_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        return self.extract_structured_data(pages, expected_keys)

    def transcribe_document(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        raise IntegrationUnavailable(
            "No document perception provider configured. Provide a local or managed perception backend."
        )

    def build_document_transcript(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        raise IntegrationUnavailable(
            "No document perception provider configured. Provide a local or managed perception backend."
        )

    def classify_document(
        self,
        pages: Sequence[RenderedPage],
        *,
        existing_field_count: int = 0,
        detected_field_count: int = 0,
        embedded_text_chars: int = 0,
    ) -> Dict[str, object]:
        return super().classify_document(
            pages,
            existing_field_count=existing_field_count,
            detected_field_count=detected_field_count,
            embedded_text_chars=embedded_text_chars,
        )

    def adjudicate_field_candidates(
        self,
        *,
        candidate_values: Dict[str, FieldValue],
        expected_keys: Sequence[str],
    ) -> Dict[str, FieldValue]:
        return super().adjudicate_field_candidates(
            candidate_values=candidate_values,
            expected_keys=expected_keys,
        )

    def review_visual_alignment(
        self,
        *,
        source_pages: Sequence[RenderedPage],
        output_pages: Sequence[RenderedPage],
        expected_values: Dict[str, str],
        profile_name: str,
        prompt_hint: str = "",
    ) -> Dict[str, object]:
        raise IntegrationUnavailable(
            "No vision LLM provider configured. Set OPENAI_API_KEY or provide a custom client."
        )
