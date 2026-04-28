from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Protocol, Sequence, runtime_checkable

from formai.models import BoundingBox, DetectedField, FieldValue, RenderedPage


@dataclass(frozen=True)
class TranscriptSpan:
    text: str
    page_number: int
    box: BoundingBox | None = None
    kind: str = "text"
    confidence: float = 0.0
    region_tag: str = ""


@dataclass
class DocumentTranscript:
    pages: List[RenderedPage] = field(default_factory=list)
    spans: List[TranscriptSpan] = field(default_factory=list)
    provider: str = ""
    confidence: float = 0.0
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["pages"] = [
            {
                "page_number": page.page_number,
                "mime_type": page.mime_type,
                "width": page.width,
                "height": page.height,
            }
            for page in self.pages
        ]
        return payload


@dataclass(frozen=True)
class FieldEvidence:
    field_key: str
    page_number: int
    anchor_ref: str = ""
    candidate_regions: List[BoundingBox] = field(default_factory=list)
    ocr_candidates: List[str] = field(default_factory=list)
    resolved_value: str = ""
    resolution_reason: str = ""
    confidence_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplatePageSummary:
    page_number: int
    width: float
    height: float
    mime_type: str = ""


@dataclass
class TemplateStructureGraph:
    pages: List[TemplatePageSummary] = field(default_factory=list)
    spans: List[TranscriptSpan] = field(default_factory=list)
    anchor_candidates: List[DetectedField] = field(default_factory=list)
    source: str = ""
    confidence: float = 0.0

    def to_detected_fields(self) -> List[DetectedField]:
        return list(self.anchor_candidates)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["anchor_candidates"] = [
            _detected_field_to_dict(field) for field in self.anchor_candidates
        ]
        return payload


@dataclass
class FieldEvidenceGraph:
    field_evidence: List[FieldEvidence] = field(default_factory=list)
    source: str = ""
    profile_name: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_structured_data(
        cls,
        *,
        source: str,
        profile_name: str,
        structured_data: Dict[str, FieldValue],
        default_page_number: int = 1,
    ) -> "FieldEvidenceGraph":
        evidences = []
        for key, value in structured_data.items():
            evidences.append(
                FieldEvidence(
                    field_key=key,
                    page_number=default_page_number,
                    resolved_value=value.value,
                    resolution_reason=value.source_kind or "legacy_bridge",
                    confidence_breakdown={"field_confidence": value.confidence},
                )
            )
        confidence = 0.0
        if structured_data:
            confidence = sum(item.confidence for item in structured_data.values()) / len(structured_data)
        return cls(
            field_evidence=evidences,
            source=source,
            profile_name=profile_name,
            confidence=confidence,
        )


@dataclass(frozen=True)
class RenderPlanItem:
    field_key: str
    writer_type: str
    target_region: BoundingBox | None = None
    baseline: float = 0.0
    line_policy: str = "single"
    content_runs: List[str] = field(default_factory=list)
    font_policy: Dict[str, str] = field(default_factory=dict)


@dataclass
class RenderPlan:
    items: List[RenderPlanItem] = field(default_factory=list)
    source: str = ""
    profile_name: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class TemplateFieldDetector(Protocol):
    def detect_template_structure(self, pages: Sequence[RenderedPage]) -> TemplateStructureGraph:
        ...

    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        ...


@runtime_checkable
class DocumentPerceptionClient(Protocol):
    def transcribe_document(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        ...

    def build_document_transcript(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        ...


@runtime_checkable
class SchemaResolverClient(Protocol):
    def resolve_field_evidence(
        self,
        transcript: DocumentTranscript,
        expected_keys: Sequence[str],
    ) -> FieldEvidenceGraph:
        ...

    def resolve_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        ...


@runtime_checkable
class VisualReviewClient(Protocol):
    def review_visual_alignment(
        self,
        *,
        source_pages: Sequence[RenderedPage],
        output_pages: Sequence[RenderedPage],
        expected_values: Dict[str, str],
        profile_name: str,
        prompt_hint: str = "",
    ) -> Dict[str, object]:
        ...


def _detected_field_to_dict(field: DetectedField) -> dict:
    payload = asdict(field)
    if field.box is not None:
        payload["box"] = asdict(field.box)
    if field.continuation_box is not None:
        payload["continuation_box"] = asdict(field.continuation_box)
    return payload
