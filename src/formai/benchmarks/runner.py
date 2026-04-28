from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Sequence

from formai.agents.data_extractor import DataExtractorAgent
from formai.benchmarks.base import DatasetAdapter
from formai.benchmarks.fir import FIRAdapter
from formai.benchmarks.funsd_plus import FUNSDPlusAdapter
from formai.benchmarks.turkish_handwritten import TurkishHandwrittenAdapter
from formai.benchmarks.turkish_petitions import TurkishPetitionsAdapter
from formai.benchmarks.turkish_printed import TurkishPrintedAdapter
from formai.benchmarks.models import (
    BenchmarkReport,
    ExpectedField,
    ValidationDatasetSummary,
    ValidationGateResult,
    ValidationMatrixReport,
    ValidationReviewQueueItem,
)
from formai.benchmarks.scoring import aggregate_results, count_issues, score_sample
from formai.benchmarks.synthetic_template import SyntheticTemplateValidator
from formai.models import AcroField
from formai.utils import slugify

RELEASE_PROFILE_BY_DATASET = {
    "funsd_plus": "general_forms",
    "fir": "handwriting",
    "turkish_printed": "turkish_printed",
    "turkish_handwritten": "turkish_handwritten",
    "turkish_petitions": "turkish_petitions",
}
RELEASE_SAMPLE_LIMITS = {
    "funsd_plus": 50,
    "fir": 30,
    "turkish_printed": 10,
    "turkish_handwritten": 10,
    "turkish_petitions": 10,
}
PACK_SAMPLE_LIMITS = {
    "funsd_plus": {"smoke": 10, "regression": 50, "tuning": 100, "release": 50},
    "fir": {"smoke": 5, "regression": 30, "tuning": 100, "release": 30},
    "template_e2e": {"smoke": 3, "regression": 10, "tuning": 10, "release": 10},
    "turkish_printed": {"smoke": 3, "regression": 10, "tuning": 25, "release": 10},
    "turkish_handwritten": {"smoke": 3, "regression": 10, "tuning": 25, "release": 10},
    "turkish_petitions": {"smoke": 3, "regression": 10, "tuning": 25, "release": 10},
}
VALIDATION_GATE_THRESHOLDS = {
    "funsd_plus": {
        "field_normalized_exact_match": 0.90,
        "field_coverage": 0.98,
    },
    "fir": {
        "field_normalized_exact_match": 0.72,
        "field_coverage": 0.88,
    },
    "template_e2e": {
        "field_match_rate": 0.97,
        "case_success_rate": 0.80,
    },
}


