from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class DocumentKind(str, Enum):
    ACROFORM = "acroform"
    FLAT = "flat"
    UNKNOWN = "unknown"


class DocumentLanguage(str, Enum):
    TR = "tr"
    EN = "en"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ScriptStyle(str, Enum):
    PRINTED = "printed"
    HANDWRITTEN = "handwritten"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class LayoutStyle(str, Enum):
    UNDERLINE_FORM = "underline_form"
    BOXED_FORM = "boxed_form"
    TABLE_FORM = "table_form"
    FREEFORM_PETITION = "freeform_petition"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class DocumentFamily(str, Enum):
    STUDENT_PETITION = "student_petition"
    APPLICATION_FORM = "application_form"
    CLAIM_FORM = "claim_form"
    CONSENT_FORM = "consent_form"
    INSURANCE_INCIDENT = "insurance_incident"
    GENERIC_FORM = "generic_form"
    UNKNOWN = "unknown"


class DomainHint(str, Enum):
    EDUCATION = "education"
    INSURANCE = "insurance"
    HR = "hr"
    OPERATIONS = "operations"
    UNKNOWN = "unknown"


class FieldKind(str, Enum):
    TEXT = "text"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    SIGNATURE = "signature"
    DATE = "date"
    NUMBER = "number"
    MULTILINE = "multiline"
    UNKNOWN = "unknown"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class MappingStatus(str, Enum):
    MAPPED = "mapped"
    NEEDS_REVIEW = "needs_review"
    UNMAPPED = "unmapped"


@dataclass
class ProcessingIssue:
    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.WARNING
    context: Dict[str, str] = field(default_factory=dict)


@dataclass
class BoundingBox:
    page_number: int
    left: float
    top: float
    right: float
    bottom: float
    reference_width: float | None = None
    reference_height: float | None = None

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)

    @property
    def area(self) -> float:
        return self.width * self.height

    def intersection_over_union(self, other: "BoundingBox") -> float:
        if self.page_number != other.page_number:
            return 0.0
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        width = max(0.0, right - left)
        height = max(0.0, bottom - top)
        intersection = width * height
        union = self.area + other.area - intersection
        if union <= 0:
            return 0.0
        return intersection / union

    def center_distance_ratio(self, other: "BoundingBox") -> float:
        if self.page_number != other.page_number:
            return 1.0
        left = (self.left + self.right) / 2.0
        top = (self.top + self.bottom) / 2.0
        other_left = (other.left + other.right) / 2.0
        other_top = (other.top + other.bottom) / 2.0
        dx = left - other_left
        dy = top - other_top
        diagonal = max((self.width ** 2 + self.height ** 2) ** 0.5, 1.0)
        return min(1.0, ((dx ** 2 + dy ** 2) ** 0.5) / diagonal)


@dataclass
class RenderedPage:
    page_number: int
    mime_type: str
    image_bytes: bytes
    width: int
    height: int


@dataclass
class DetectedField:
    label: str
    field_kind: FieldKind
    box: BoundingBox
    confidence: float
    page_hint_text: str = ""
    continuation_box: Optional[BoundingBox] = None


@dataclass
class AcroField:
    name: str
    field_kind: FieldKind
    box: Optional[BoundingBox]
    page_number: int
    value: Optional[str] = None
    label: str = ""


@dataclass
class FieldNameReview:
    current_name: str
    recommended_name: str
    is_valid: bool
    reason: str = ""


@dataclass
class FieldValue:
    value: str
    confidence: float
    source_key: str
    raw_text: str = ""
    source_kind: str = "llm_page"
    review_reasons: List[str] = field(default_factory=list)


@dataclass
class FieldMapping:
    source_key: str
    target_field: str
    confidence: float
    status: MappingStatus
    notes: str = ""


@dataclass
class ReviewItem:
    field_key: str
    predicted_value: str
    confidence: float
    reason_code: str
    raw_text: str = ""
    source_kind: str = ""


@dataclass
class DocumentIdentity:
    document_kind: DocumentKind
    language: DocumentLanguage = DocumentLanguage.UNKNOWN
    script_style: ScriptStyle = ScriptStyle.UNKNOWN
    layout_style: LayoutStyle = LayoutStyle.UNKNOWN
    document_family: DocumentFamily = DocumentFamily.UNKNOWN
    domain_hint: DomainHint = DomainHint.UNKNOWN
    profile: str = "generic_printed_form"
    confidence: float = 0.0
    signals: Dict[str, str] = field(default_factory=dict)


@dataclass
class TemplateTextSpan:
    text: str
    page_number: int
    left: float
    top: float
    right: float
    bottom: float
    font_name: str = ""


@dataclass
class TemplateRule:
    kind: str
    page_number: int
    left: float
    top: float
    right: float
    bottom: float


@dataclass
class TemplateTableCell:
    page_number: int
    row_index: int
    column_index: int
    left: float
    top: float
    right: float
    bottom: float


@dataclass
class TemplateAnchorCandidate:
    field_key: str
    page_number: int
    anchor_type: str
    label_text: str
    left: float
    top: float
    right: float
    bottom: float


@dataclass
class TemplateStructureGraph:
    page_count: int
    page_sizes: List[Dict[str, float]] = field(default_factory=list)
    spans: List[TemplateTextSpan] = field(default_factory=list)
    rules: List[TemplateRule] = field(default_factory=list)
    table_cells: List[TemplateTableCell] = field(default_factory=list)
    anchor_candidates: List[TemplateAnchorCandidate] = field(default_factory=list)

    def summary(self) -> Dict[str, object]:
        return {
            "page_count": self.page_count,
            "page_sizes": list(self.page_sizes),
            "span_count": len(self.spans),
            "rule_count": len(self.rules),
            "table_cell_count": len(self.table_cells),
            "anchor_candidate_count": len(self.anchor_candidates),
        }


