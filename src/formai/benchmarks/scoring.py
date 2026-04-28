from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Sequence

from formai.benchmarks.models import (
    BenchmarkAggregateMetrics,
    BenchmarkSample,
    BenchmarkSampleResult,
    PerFieldScore,
)
from formai.models import FieldKind, FieldValue, IssueSeverity, ProcessingIssue, ReviewItem
from formai.segmentation import logical_field_name
from formai.utils import (
    average_confidence,
    canonicalize_value_for_matching,
    normalize_text,
    text_similarity,
)


CONFIDENCE_BUCKETS = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.01),
)

CHECKBOX_TRUE_VALUES = {"yes", "true", "on", "checked", "1", "selected"}
CHECKBOX_FALSE_VALUES = {"no", "false", "off", "unchecked", "0", "unselected"}


def score_sample(
    sample: BenchmarkSample,
    predicted_fields: Dict[str, FieldValue],
    issues: Sequence[ProcessingIssue],
    confidence: float,
    review_items: Sequence[ReviewItem] | None = None,
) -> BenchmarkSampleResult:
    logical_predictions = {
        logical_field_name(key): value for key, value in predicted_fields.items()
    }
    normalized_predictions = {
        normalize_text(logical_field_name(key)): value for key, value in predicted_fields.items()
    }
    expected_map = {field.key: field for field in sample.expected_fields}
    normalized_expected_keys = {
        normalize_text(field.key): field.key for field in sample.expected_fields
    }
    per_field_scores: List[PerFieldScore] = []
    sample_issues = list(issues)

    for expected_field in sample.expected_fields:
        predicted = logical_predictions.get(expected_field.key)
        if predicted is None:
            predicted = normalized_predictions.get(normalize_text(expected_field.key))
        predicted_value = predicted.value if predicted else ""
        covered = bool(predicted_value.strip())
        exact_match = _values_match(
            expected_field.value,
            predicted_value,
            expected_field.field_kind,
            expected_field.key,
        )
        status = "matched" if exact_match else "missing" if not covered else "mismatch"
        if status == "missing":
            sample_issues.append(
                ProcessingIssue(
                    code="benchmark.missing_field",
                    message=f"Expected field not extracted: {expected_field.key}",
                    severity=IssueSeverity.WARNING,
                )
            )
        per_field_scores.append(
            PerFieldScore(
                key=expected_field.key,
                expected_value=expected_field.value,
                predicted_value=predicted_value,
                field_kind=expected_field.field_kind,
                page_number=expected_field.page_number,
                normalized_exact_match=exact_match,
                covered=covered,
                confidence=predicted.confidence if predicted else 0.0,
                status=status,
                source_kind=predicted.source_kind if predicted else "",
            )
        )

    for predicted_key in sorted(logical_predictions):
        if predicted_key in expected_map:
            continue
        if normalize_text(predicted_key) in normalized_expected_keys:
            continue
        sample_issues.append(
            ProcessingIssue(
                code="benchmark.unexpected_field",
                message=f"Unexpected extracted field: {predicted_key}",
                severity=IssueSeverity.WARNING,
            )
        )

    matched_count = sum(score.normalized_exact_match for score in per_field_scores)
    covered_count = sum(score.covered for score in per_field_scores)
    total_fields = max(1, len(per_field_scores))
    normalized_review_items = [
        item for item in (review_items or []) if item.reason_code != "expected_empty"
    ]

    return BenchmarkSampleResult(
        sample_id=sample.sample_id,
        predicted_fields=logical_predictions,
        per_field_scores=per_field_scores,
        review_items=list(review_items or []),
        issues=sample_issues,
        confidence=confidence,
        field_normalized_exact_match=matched_count / total_fields,
        field_coverage=covered_count / total_fields,
        document_success=matched_count == len(per_field_scores),
        normalized_document_success=matched_count == len(per_field_scores),
        review_required=bool(normalized_review_items),
    )


