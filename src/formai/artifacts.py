from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from formai.models import (
    AcroField,
    BoundingBox,
    DetectedField,
    DocumentIdentity,
    FieldEvidence,
    FieldMapping,
    FieldValue,
    FilledDocumentTranscript,
    ProcessingIssue,
    RenderPlanItem,
    TemplateStructureGraph,
)


@dataclass(frozen=True)
class NodeMeta:
    node_name: str
    provider: str = ""
    model: str = ""
    duration_ms: int = 0
    cache_hit: bool = False
    input_hash: str = ""


@dataclass
class IntakeArtifact:
    source_path: Path
    document_identity: DocumentIdentity
    route_hint: str
    confidence: float
    summary: str = ""
    route_source: str = "analysis"
    classifier_payload: Dict[str, object] = field(default_factory=dict)
    existing_fields: List[AcroField] = field(default_factory=list)
    detected_fields: List[DetectedField] = field(default_factory=list)
    issues: List[ProcessingIssue] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="intake_document"))


@dataclass
class RouteArtifact:
    route: str
    confidence: float
    reason: str = ""
    review_required: bool = False
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="route_document"))


@dataclass
class TemplateLayoutArtifact:
    source_path: Path
    template_structure: Optional[TemplateStructureGraph] = None
    summary: Dict[str, object] = field(default_factory=dict)
    issues: List[ProcessingIssue] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="analyze_template_layout"))


@dataclass
class TemplateIdentityArtifact:
    source_path: Path
    document_identity: DocumentIdentity
    summary: str = ""
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="infer_template_identity"))


@dataclass
class FieldDetectionArtifact:
    source_path: Path
    detected_fields: List[DetectedField] = field(default_factory=list)
    confidence: float = 0.0
    issues: List[ProcessingIssue] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="detect_template_fields"))


@dataclass
class RenameArtifact:
    rename_map: Dict[str, str] = field(default_factory=dict)
    field_name_reviews: List[dict[str, object]] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="normalize_field_names"))


@dataclass
class FillablePdfArtifact:
    output_path: Path
    acro_fields: List[AcroField] = field(default_factory=list)
    mappings: List[FieldMapping] = field(default_factory=list)
    rename_map: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    issues: List[ProcessingIssue] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="generate_fillable_pdf"))


@dataclass
class LayoutValidationArtifact:
    summary: Dict[str, object] = field(default_factory=dict)
    issues: List[ProcessingIssue] = field(default_factory=list)
    confidence: float = 0.0
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="validate_widget_layout"))


@dataclass
class AcroInspectionArtifact:
    source_path: Path
    fields: List[AcroField] = field(default_factory=list)
    issues: List[ProcessingIssue] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="inspect_existing_acroform"))


@dataclass
class RasterPageRef:
    page_number: int
    path: Path
    mime_type: str
    width: int
    height: int


@dataclass
class RasterArtifact:
    source_path: Path
    dpi: int
    pages: List[RasterPageRef] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="rasterize_document"))


@dataclass
class TranscriptArtifact:
    transcript: Optional[FilledDocumentTranscript] = None
    confidence: float = 0.0
    issues: List[ProcessingIssue] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="transcribe_document"))


@dataclass
class FilledLayoutArtifact:
    page_regions: Dict[int, List[BoundingBox]] = field(default_factory=dict)
    region_density: Dict[str, float] = field(default_factory=dict)
    issues: List[ProcessingIssue] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="analyze_filled_layout"))


@dataclass
class RegionReadRequest:
    field_key: str
    page_number: int
    region: BoundingBox
    reason: str
    priority: int = 0


@dataclass
class RegionPlanArtifact:
    requests: List[RegionReadRequest] = field(default_factory=list)
    summary: Dict[str, object] = field(default_factory=dict)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="plan_region_reads"))


@dataclass
class RegionReadArtifact:
    values: Dict[str, FieldValue] = field(default_factory=dict)
    summary: Dict[str, object] = field(default_factory=dict)
    issues: List[ProcessingIssue] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="read_regions"))


@dataclass
class EvidenceArtifact:
    field_evidence: List[FieldEvidence] = field(default_factory=list)
    unresolved_keys: List[str] = field(default_factory=list)
    conflicts: Dict[str, List[str]] = field(default_factory=dict)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="gather_field_evidence"))


@dataclass
class AdjudicationArtifact:
    values: Dict[str, FieldValue] = field(default_factory=dict)
    ambiguity_count: int = 0
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="resolve_ambiguous_fields"))


@dataclass
class ResolutionArtifact:
    values: Dict[str, FieldValue] = field(default_factory=dict)
    confidence: float = 0.0
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="resolve_field_values"))


@dataclass
class NormalizedValuesArtifact:
    values: Dict[str, FieldValue] = field(default_factory=dict)
    confidence: float = 0.0
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="normalize_turkish_values"))


@dataclass
class RenderPlanArtifact:
    items: List[RenderPlanItem] = field(default_factory=list)
    summary: Dict[str, object] = field(default_factory=dict)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="compile_render_plan"))


@dataclass
class VerificationArtifact:
    passed: bool = False
    overall_score: float = 0.0
    evidence_score: float = 0.0
    llm_score: float = 0.0
    geometry_score: float = 0.0
    review_required: bool = False
    warnings: List[str] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="verify_output"))


@dataclass
class UserFeedbackArtifact:
    route: str
    confidence: float
    summary: str
    review_required: bool = False
    highlights: List[str] = field(default_factory=list)
    meta: NodeMeta = field(default_factory=lambda: NodeMeta(node_name="build_user_feedback"))