@dataclass
class TranscriptSpan:
    text: str
    page_number: int
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    confidence: float = 0.0
    source: str = "ocr"


@dataclass
class TranscriptLine:
    page_number: int
    text: str
    spans: List[TranscriptSpan] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class TranscriptTableCell:
    page_number: int
    row_index: int
    column_index: int
    text: str
    confidence: float = 0.0


@dataclass
class TranscriptCheckboxState:
    page_number: int
    label: str
    state: str
    confidence: float = 0.0


@dataclass
class FilledDocumentTranscript:
    provider: str
    page_count: int
    page_texts: Dict[int, str] = field(default_factory=dict)
    lines: List[TranscriptLine] = field(default_factory=list)
    table_cells: List[TranscriptTableCell] = field(default_factory=list)
    checkbox_states: List[TranscriptCheckboxState] = field(default_factory=list)
    region_tags: List[Dict[str, object]] = field(default_factory=list)
    confidence_map: Dict[str, float] = field(default_factory=dict)

    def summary(self) -> Dict[str, object]:
        non_empty_pages = sum(1 for text in self.page_texts.values() if text.strip())
        return {
            "provider": self.provider,
            "page_count": self.page_count,
            "non_empty_page_count": non_empty_pages,
            "line_count": len(self.lines),
            "table_cell_count": len(self.table_cells),
            "checkbox_state_count": len(self.checkbox_states),
        }


@dataclass
class FieldEvidenceCandidate:
    value: str
    source: str
    confidence: float
    region: Optional[BoundingBox] = None
    raw_text: str = ""


@dataclass
class FieldEvidence:
    field_key: str
    page_number: int
    anchor_ref: str = ""
    candidate_regions: List[BoundingBox] = field(default_factory=list)
    ocr_candidates: List[FieldEvidenceCandidate] = field(default_factory=list)
    resolved_value: str = ""
    resolution_reason: str = ""
    confidence_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class RenderContentRun:
    text: str
    role: str = "value"


@dataclass
class RenderPlanItem:
    field_key: str
    writer_type: str
    page_number: int
    target_region: Optional[BoundingBox] = None
    baseline_y: float = 0.0
    line_policy: str = "single_line"
    content_runs: List[RenderContentRun] = field(default_factory=list)
    font_policy: Dict[str, float | str] = field(default_factory=dict)


@dataclass
class InputAnalysis:
    source_path: Path
    document_kind: DocumentKind
    document_identity: DocumentIdentity = field(
        default_factory=lambda: DocumentIdentity(document_kind=DocumentKind.UNKNOWN)
    )
    existing_fields: List[AcroField] = field(default_factory=list)
    detected_fields: List[DetectedField] = field(default_factory=list)
    field_name_reviews: List[FieldNameReview] = field(default_factory=list)
    routing_strategy: str = "vision_first"
    routing_diagnostics: Dict[str, str] = field(default_factory=dict)
    template_structure: Optional[TemplateStructureGraph] = None
    template_structure_summary: Dict[str, object] = field(default_factory=dict)
    page_character_counts: List[int] = field(default_factory=list)
    issues: List[ProcessingIssue] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class GenerationResult:
    output_path: Path
    acro_fields: List[AcroField] = field(default_factory=list)
    rename_map: Dict[str, str] = field(default_factory=dict)
    mappings: List[FieldMapping] = field(default_factory=list)
    issues: List[ProcessingIssue] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ExtractionResult:
    source_path: Path
    structured_data: Dict[str, FieldValue] = field(default_factory=dict)
    mappings: List[FieldMapping] = field(default_factory=list)
    review_items: List[ReviewItem] = field(default_factory=list)
    transcript: Optional[FilledDocumentTranscript] = None
    transcript_summary: Dict[str, object] = field(default_factory=dict)
    field_evidence: List[FieldEvidence] = field(default_factory=list)
    issues: List[ProcessingIssue] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class AssemblyResult:
    output_path: Path
    filled_values: Dict[str, str] = field(default_factory=dict)
    render_plan: List[RenderPlanItem] = field(default_factory=list)
    render_plan_summary: Dict[str, object] = field(default_factory=dict)
    issues: List[ProcessingIssue] = field(default_factory=list)
    confidence: float = 0.0
    self_check: Optional["SelfCheckResult"] = None


@dataclass
class SelfCheckFieldResult:
    field_name: str
    expected_value: str
    source_ocr: str = ""
    output_ocr: str = ""
    source_similarity: float = 0.0
    output_similarity: float = 0.0


@dataclass
class SelfCheckResult:
    source_reference: str
    overall_score: float
    source_score: float
    output_score: float
    passed: bool
    profile: str = "generic_printed_form"
    geometry_score: float = 0.0
    evidence_score: float = 0.0
    llm_score: float = 0.0
    critical_layout_pass: bool = False
    critical_text_pass: bool = False
    review_required: bool = False
    layout_warnings: List[str] = field(default_factory=list)
    field_results: List[SelfCheckFieldResult] = field(default_factory=list)


@dataclass
class PipelineResult:
    analysis: InputAnalysis
    generation: GenerationResult
    extraction: ExtractionResult
    assembly: AssemblyResult

    @property
    def overall_confidence(self) -> float:
        scores = [
            self.analysis.confidence,
            self.generation.confidence,
            self.extraction.confidence,
            self.assembly.confidence,
        ]
        valid_scores = [score for score in scores if score > 0]
        if not valid_scores:
            return 0.0
        return sum(valid_scores) / len(valid_scores)