def aggregate_results(results: Sequence[BenchmarkSampleResult]) -> BenchmarkAggregateMetrics:
    total_fields = sum(len(result.per_field_scores) for result in results)
    matched_fields = sum(
        score.normalized_exact_match
        for result in results
        for score in result.per_field_scores
    )
    covered_fields = sum(
        score.covered
        for result in results
        for score in result.per_field_scores
    )
    document_successes = sum(result.document_success for result in results)
    normalized_document_successes = sum(
        result.normalized_document_success for result in results
    )
    review_required_count = sum(result.review_required for result in results)
    confidence_values = [result.confidence for result in results]

    bucket_counts: Dict[str, Counter] = {}
    for result in results:
        for score in result.per_field_scores:
            bucket = _bucket_label(score.confidence)
            counter = bucket_counts.setdefault(bucket, Counter())
            counter["count"] += 1
            if score.normalized_exact_match:
                counter["exact_matches"] += 1

    review_reason_counts = Counter()
    for result in results:
        for review_item in result.review_items:
            review_reason_counts[review_item.reason_code] += 1

    confidence_vs_accuracy = {}
    for bucket in _all_bucket_labels():
        counter = bucket_counts.get(bucket, Counter())
        count = counter.get("count", 0)
        confidence_vs_accuracy[bucket] = {
            "count": float(count),
            "exact_match_rate": (counter.get("exact_matches", 0) / count) if count else 0.0,
        }

    return BenchmarkAggregateMetrics(
        field_normalized_exact_match=(matched_fields / total_fields) if total_fields else 0.0,
        field_coverage=(covered_fields / total_fields) if total_fields else 0.0,
        document_success_rate=(document_successes / len(results)) if results else 0.0,
        normalized_document_success_rate=(
            normalized_document_successes / len(results)
        )
        if results
        else 0.0,
        confidence_average=average_confidence(confidence_values, default=0.0),
        review_required_rate=(review_required_count / len(results)) if results else 0.0,
        confidence_vs_accuracy=confidence_vs_accuracy,
        review_reason_counts=dict(sorted(review_reason_counts.items())),
    )


def count_issues(results: Iterable[BenchmarkSampleResult]) -> Dict[str, int]:
    counter = Counter()
    for result in results:
        for issue in result.issues:
            counter[issue.code] += 1
    return dict(sorted(counter.items()))


def _values_match(expected: str, predicted: str, field_kind: FieldKind, key: str = "") -> bool:
    if field_kind == FieldKind.CHECKBOX:
        return _normalize_checkbox_value(expected) == _normalize_checkbox_value(predicted)
    expected_canonical = canonicalize_value_for_matching(expected, key)
    predicted_canonical = canonicalize_value_for_matching(predicted, key)
    if expected_canonical == predicted_canonical:
        return True
    if _name_like_values_match(expected_canonical, predicted_canonical, key):
        return True
    return False


def _name_like_values_match(expected: str, predicted: str, key: str) -> bool:
    normalized_key = normalize_text(key)
    if "name" not in normalized_key:
        return False
    if not expected or not predicted:
        return False
    if any(character.isdigit() for character in expected + predicted):
        return False
    expected_tokens = expected.split()
    predicted_tokens = predicted.split()
    if len(expected_tokens) != len(predicted_tokens):
        return False
    if not (2 <= len(expected_tokens) <= 4):
        return False
    similarity = text_similarity(expected, predicted)
    if len(expected_tokens) == 2:
        if similarity >= 0.76:
            return True
        surname_similarity = text_similarity(expected_tokens[1], predicted_tokens[1])
        return surname_similarity >= 0.8 and similarity >= 0.69
    return similarity >= 0.84


def _normalize_checkbox_value(value: str) -> str:
    normalized = normalize_text(value)
    if normalized in CHECKBOX_TRUE_VALUES:
        return "true"
    if normalized in CHECKBOX_FALSE_VALUES:
        return "false"
    return normalized


def _bucket_label(confidence: float) -> str:
    for start, end in CONFIDENCE_BUCKETS:
        if start <= confidence < end:
            upper = 1.0 if end > 1.0 else end
            return f"{start:.1f}-{upper:.1f}"
    return "0.0-0.2"


def _all_bucket_labels() -> List[str]:
    labels = []
    for start, end in CONFIDENCE_BUCKETS:
        upper = 1.0 if end > 1.0 else end
        labels.append(f"{start:.1f}-{upper:.1f}")
    return labels
