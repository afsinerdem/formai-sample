from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from formai.models import BoundingBox, FieldKind, FieldValue, ProcessingIssue, RenderedPage, ReviewItem


@dataclass
class ExpectedField:
    key: str
    value: str
    field_kind: FieldKind = FieldKind.TEXT
    box: BoundingBox | None = None
    page_number: int = 1


@dataclass
class BenchmarkSample:
    sample_id: str
    dataset: str
    split: str
    rendered_pages: List[RenderedPage] = field(default_factory=list)
    expected_fields: List[ExpectedField] = field(default_factory=list)


@dataclass
class PerFieldScore:
    key: str
    expected_value: str
    predicted_value: str
    field_kind: FieldKind
    normalized_exact_match: bool
    covered: bool
    confidence: float
    status: str
    page_number: int = 1
    source_kind: str = ""


@dataclass
class BenchmarkSampleResult:
    sample_id: str
    predicted_fields: Dict[str, FieldValue] = field(default_factory=dict)
    per_field_scores: List[PerFieldScore] = field(default_factory=list)
    review_items: List[ReviewItem] = field(default_factory=list)
    issues: List[ProcessingIssue] = field(default_factory=list)
    confidence: float = 0.0
    field_normalized_exact_match: float = 0.0
    field_coverage: float = 0.0
    document_success: bool = False
    normalized_document_success: bool = False
    review_required: bool = False


@dataclass
class BenchmarkAggregateMetrics:
    field_normalized_exact_match: float = 0.0
    field_coverage: float = 0.0
    document_success_rate: float = 0.0
    normalized_document_success_rate: float = 0.0
    confidence_average: float = 0.0
    review_required_rate: float = 0.0
    confidence_vs_accuracy: Dict[str, Dict[str, float]] = field(default_factory=dict)
    review_reason_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class BenchmarkReport:
    dataset: str
    profile: str
    split: str
    sample_count: int
    aggregate_metrics: BenchmarkAggregateMetrics
    pack: str = "custom"
    issue_counts: Dict[str, int] = field(default_factory=dict)
    sample_results: List[BenchmarkSampleResult] = field(default_factory=list)
    output_dir: Path | None = None


@dataclass
class ValidationGateResult:
    gate_name: str
    metric_name: str
    actual: float | bool
    threshold: float | bool
    passed: bool
    notes: str = ""


@dataclass
class ValidationDatasetSummary:
    dataset: str
    profile: str
    split: str
    sample_count: int
    pack: str = "custom"
    metrics: Dict[str, float] = field(default_factory=dict)
    issue_counts: Dict[str, int] = field(default_factory=dict)
    review_queue_count: int = 0
    gates: List[ValidationGateResult] = field(default_factory=list)
    passed: bool = False
    artifact_paths: Dict[str, Path] = field(default_factory=dict)


@dataclass
class ValidationReviewQueueItem:
    dataset: str
    profile: str
    sample_id: str
    field_key: str
    expected_value: str
    predicted_value: str
    confidence: float
    status: str
    page_number: int = 1
    reason_code: str = ""


@dataclass
class ValidationMatrixReport:
    dataset: str
    profile: str
    split: str
    pack: str = "custom"
    dataset_summaries: List[ValidationDatasetSummary] = field(default_factory=list)
    manual_review_queue: List[ValidationReviewQueueItem] = field(default_factory=list)
    gates: List[ValidationGateResult] = field(default_factory=list)
    passed: bool = False
    output_dir: Path | None = None


@dataclass
class SyntheticCheckResult:
    field: str
    expected: str
    actual: str
    matched: bool
    kind: str


@dataclass
class SyntheticCaseResult:
    case_id: str
    source_flat: Path
    final_pdf: Path
    checks: List[SyntheticCheckResult] = field(default_factory=list)
    issue_codes: List[str] = field(default_factory=list)
    review_reason_codes: List[str] = field(default_factory=list)
    mismatch_count: int = 0
    verification_passed: bool | None = None
    verification_score: float = 0.0
    layout_fidelity: float = 0.0
    render_readability: float = 0.0
    review_required: bool = False


@dataclass
class SyntheticAggregateMetrics:
    field_match_rate: float = 0.0
    case_success_rate: float = 0.0
    confidence_average: float = 0.0
    layout_fidelity: float = 0.0
    render_readability: float = 0.0
    critical_visual_pass_rate: float = 0.0
    review_required_rate: float = 0.0


@dataclass
class SyntheticPackReport:
    dataset: str
    profile: str
    split: str
    sample_count: int
    aggregate_metrics: SyntheticAggregateMetrics
    pack: str = "custom"
    issue_counts: Dict[str, int] = field(default_factory=dict)
    review_reason_counts: Dict[str, int] = field(default_factory=dict)
    case_results: List[SyntheticCaseResult] = field(default_factory=list)
    output_dir: Path | None = None