class BenchmarkRunner:
    def __init__(
        self,
        extractor: DataExtractorAgent,
        adapters: Dict[str, DatasetAdapter] | None = None,
        synthetic_validator: SyntheticTemplateValidator | None = None,
        pipeline_factory: Callable[[], object] | None = None,
    ):
        self.extractor = extractor
        self.pipeline_factory = pipeline_factory
        self.adapters = adapters or {
            FUNSDPlusAdapter.dataset_name: FUNSDPlusAdapter(),
            FIRAdapter.dataset_name: FIRAdapter(
                dataset_dir=Path(self.extractor.config.fir_dataset_dir)
                if self.extractor.config.fir_dataset_dir
                else None,
                working_dir=self.extractor.config.working_dir,
            ),
            TurkishPrintedAdapter.dataset_name: TurkishPrintedAdapter(
                dataset_dir=Path(self.extractor.config.turkish_printed_dataset_dir)
                if self.extractor.config.turkish_printed_dataset_dir
                else None
            ),
            TurkishHandwrittenAdapter.dataset_name: TurkishHandwrittenAdapter(
                dataset_dir=Path(self.extractor.config.turkish_handwritten_dataset_dir)
                if self.extractor.config.turkish_handwritten_dataset_dir
                else None
            ),
            TurkishPetitionsAdapter.dataset_name: TurkishPetitionsAdapter(
                dataset_dir=Path(self.extractor.config.turkish_petitions_dataset_dir)
                if self.extractor.config.turkish_petitions_dataset_dir
                else None
            ),
        }
        self.synthetic_validator = synthetic_validator or SyntheticTemplateValidator(
            self.extractor.config,
            pipeline_factory=self.pipeline_factory or (lambda: None),
        )

    def run(
        self,
        dataset_name: str,
        split: str,
        max_samples: int | None = None,
        output_dir: Path | None = None,
        profile: str = "default",
        pack: str = "custom",
    ) -> BenchmarkReport:
        adapter = self._get_adapter(dataset_name)
        dataset_limit = self._resolve_pack_limit(dataset_name=dataset_name, pack=pack)
        load_limit = self._merge_limit(max_samples, dataset_limit)
        samples = list(adapter.load_samples(split=split, max_samples=load_limit))
        samples = self._apply_pack_subset(
            dataset_name=dataset_name,
            samples=samples,
            max_samples=load_limit,
            profile=profile,
            pack=pack,
        )
        sample_results = []
        sample_pages: Dict[str, Sequence] = {}
        sample_debug: Dict[str, Dict[str, dict]] = {}
        pipeline = self.pipeline_factory() if self.pipeline_factory is not None else None
        runner = getattr(pipeline, "runner", None)

        for sample in samples:
            sample_pages[sample.sample_id] = sample.rendered_pages
            target_fields = _expected_fields_to_targets(sample.expected_fields)
            if runner is not None and getattr(runner.config, "runner_backend", "legacy") != "legacy":
                extraction_bundle = runner.extract_from_rendered_pages(
                    rendered_pages=sample.rendered_pages,
                    target_fields=target_fields,
                    source_name=sample.sample_id,
                )
                extraction = extraction_bundle["extraction"]
            else:
                extraction = self.extractor.extract_from_rendered_pages(
                    rendered_pages=sample.rendered_pages,
                    target_fields=target_fields,
                    source_name=sample.sample_id,
                )
            sample_debug[sample.sample_id] = dict(getattr(self.extractor, "last_debug_trace", {}) or {})
            sample_results.append(
                score_sample(
                    sample=sample,
                    predicted_fields=extraction.structured_data,
                    issues=extraction.issues,
                    confidence=extraction.confidence,
                    review_items=extraction.review_items,
                )
            )

        report = BenchmarkReport(
            dataset=dataset_name,
            profile=profile,
            split=split,
            sample_count=len(samples),
            aggregate_metrics=aggregate_results(sample_results),
            pack=pack,
            issue_counts=count_issues(sample_results),
            sample_results=sample_results,
            output_dir=output_dir,
        )

        if output_dir is not None:
            self.write_report(report, output_dir, sample_pages=sample_pages, sample_debug=sample_debug)
        return report

    def run_validation_matrix(
        self,
        output_dir: Path,
        split: str = "test",
        max_samples: int | None = None,
        pack: str = "smoke",
    ) -> ValidationMatrixReport:
        output_dir.mkdir(parents=True, exist_ok=True)
        dataset_root = output_dir / "dataset_summaries"
        dataset_root.mkdir(parents=True, exist_ok=True)

        funsd_dir = dataset_root / "funsd_plus"
        fir_dir = dataset_root / "fir"
        synthetic_dir = dataset_root / "template_e2e"

        funsd_report = self.run(
            dataset_name="funsd_plus",
            split=split,
            max_samples=max_samples,
            output_dir=funsd_dir,
            profile="general_forms",
            pack=pack,
        )
        fir_report = self.run(
            dataset_name="fir",
            split=split,
            max_samples=max_samples,
            output_dir=fir_dir,
            profile="handwriting",
            pack=pack,
        )
        turkish_printed_dir = dataset_root / "turkish_printed"
        turkish_handwritten_dir = dataset_root / "turkish_handwritten"
        turkish_petitions_dir = dataset_root / "turkish_petitions"
        turkish_printed_report = self.run(
            dataset_name="turkish_printed",
            split=split,
            max_samples=max_samples,
            output_dir=turkish_printed_dir,
            profile="turkish_printed",
            pack=pack,
        )
        turkish_handwritten_report = self.run(
            dataset_name="turkish_handwritten",
            split=split,
            max_samples=max_samples,
            output_dir=turkish_handwritten_dir,
            profile="turkish_handwritten",
            pack=pack,
        )
        turkish_petitions_report = self.run(
            dataset_name="turkish_petitions",
            split=split,
            max_samples=max_samples,
            output_dir=turkish_petitions_dir,
            profile="turkish_petitions",
            pack=pack,
        )
        synthetic_report = self.synthetic_validator.run(
            output_dir=synthetic_dir,
            split="validation",
            max_cases=self._merge_limit(max_samples, self._resolve_pack_limit("template_e2e", pack)),
            pack=pack,
        )

        summaries = [
            self._dataset_summary_from_benchmark(funsd_report, funsd_dir),
            self._dataset_summary_from_benchmark(fir_report, fir_dir),
            self._dataset_summary_from_benchmark(turkish_printed_report, turkish_printed_dir),
            self._dataset_summary_from_benchmark(turkish_handwritten_report, turkish_handwritten_dir),
            self._dataset_summary_from_benchmark(turkish_petitions_report, turkish_petitions_dir),
            self._dataset_summary_from_synthetic(synthetic_report, synthetic_dir),
        ]
        manual_review_queue = self._build_manual_review_queue(
            benchmark_reports=[
                funsd_report,
                fir_report,
                turkish_printed_report,
                turkish_handwritten_report,
                turkish_petitions_report,
            ],
            synthetic_report=synthetic_report,
        )
        gates = self._build_validation_gates(summaries)
        report = ValidationMatrixReport(
            dataset="validation_matrix",
            profile="validation_first",
            split=split,
            pack=pack,
            dataset_summaries=summaries,
            manual_review_queue=manual_review_queue,
            gates=gates,
            passed=all(gate.passed for gate in gates),
            output_dir=output_dir,
        )
        self.write_validation_report(report, output_dir)
        return report

    def default_output_dir(self, dataset_name: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.extractor.config.working_dir / "tmp" / "benchmarks" / dataset_name / timestamp

    def write_report(
        self,
        report: BenchmarkReport,
        output_dir: Path,
        sample_pages: Dict[str, Sequence] | None = None,
        sample_debug: Dict[str, Dict[str, dict]] | None = None,
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "summary.json"
        samples_path = output_dir / "samples.jsonl"
        worst_cases_path = output_dir / "worst_cases.md"

        summary_payload = {
            "dataset": report.dataset,
            "profile": report.profile,
            "split": report.split,
            "pack": report.pack,
            "sample_count": report.sample_count,
            "aggregate_metrics": _serialize(report.aggregate_metrics),
            "issue_counts": report.issue_counts,
        }
        summary_path.write_text(
            json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        with samples_path.open("w", encoding="utf-8") as handle:
            for sample_result in report.sample_results:
                handle.write(json.dumps(_serialize(sample_result), ensure_ascii=False) + "\n")

        worst_cases = sorted(
            report.sample_results,
            key=lambda item: (item.field_normalized_exact_match, item.confidence, item.sample_id),
        )[:10]
        worst_cases_path.write_text(_render_worst_cases_markdown(worst_cases), encoding="utf-8")
        self._write_benchmark_showcase(report, output_dir, sample_pages=sample_pages or {})
        if report.dataset == "fir":
            self._write_fir_debug_bundle(worst_cases, output_dir, sample_debug or {})
        report.output_dir = output_dir

    def _write_fir_debug_bundle(
        self,
        worst_cases: Sequence,
        output_dir: Path,
        sample_debug: Dict[str, Dict[str, dict]],
    ) -> None:
        debug_root = output_dir / "debug"
        debug_root.mkdir(parents=True, exist_ok=True)
        manifest = []
        for sample in worst_cases:
            debug = sample_debug.get(sample.sample_id)
            if not debug:
                continue
            sample_dir = debug_root / _safe_sample_dirname(sample.sample_id)
            sample_dir.mkdir(parents=True, exist_ok=True)
            page_value = {}
            crop_value = {}
            precision_value = {}
            selected_value = {}
            for key, entry in debug.items():
                page_value[key] = entry.get("page_value", "")
                crop_value[key] = entry.get("crop_value", "")
                precision_value[key] = {
                    "page": entry.get("page_precision_value", ""),
                    "crop": entry.get("crop_precision_value", ""),
                }
                selected_value[key] = {
                    "value": entry.get("selected_value", ""),
                    "source_kind": entry.get("source_kind", ""),
                }
            (sample_dir / "page_value.json").write_text(
                json.dumps(page_value, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (sample_dir / "crop_value.json").write_text(
                json.dumps(crop_value, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (sample_dir / "precision_value.json").write_text(
                json.dumps(precision_value, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (sample_dir / "selected_value.json").write_text(
                json.dumps(selected_value, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest.append(
                {
                    "sample_id": sample.sample_id,
                    "path": sample_dir,
                }
            )
        (debug_root / "manifest.json").write_text(
            json.dumps(_serialize(manifest), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def write_validation_report(self, report: ValidationMatrixReport, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_payload = {
            "dataset": report.dataset,
            "profile": report.profile,
            "split": report.split,
            "pack": report.pack,
            "passed": report.passed,
            "dataset_summaries": [_serialize(summary) for summary in report.dataset_summaries],
            "gates": [_serialize(gate) for gate in report.gates],
        }
        (output_dir / "validation_summary.json").write_text(
            json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (output_dir / "manual_review_queue.json").write_text(
            json.dumps([_serialize(item) for item in report.manual_review_queue], indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        (output_dir / "worst_cases.md").write_text(
            self._render_validation_worst_cases(report),
            encoding="utf-8",
        )
        report.output_dir = output_dir

    def _get_adapter(self, dataset_name: str) -> DatasetAdapter:
        if dataset_name not in self.adapters:
            available = ", ".join(sorted(self.adapters))
            raise ValueError(f"Unsupported benchmark dataset: {dataset_name}. Available: {available}")
        return self.adapters[dataset_name]

    def _write_benchmark_showcase(
        self,
        report: BenchmarkReport,
        output_dir: Path,
        sample_pages: Dict[str, Sequence],
    ) -> None:
        showcase_dir = output_dir / "showcase"
        showcase_dir.mkdir(parents=True, exist_ok=True)
        selected = self._select_showcase_samples(report.sample_results)
        manifest = []
        for slot, sample in selected.items():
            sample_dir = showcase_dir / slot
            sample_dir.mkdir(parents=True, exist_ok=True)
            (sample_dir / "sample_result.json").write_text(
                json.dumps(_serialize(sample), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            rendered_pages = sample_pages.get(sample.sample_id, [])
            for page in rendered_pages[:3]:
                suffix = ".png" if page.mime_type == "image/png" else ".jpg"
                (sample_dir / f"page_{page.page_number}{suffix}").write_bytes(page.image_bytes)
            manifest.append(
                {
                    "slot": slot,
                    "sample_id": sample.sample_id,
                    "exact_match": sample.field_normalized_exact_match,
                    "coverage": sample.field_coverage,
                    "confidence": sample.confidence,
                }
            )
        (showcase_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _select_showcase_samples(self, sample_results: Sequence) -> Dict[str, object]:
        if not sample_results:
            return {}
        ordered_good = sorted(
            sample_results,
            key=lambda item: (-item.field_normalized_exact_match, -item.field_coverage, -item.confidence, item.sample_id),
        )
        ordered_hard = sorted(
            sample_results,
            key=lambda item: (item.field_normalized_exact_match, item.field_coverage, item.confidence, item.sample_id),
        )
        ordered_borderline = sorted(
            sample_results,
            key=lambda item: (abs(item.field_normalized_exact_match - 0.5), item.confidence, item.sample_id),
        )
        selected = {
            "good": ordered_good[0],
            "hard": ordered_hard[0],
        }
        for candidate in ordered_borderline:
            if candidate.sample_id not in {item.sample_id for item in selected.values()}:
                selected["borderline"] = candidate
                break
        if "borderline" not in selected:
            selected["borderline"] = ordered_good[-1]
        return selected

    def _apply_pack_subset(
        self,
        dataset_name: str,
        samples: Sequence,
        max_samples: int | None,
        profile: str,
        pack: str,
    ) -> List:
        if profile not in {
            "general_forms",
            "handwriting",
            "release",
            "turkish_printed",
            "turkish_handwritten",
            "turkish_petitions",
        } and pack == "custom":
            if max_samples is not None:
                return list(samples)[:max_samples]
            return list(samples)
        limit = self._merge_limit(max_samples, self._resolve_pack_limit(dataset_name, pack))
        if limit is None:
            limit = RELEASE_SAMPLE_LIMITS.get(dataset_name, len(samples))
        return self._select_release_subset(samples, limit)

    def _resolve_pack_limit(self, dataset_name: str, pack: str) -> int | None:
        if pack == "custom":
            return None
        return PACK_SAMPLE_LIMITS.get(dataset_name, {}).get(pack)

    def _merge_limit(self, requested: int | None, default_limit: int | None) -> int | None:
        if requested is None:
            return default_limit
        if default_limit is None:
            return requested
        return min(requested, default_limit)

    def _select_release_subset(self, samples: Sequence, limit: int) -> List:
        if limit <= 0 or len(samples) <= limit:
            return list(samples)
        grouped: Dict[tuple, List] = {}
        for sample in samples:
            grouped.setdefault(self._release_bucket(sample), []).append(sample)
        for bucket_samples in grouped.values():
            bucket_samples.sort(key=lambda sample: sample.sample_id)
        selected: List = []
        bucket_keys = sorted(grouped)
        while len(selected) < limit and any(grouped.values()):
            for bucket_key in bucket_keys:
                bucket_samples = grouped[bucket_key]
                if not bucket_samples:
                    continue
                selected.append(bucket_samples.pop(0))
                if len(selected) >= limit:
                    break
        return selected

    def _release_bucket(self, sample) -> tuple:
        field_count = len(sample.expected_fields)
        if field_count <= 4:
            density = "sparse"
        elif field_count <= 8:
            density = "medium"
        else:
            density = "dense"
        multiline = any(field.field_kind.value == "multiline" for field in sample.expected_fields)
        page_count = "multi_page" if len(sample.rendered_pages) > 1 else "single_page"
        page = sample.rendered_pages[0] if sample.rendered_pages else None
        if page and page.width > page.height * 1.1:
            aspect = "landscape"
        elif page and page.height > page.width * 1.1:
            aspect = "portrait"
        else:
            aspect = "squareish"
        return density, "multiline" if multiline else "single", page_count, aspect

    def _dataset_summary_from_benchmark(
        self,
        report: BenchmarkReport,
        output_dir: Path,
    ) -> ValidationDatasetSummary:
        gates = []
        thresholds = VALIDATION_GATE_THRESHOLDS.get(report.dataset, {})
        for metric_name, threshold in thresholds.items():
            actual = getattr(report.aggregate_metrics, metric_name)
            gates.append(
                ValidationGateResult(
                    gate_name=f"{report.dataset}.{metric_name}",
                    metric_name=metric_name,
                    actual=actual,
                    threshold=threshold,
                    passed=actual >= threshold,
                )
            )
        return ValidationDatasetSummary(
            dataset=report.dataset,
            profile=report.profile,
            split=report.split,
            sample_count=report.sample_count,
            pack=report.pack,
            metrics={
                "field_normalized_exact_match": report.aggregate_metrics.field_normalized_exact_match,
                "field_coverage": report.aggregate_metrics.field_coverage,
                "document_success_rate": report.aggregate_metrics.document_success_rate,
                "normalized_document_success_rate": report.aggregate_metrics.normalized_document_success_rate,
                "confidence_average": report.aggregate_metrics.confidence_average,
                "review_required_rate": report.aggregate_metrics.review_required_rate,
            },
            issue_counts=report.issue_counts,
            review_queue_count=len(self._manual_queue_from_benchmark_report(report)),
            gates=gates,
            passed=all(gate.passed for gate in gates),
            artifact_paths={
                "summary": output_dir / "summary.json",
                "samples": output_dir / "samples.jsonl",
                "worst_cases": output_dir / "worst_cases.md",
                "showcase": output_dir / "showcase",
            },
        )

    def _dataset_summary_from_synthetic(self, report, output_dir: Path) -> ValidationDatasetSummary:
        thresholds = VALIDATION_GATE_THRESHOLDS["template_e2e"]
        gates = [
            ValidationGateResult(
                gate_name=f"template_e2e.{metric_name}",
                metric_name=metric_name,
                actual=getattr(report.aggregate_metrics, metric_name),
                threshold=threshold,
                passed=getattr(report.aggregate_metrics, metric_name) >= threshold,
            )
            for metric_name, threshold in thresholds.items()
        ]
        return ValidationDatasetSummary(
            dataset=report.dataset,
            profile=report.profile,
            split=report.split,
            sample_count=report.sample_count,
            pack=report.pack,
            metrics={
                "field_match_rate": report.aggregate_metrics.field_match_rate,
                "case_success_rate": report.aggregate_metrics.case_success_rate,
                "confidence_average": report.aggregate_metrics.confidence_average,
                "layout_fidelity": report.aggregate_metrics.layout_fidelity,
                "render_readability": report.aggregate_metrics.render_readability,
                "critical_visual_pass_rate": report.aggregate_metrics.critical_visual_pass_rate,
                "review_required_rate": report.aggregate_metrics.review_required_rate,
            },
            issue_counts=report.issue_counts,
            review_queue_count=len(self._manual_queue_from_synthetic_report(report)),
            gates=gates,
            passed=all(gate.passed for gate in gates),
            artifact_paths={
                "summary": output_dir / "summary.json",
                "report": output_dir / "report.json",
                "cases": output_dir / "cases.jsonl",
                "worst_cases": output_dir / "worst_cases.md",
                "showcase": output_dir / "showcase",
            },
        )

    def _build_validation_gates(
        self,
        summaries: Sequence[ValidationDatasetSummary],
    ) -> List[ValidationGateResult]:
        gates: List[ValidationGateResult] = []
        for summary in summaries:
            gates.extend(summary.gates)
        gates.append(
            ValidationGateResult(
                gate_name="real_demo_visual_manual_pass",
                metric_name="manual_visual_pass",
                actual=self.extractor.config.validation_real_demo_manual_pass,
                threshold=True,
                passed=bool(self.extractor.config.validation_real_demo_manual_pass),
                notes="Set FORMAI_VALIDATION_REAL_DEMO_MANUAL_PASS=true after manual visual review.",
            )
        )
        return gates

    def _build_manual_review_queue(
        self,
        benchmark_reports: Sequence[BenchmarkReport],
        synthetic_report,
    ) -> List[ValidationReviewQueueItem]:
        queue: List[ValidationReviewQueueItem] = []
        for report in benchmark_reports:
            queue.extend(self._manual_queue_from_benchmark_report(report))
        queue.extend(self._manual_queue_from_synthetic_report(synthetic_report))
        queue.sort(key=lambda item: (item.dataset, item.sample_id, item.field_key, item.reason_code))
        return queue

    def _manual_queue_from_benchmark_report(
        self,
        report: BenchmarkReport,
    ) -> List[ValidationReviewQueueItem]:
        queue: List[ValidationReviewQueueItem] = []
        for sample in report.sample_results:
            reason_by_field = {
                item.field_key: item
                for item in sample.review_items
                if item.reason_code != "expected_empty"
            }
            for score in sample.per_field_scores:
                if score.normalized_exact_match:
                    continue
                review_item = reason_by_field.get(score.key)
                queue.append(
                    ValidationReviewQueueItem(
                        dataset=report.dataset,
                        profile=report.profile,
                        sample_id=sample.sample_id,
                        field_key=score.key,
                        page_number=score.page_number,
                        expected_value=score.expected_value,
                        predicted_value=score.predicted_value,
                        confidence=score.confidence,
                        status=score.status,
                        reason_code=review_item.reason_code if review_item else "",
                    )
                )
        return queue

    def _manual_queue_from_synthetic_report(self, report) -> List[ValidationReviewQueueItem]:
        queue: List[ValidationReviewQueueItem] = []
        for case in report.case_results:
            for check in case.checks:
                if check.matched:
                    continue
                queue.append(
                    ValidationReviewQueueItem(
                        dataset=report.dataset,
                        profile=report.profile,
                        sample_id=case.case_id,
                        field_key=check.field,
                        expected_value=check.expected,
                        predicted_value=check.actual,
                        confidence=0.0,
                        status="mismatch",
                        reason_code="synthetic_mismatch",
                    )
                )
        return queue

    def _render_validation_worst_cases(self, report: ValidationMatrixReport) -> str:
        lines = ["# Validation Worst Cases", ""]
        for summary in report.dataset_summaries:
            lines.append(f"## {summary.dataset} ({summary.profile})")
            lines.append(f"- passed: `{summary.passed}`")
            for gate in summary.gates:
                lines.append(
                    f"- `{gate.metric_name}`: actual `{gate.actual}` / threshold `{gate.threshold}`"
                )
            lines.append("")
        if report.manual_review_queue:
            lines.append("## Manual Review Queue")
            for item in report.manual_review_queue[:20]:
                lines.append(
                    f"- `{item.dataset}` / `{item.sample_id}` / `{item.field_key}` => `{item.status}` {item.reason_code}".rstrip()
                )
        else:
            lines.append("## Manual Review Queue")
            lines.append("- none")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _expected_fields_to_targets(expected_fields: Sequence[ExpectedField]) -> Sequence[AcroField]:
    targets = []
    for expected in expected_fields:
        targets.append(
            AcroField(
                name=slugify(expected.key),
                field_kind=expected.field_kind,
                box=expected.box,
                page_number=expected.page_number,
                label=expected.key,
            )
        )
    return targets


def _render_worst_cases_markdown(sample_results) -> str:
    lines = ["# Worst Cases", ""]
    for sample in sample_results:
        lines.append(f"## {sample.sample_id}")
        lines.append(
            f"- exact_match: {sample.field_normalized_exact_match:.2f}, coverage: {sample.field_coverage:.2f}, confidence: {sample.confidence:.2f}"
        )
        for score in sample.per_field_scores:
            if score.normalized_exact_match:
                continue
            lines.append(f"- `{score.key}`")
            lines.append(f"  expected: `{score.expected_value}`")
            lines.append(f"  predicted: `{score.predicted_value}`")
            lines.append(f"  status: `{score.status}`")
        if sample.review_items:
            lines.append("- review:")
            for item in sample.review_items[:5]:
                lines.append(
                    f"  - `{item.field_key}` => `{item.reason_code}` ({item.confidence:.2f})"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _serialize(value):
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _safe_sample_dirname(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return safe.strip("_") or "sample"
