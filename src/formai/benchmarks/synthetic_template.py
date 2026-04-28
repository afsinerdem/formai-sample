from __future__ import annotations

import io
import json
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from formai.benchmarks.models import (
    SyntheticAggregateMetrics,
    SyntheticCaseResult,
    SyntheticCheckResult,
    SyntheticPackReport,
)
from formai.errors import IntegrationUnavailable
from formai.models import FieldValue
from formai.pdf.inspector import fill_pdf_fields
from formai.utils import average_confidence, canonicalize_value_for_matching


ID_FAMILY = (
    "driver_s_license_no_selected",
    "passport_no_selected",
    "other_selected",
)
TIME_FAMILY = ("time_am", "time_pm")
INJURY_FAMILY = ("was_anyone_injured_yes", "was_anyone_injured_no")
WITNESS_FAMILY = (
    "were_there_witnesses_to_the_incident_yes",
    "were_there_witnesses_to_the_incident_no",
)


@dataclass(frozen=True)
class SyntheticCheck:
    field: str
    expected: str
    kind: str = "text"


@dataclass(frozen=True)
class SyntheticCase:
    case_id: str
    values: Dict[str, str]
    checks: Sequence[SyntheticCheck]
    flatten_variant: str = "normal"
    flatten_dpi: int | None = None


class SyntheticTemplateValidator:
    dataset_name = "template_e2e"
    profile = "template_e2e"

    def __init__(self, config, pipeline_factory):
        self.config = config
        self.pipeline_factory = pipeline_factory

    def run(
        self,
        output_dir: Path,
        split: str = "validation",
        max_cases: int | None = None,
        pack: str = "custom",
    ) -> SyntheticPackReport:
        pipeline = self.pipeline_factory()
        fillable_template = self._resolve_fillable_template(output_dir, pipeline)
        output_dir.mkdir(parents=True, exist_ok=True)
        cached_fillable = output_dir / "fillable_template.pdf"
        if not cached_fillable.exists():
            shutil.copyfile(fillable_template, cached_fillable)
        cases = list(self._default_cases())
        if max_cases is not None:
            cases = cases[:max_cases]

        case_results: List[SyntheticCaseResult] = []
        issue_counts = Counter()
        review_reason_counts = Counter()
        confidence_values: List[float] = []
        layout_scores: List[float] = []
        readability_scores: List[float] = []
        verification_passes = 0
        review_required_cases = 0

        for case in cases:
            case_dir = output_dir / case.case_id
            case_dir.mkdir(parents=True, exist_ok=True)
            source_acro = case_dir / f"{case.case_id}_source_acro.pdf"
            source_flat = case_dir / f"{case.case_id}_source_flat.pdf"
            final_pdf = case_dir / f"{case.case_id}_final.pdf"
            extraction_json = case_dir / "extraction.json"

            fill_pdf_fields(fillable_template, case.values, source_acro)
            self._flatten_pdf(source_acro, source_flat, dpi=case.flatten_dpi or self.config.raster_dpi, variant=case.flatten_variant)

            extraction = pipeline.extract(source_flat, fillable_template)
            extraction_json.write_text(
                json.dumps(
                    {
                        "structured_data": {
                            key: {
                                "value": value.value,
                                "confidence": value.confidence,
                                "raw_text": value.raw_text,
                                "source_kind": value.source_kind,
                                "review_reasons": value.review_reasons,
                            }
                            for key, value in extraction.structured_data.items()
                        },
                        "confidence": extraction.confidence,
                        "issues": [issue.code for issue in extraction.issues],
                        "review_items": [
                            {
                                "field_key": item.field_key,
                                "predicted_value": item.predicted_value,
                                "confidence": item.confidence,
                                "reason_code": item.reason_code,
                                "raw_text": item.raw_text,
                            }
                            for item in extraction.review_items
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            try:
                assembly = pipeline.assembler.assemble(
                    fillable_template,
                    extraction,
                    final_pdf,
                    source_reference=source_flat,
                )
            except TypeError:
                assembly = pipeline.assembler.assemble(fillable_template, extraction, final_pdf)
            confidence_values.append(average_confidence([extraction.confidence, assembly.confidence], default=0.0))

            check_results = self._evaluate_case_checks(case.checks, extraction.structured_data)
            mismatch_count = sum(not check.matched for check in check_results)

            self_check = getattr(assembly, "self_check", None)
            verification_passed = None
            verification_score = 0.0
            layout_fidelity = 0.0
            render_readability = 0.0
            if self_check is not None:
                verification_passed = bool(self_check.passed)
                verification_score = float(self_check.overall_score)
                layout_fidelity = float(self_check.geometry_score)
                render_readability = float(self_check.output_score)
                layout_scores.append(layout_fidelity)
                readability_scores.append(render_readability)
                if verification_passed:
                    verification_passes += 1

            combined_issues = extraction.issues + assembly.issues
            for issue in combined_issues:
                issue_counts[issue.code] += 1
            for item in extraction.review_items:
                if item.reason_code == "expected_empty":
                    continue
                review_reason_counts[item.reason_code] += 1
            case_review_required = bool(
                [
                    item
                    for item in extraction.review_items
                    if item.reason_code != "expected_empty"
                ]
            ) or bool(self_check is not None and not self_check.passed)
            if case_review_required:
                review_required_cases += 1

            case_result = SyntheticCaseResult(
                case_id=case.case_id,
                source_flat=source_flat,
                final_pdf=final_pdf,
                checks=check_results,
                issue_codes=sorted({issue.code for issue in combined_issues}),
                review_reason_codes=sorted(
                    {
                        item.reason_code
                        for item in extraction.review_items
                        if item.reason_code != "expected_empty"
                    }
                ),
                mismatch_count=mismatch_count,
                verification_passed=verification_passed,
                verification_score=verification_score,
                layout_fidelity=layout_fidelity,
                render_readability=render_readability,
                review_required=case_review_required,
            )
            case_results.append(case_result)
            self._write_case_artifact(case_dir / "case_report.json", case_result)

        total_checks = sum(len(case.checks) for case in case_results)
        matched_checks = sum(check.matched for case in case_results for check in case.checks)
        successful_cases = sum(case.mismatch_count == 0 for case in case_results)
        report = SyntheticPackReport(
            dataset=self.dataset_name,
            profile=self.profile,
            split=split,
            sample_count=len(case_results),
            aggregate_metrics=SyntheticAggregateMetrics(
                field_match_rate=(matched_checks / total_checks) if total_checks else 0.0,
                case_success_rate=(successful_cases / len(case_results)) if case_results else 0.0,
                confidence_average=average_confidence(confidence_values, default=0.0),
                layout_fidelity=average_confidence(layout_scores, default=0.0),
                render_readability=average_confidence(readability_scores, default=0.0),
                critical_visual_pass_rate=(verification_passes / len(case_results)) if case_results else 0.0,
                review_required_rate=(review_required_cases / len(case_results)) if case_results else 0.0,
            ),
            pack=pack,
            issue_counts=dict(sorted(issue_counts.items())),
            review_reason_counts=dict(sorted(review_reason_counts.items())),
            case_results=case_results,
            output_dir=output_dir,
        )
        self.write_report(report, output_dir)
        return report

    def write_report(self, report: SyntheticPackReport, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_payload = {
            "dataset": report.dataset,
            "profile": report.profile,
            "split": report.split,
            "pack": report.pack,
            "sample_count": report.sample_count,
            "aggregate_metrics": {
                "field_match_rate": report.aggregate_metrics.field_match_rate,
                "case_success_rate": report.aggregate_metrics.case_success_rate,
                "confidence_average": report.aggregate_metrics.confidence_average,
                "layout_fidelity": report.aggregate_metrics.layout_fidelity,
                "render_readability": report.aggregate_metrics.render_readability,
                "critical_visual_pass_rate": report.aggregate_metrics.critical_visual_pass_rate,
                "review_required_rate": report.aggregate_metrics.review_required_rate,
            },
            "issue_counts": report.issue_counts,
            "review_reason_counts": report.review_reason_counts,
        }
        (output_dir / "summary.json").write_text(
            json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (output_dir / "report.json").write_text(
            json.dumps(
                {
                    **summary_payload,
                    "cases": [
                        {
                            "case_id": case.case_id,
                            "source_flat": str(case.source_flat),
                            "final_pdf": str(case.final_pdf),
                            "checks": [
                                {
                                    "field": check.field,
                                    "expected": check.expected,
                                    "actual": check.actual,
                                    "matched": check.matched,
                                    "kind": check.kind,
                                }
                                for check in case.checks
                            ],
                            "issue_codes": case.issue_codes,
                            "review_reason_codes": case.review_reason_codes,
                            "mismatch_count": case.mismatch_count,
                            "verification_passed": case.verification_passed,
                            "verification_score": case.verification_score,
                            "layout_fidelity": case.layout_fidelity,
                            "render_readability": case.render_readability,
                            "review_required": case.review_required,
                        }
                        for case in report.case_results
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        with (output_dir / "cases.jsonl").open("w", encoding="utf-8") as handle:
            for case in report.case_results:
                handle.write(
                    json.dumps(
                        {
                            "case_id": case.case_id,
                            "source_flat": str(case.source_flat),
                            "final_pdf": str(case.final_pdf),
                            "checks": [
                                {
                                    "field": check.field,
                                    "expected": check.expected,
                                    "actual": check.actual,
                                    "matched": check.matched,
                                    "kind": check.kind,
                                }
                                for check in case.checks
                            ],
                            "issue_codes": case.issue_codes,
                            "review_reason_codes": case.review_reason_codes,
                            "mismatch_count": case.mismatch_count,
                            "verification_passed": case.verification_passed,
                            "verification_score": case.verification_score,
                            "layout_fidelity": case.layout_fidelity,
                            "render_readability": case.render_readability,
                            "review_required": case.review_required,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        worst_lines = ["# Worst Cases", ""]
        for case in sorted(report.case_results, key=lambda item: (item.mismatch_count, item.case_id), reverse=True)[:10]:
            worst_lines.append(f"## {case.case_id}")
            worst_lines.append(f"- mismatch_count: {case.mismatch_count}")
            worst_lines.append(f"- review_required: {case.review_required}")
            if case.verification_passed is not None:
                worst_lines.append(
                    f"- verification: passed={case.verification_passed} score={case.verification_score:.2f} layout={case.layout_fidelity:.2f} readability={case.render_readability:.2f}"
                )
            for check in case.checks:
                if check.matched:
                    continue
                worst_lines.append(f"- `{check.field}`")
                worst_lines.append(f"  expected: `{check.expected}`")
                worst_lines.append(f"  actual: `{check.actual}`")
            if case.review_reason_codes:
                worst_lines.append(f"- review: {', '.join(case.review_reason_codes)}")
            worst_lines.append("")
        (output_dir / "worst_cases.md").write_text("\n".join(worst_lines).rstrip() + "\n", encoding="utf-8")
        self._write_showcase_bundle(report, output_dir)

    def _resolve_fillable_template(self, output_dir: Path, pipeline) -> Path:
        explicit_fillable = Path(self.config.validation_fillable_template_path) if self.config.validation_fillable_template_path else None
        if explicit_fillable and explicit_fillable.exists():
            return explicit_fillable

        demo_fillable = self.config.working_dir / "tmp" / "demo" / "ornek_real_pipeline_fillable_v23.pdf"
        if demo_fillable.exists():
            return demo_fillable

        template_path = (
            Path(self.config.validation_template_path)
            if self.config.validation_template_path
            else self.config.working_dir / "ornek" / "input.pdf"
        )
        if not template_path.exists():
            raise IntegrationUnavailable(
                "Validation template could not be found. Set FORMAI_VALIDATION_TEMPLATE_PATH or FORMAI_VALIDATION_FILLABLE_TEMPLATE_PATH."
            )

        cache_dir = output_dir / "template_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        fillable_path = cache_dir / "fillable_template.pdf"
        if fillable_path.exists():
            return fillable_path
        if pipeline is None:
            raise IntegrationUnavailable(
                "Synthetic validation requires a pipeline factory when no fillable validation template is available."
            )
        _, generation = pipeline.prepare_fillable(template_path, fillable_path)
        if not fillable_path.exists():
            raise IntegrationUnavailable("Failed to prepare validation fillable template.")
        return generation.output_path

    def _flatten_pdf(self, input_path: Path, output_path: Path, *, dpi: int, variant: str) -> None:
        try:
            import fitz
        except ImportError as exc:
            raise IntegrationUnavailable("PyMuPDF is required for synthetic validation flattening.") from exc

        scale = max(1.0, dpi / 72.0)
        target = fitz.open()
        with fitz.open(str(input_path)) as source:
            for page in source:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image_bytes = pixmap.tobytes("png")
                image_bytes = self._transform_image_bytes(image_bytes, variant)
                image_doc = fitz.open(stream=image_bytes, filetype="png")
                image_page = image_doc[0]
                flat_page = target.new_page(width=image_page.rect.width, height=image_page.rect.height)
                flat_page.insert_image(flat_page.rect, stream=image_bytes)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target.save(str(output_path))
        target.close()

    def _transform_image_bytes(self, image_bytes: bytes, variant: str) -> bytes:
        if variant == "normal":
            return image_bytes
        try:
            from PIL import Image, ImageEnhance
        except ImportError:
            return image_bytes
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if variant == "low_contrast":
            image = ImageEnhance.Contrast(image).enhance(0.72)
            image = ImageEnhance.Brightness(image).enhance(1.04)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _evaluate_case_checks(
        self,
        checks: Sequence[SyntheticCheck],
        structured_data: Dict[str, FieldValue],
    ) -> List[SyntheticCheckResult]:
        results: List[SyntheticCheckResult] = []
        for check in checks:
            if check.kind == "family":
                actual = self._selected_family_member(check.field, structured_data)
                matched = actual == check.expected
            else:
                actual = structured_data.get(check.field, FieldValue("", 0.0, check.field)).value
                matched = canonicalize_value_for_matching(actual, check.field) == canonicalize_value_for_matching(
                    check.expected,
                    check.field,
                )
            results.append(
                SyntheticCheckResult(
                    field=check.field,
                    expected=check.expected,
                    actual=actual,
                    matched=matched,
                    kind=check.kind,
                )
            )
        return results

    def _selected_family_member(
        self,
        family_name: str,
        structured_data: Dict[str, FieldValue],
    ) -> str:
        if family_name == "id_family":
            family = ID_FAMILY
        elif family_name == "time_family":
            family = TIME_FAMILY
        elif family_name == "injury_family":
            family = INJURY_FAMILY
        elif family_name == "witness_family":
            family = WITNESS_FAMILY
        else:
            return ""
        for field_name in family:
            value = structured_data.get(field_name, FieldValue("", 0.0, field_name)).value
            if canonicalize_value_for_matching(value, field_name) in {"yes", "true", "checked", "on", "selected"}:
                return field_name
        return ""

    def _write_case_artifact(self, output_path: Path, case_result: SyntheticCaseResult) -> None:
        payload = {
            "case_id": case_result.case_id,
            "source_flat": str(case_result.source_flat),
            "final_pdf": str(case_result.final_pdf),
            "checks": [
                {
                    "field": check.field,
                    "expected": check.expected,
                    "actual": check.actual,
                    "matched": check.matched,
                    "kind": check.kind,
                }
                for check in case_result.checks
            ],
            "issue_codes": case_result.issue_codes,
            "review_reason_codes": case_result.review_reason_codes,
            "mismatch_count": case_result.mismatch_count,
            "verification_passed": case_result.verification_passed,
            "verification_score": case_result.verification_score,
            "layout_fidelity": case_result.layout_fidelity,
            "render_readability": case_result.render_readability,
            "review_required": case_result.review_required,
        }
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _write_showcase_bundle(self, report: SyntheticPackReport, output_dir: Path) -> None:
        showcase_dir = output_dir / "showcase"
        showcase_dir.mkdir(parents=True, exist_ok=True)
        if not report.case_results:
            (showcase_dir / "manifest.json").write_text("[]\n", encoding="utf-8")
            return
        ordered = sorted(report.case_results, key=lambda item: (item.mismatch_count, item.case_id))
        slots = {
            "good": ordered[0],
            "hard": ordered[-1],
            "borderline": ordered[len(ordered) // 2],
        }
        manifest = []
        for slot, case in slots.items():
            slot_dir = showcase_dir / slot
            slot_dir.mkdir(parents=True, exist_ok=True)
            _copy_if_exists(case.source_flat, slot_dir / "source_flat.pdf")
            _copy_if_exists(case.final_pdf, slot_dir / "final.pdf")
            _copy_if_exists(case.final_pdf.parent / "extraction.json", slot_dir / "extraction.json")
            _copy_if_exists(output_dir / "fillable_template.pdf", slot_dir / "fillable_template.pdf")
            manifest.append(
                {
                    "slot": slot,
                    "case_id": case.case_id,
                    "mismatch_count": case.mismatch_count,
                    "review_required": case.review_required,
                    "verification_passed": case.verification_passed,
                    "verification_score": case.verification_score,
                    "issue_codes": case.issue_codes,
                    "review_reason_codes": case.review_reason_codes,
                }
            )
        (showcase_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _default_cases(self) -> Iterable[SyntheticCase]:
        return (
            SyntheticCase(
                case_id="driver_clean",
                values={
                    "date_of_report": "March 17",
                    "report_year": "26",
                    "full_name": "Mina Karlsen",
                    "address": "27 Cedar Lane, Brookfield, NJ 07004",
                    "driver_s_license_no_selected": "yes",
                    "driver_s_license_no": "K5518923 (NJ)",
                    "phone": "201-555-0187",
                    "e_mail": "mina.karlsen@example.com",
                    "date_of_incident": "March 16, 2026",
                    "time": "8:15",
                    "time_am": "yes",
                    "location": "Cedar Lane & 3rd Street, Brookfield, NJ",
                    "describe_the_incident": "I slowed for a yellow light and lightly bumped the rear bumper of the vehicle in front of me.",
                    "was_anyone_injured_no": "yes",
                    "were_there_witnesses_to_the_incident_no": "yes",
                },
                checks=(
                    SyntheticCheck("full_name", "Mina Karlsen"),
                    SyntheticCheck("driver_s_license_no", "K5518923 (NJ)"),
                    SyntheticCheck("phone", "201-555-0187"),
                    SyntheticCheck("e_mail", "mina.karlsen@example.com"),
                    SyntheticCheck("describe_the_incident", "I slowed for a yellow light and lightly bumped the rear bumper of the vehicle in front of me."),
                    SyntheticCheck("id_family", "driver_s_license_no_selected", "family"),
                    SyntheticCheck("time_family", "time_am", "family"),
                    SyntheticCheck("injury_family", "was_anyone_injured_no", "family"),
                    SyntheticCheck("witness_family", "were_there_witnesses_to_the_incident_no", "family"),
                ),
            ),
            SyntheticCase(
                case_id="passport_injury_witness",
                values={
                    "date_of_report": "April 2",
                    "report_year": "26",
                    "full_name": "Omar Reyes",
                    "address": "1180 Park Ave, Yonkers, NY 10701",
                    "passport_no_selected": "yes",
                    "passport_no": "P4481209",
                    "phone": "914-555-7720",
                    "e_mail": "omar.reyes@samplemail.com",
                    "date_of_incident": "April 1, 2026",
                    "time": "6:40",
                    "time_pm": "yes",
                    "location": "North Broadway near Ashburton Ave, Yonkers",
                    "describe_the_incident": "A delivery van changed lanes without signaling and clipped the passenger side mirror of\nmy parked car.",
                    "was_anyone_injured_yes": "yes",
                    "if_yes_describe_the_injuries": "Passenger reported mild shoulder pain but declined ambulance transport.",
                    "were_there_witnesses_to_the_incident_yes": "yes",
                    "if_yes_enter_the_witnesses_names_and_contact_info": "Witness: Lena Ortiz, 914-555-8801",
                },
                checks=(
                    SyntheticCheck("passport_no", "P4481209"),
                    SyntheticCheck("if_yes_describe_the_injuries", "Passenger reported mild shoulder pain but declined ambulance transport."),
                    SyntheticCheck("if_yes_enter_the_witnesses_names_and_contact_info", "Witness: Lena Ortiz, 914-555-8801"),
                    SyntheticCheck("id_family", "passport_no_selected", "family"),
                    SyntheticCheck("time_family", "time_pm", "family"),
                    SyntheticCheck("injury_family", "was_anyone_injured_yes", "family"),
                    SyntheticCheck("witness_family", "were_there_witnesses_to_the_incident_yes", "family"),
                ),
            ),
            SyntheticCase(
                case_id="other_id_long_incident",
                values={
                    "date_of_report": "May 11",
                    "report_year": "26",
                    "full_name": "Taylor Brooks",
                    "address": "440 Riverfront Dr, Unit 12C, Albany, NY 12207",
                    "other_selected": "yes",
                    "other": "State Employee ID SE-4471",
                    "phone": "518-555-9004",
                    "e_mail": "taylor.brooks@agency.gov",
                    "date_of_incident": "May 10, 2026",
                    "time": "7:05",
                    "time_am": "yes",
                    "location": "Exit 6 ramp toward downtown Albany",
                    "describe_the_incident": "While merging from the exit ramp, I hit debris already in the roadway and then came to a\nstop on the shoulder. A second vehicle behind me was unable to brake in time and struck my rear bumper.\nTraffic was heavy, visibility was clear, and both drivers moved their vehicles out of the lane before police arrived.",
                    "was_anyone_injured_no": "yes",
                    "were_there_witnesses_to_the_incident_yes": "yes",
                    "if_yes_enter_the_witnesses_names_and_contact_info": "Witness 1: Rob Chen, 518-555-1112. Witness 2: Keisha\nLong, 518-555-7744.",
                },
                checks=(
                    SyntheticCheck("other", "State Employee ID SE-4471"),
                    SyntheticCheck("describe_the_incident", "While merging from the exit ramp, I hit debris already in the roadway and then came to a\nstop on the shoulder. A second vehicle behind me was unable to brake in time and struck my rear bumper.\nTraffic was heavy, visibility was clear, and both drivers moved their vehicles out of the lane before police arrived."),
                    SyntheticCheck("if_yes_enter_the_witnesses_names_and_contact_info", "Witness 1: Rob Chen, 518-555-1112. Witness 2: Keisha\nLong, 518-555-7744."),
                    SyntheticCheck("id_family", "other_selected", "family"),
                    SyntheticCheck("witness_family", "were_there_witnesses_to_the_incident_yes", "family"),
                ),
            ),
            SyntheticCase(
                case_id="driver_dense_contact",
                values={
                    "date_of_report": "June 4",
                    "report_year": "26",
                    "full_name": "Jon Perez",
                    "address": "145 Maple Street, Apt 3B, Metropolis, NY 10001",
                    "driver_s_license_no_selected": "yes",
                    "driver_s_license_no": "N8830142 (NY)",
                    "phone": "555-019-3481",
                    "e_mail": "sl_jonsson@example.com",
                    "date_of_incident": "June 3, 2026",
                    "time": "8:20",
                    "time_pm": "yes",
                    "location": "Loading Dock B, 145 Maple Street",
                    "describe_the_incident": "I was backing into the loading zone when the rear bumper made contact with a low concrete barrier.",
                    "was_anyone_injured_no": "yes",
                    "were_there_witnesses_to_the_incident_yes": "yes",
                    "if_yes_enter_the_witnesses_names_and_contact_info": "Jon Perez, 555-0177, jon.perez@samplemail.com",
                },
                checks=(
                    SyntheticCheck("phone", "555-019-3481"),
                    SyntheticCheck("e_mail", "sl_jonsson@example.com"),
                    SyntheticCheck("if_yes_enter_the_witnesses_names_and_contact_info", "Jon Perez, 555-0177, jon.perez@samplemail.com"),
                    SyntheticCheck("id_family", "driver_s_license_no_selected", "family"),
                    SyntheticCheck("time_family", "time_pm", "family"),
                    SyntheticCheck("witness_family", "were_there_witnesses_to_the_incident_yes", "family"),
                ),
            ),
            SyntheticCase(
                case_id="checkbox_heavy",
                values={
                    "date_of_report": "July 8",
                    "report_year": "26",
                    "full_name": "Dana Clarke",
                    "passport_no_selected": "yes",
                    "passport_no": "X3377129",
                    "time": "11:45",
                    "time_pm": "yes",
                    "was_anyone_injured_yes": "yes",
                    "if_yes_describe_the_injuries": "Minor bruising reported by rear passenger.",
                    "were_there_witnesses_to_the_incident_yes": "yes",
                    "if_yes_enter_the_witnesses_names_and_contact_info": "Andre Mills, 212-555-7712",
                },
                checks=(
                    SyntheticCheck("passport_no", "X3377129"),
                    SyntheticCheck("if_yes_describe_the_injuries", "Minor bruising reported by rear passenger."),
                    SyntheticCheck("if_yes_enter_the_witnesses_names_and_contact_info", "Andre Mills, 212-555-7712"),
                    SyntheticCheck("id_family", "passport_no_selected", "family"),
                    SyntheticCheck("time_family", "time_pm", "family"),
                    SyntheticCheck("injury_family", "was_anyone_injured_yes", "family"),
                    SyntheticCheck("witness_family", "were_there_witnesses_to_the_incident_yes", "family"),
                ),
            ),
            SyntheticCase(
                case_id="witness_heavy",
                values={
                    "date_of_report": "August 3",
                    "report_year": "26",
                    "full_name": "Rina Patel",
                    "driver_s_license_no_selected": "yes",
                    "driver_s_license_no": "P5561204 (NJ)",
                    "time": "5:50",
                    "time_pm": "yes",
                    "describe_the_incident": "A taxi side-swiped my front fender while squeezing between lanes near the tunnel entrance.",
                    "was_anyone_injured_no": "yes",
                    "were_there_witnesses_to_the_incident_yes": "yes",
                    "if_yes_enter_the_witnesses_names_and_contact_info": "Witness 1: Marco Bell, 201-555-4400.\nWitness 2: Elena Yu, 201-555-6611.",
                },
                checks=(
                    SyntheticCheck("describe_the_incident", "A taxi side-swiped my front fender while squeezing between lanes near the tunnel entrance."),
                    SyntheticCheck("if_yes_enter_the_witnesses_names_and_contact_info", "Witness 1: Marco Bell, 201-555-4400.\nWitness 2: Elena Yu, 201-555-6611."),
                    SyntheticCheck("witness_family", "were_there_witnesses_to_the_incident_yes", "family"),
                ),
            ),
            SyntheticCase(
                case_id="injuries_heavy",
                values={
                    "date_of_report": "September 14",
                    "report_year": "26",
                    "full_name": "Lara Kim",
                    "other_selected": "yes",
                    "other": "State Contractor Badge 228",
                    "time": "9:05",
                    "time_am": "yes",
                    "describe_the_incident": "A reversing utility truck struck the open passenger door while I was unloading survey equipment.",
                    "was_anyone_injured_yes": "yes",
                    "if_yes_describe_the_injuries": "Bruising on forearm and lower back stiffness reported later that evening.",
                    "were_there_witnesses_to_the_incident_no": "yes",
                },
                checks=(
                    SyntheticCheck("other", "State Contractor Badge 228"),
                    SyntheticCheck("if_yes_describe_the_injuries", "Bruising on forearm and lower back stiffness reported later that evening."),
                    SyntheticCheck("id_family", "other_selected", "family"),
                    SyntheticCheck("injury_family", "was_anyone_injured_yes", "family"),
                    SyntheticCheck("witness_family", "were_there_witnesses_to_the_incident_no", "family"),
                ),
            ),
            SyntheticCase(
                case_id="sparse_mostly_empty",
                values={
                    "date_of_report": "October 1",
                    "report_year": "26",
                    "full_name": "Chris Mendez",
                    "driver_s_license_no_selected": "yes",
                    "driver_s_license_no": "D2201771 (PA)",
                    "phone": "610-555-2211",
                    "time": "7:30",
                    "time_am": "yes",
                    "location": "Warehouse parking row C",
                    "describe_the_incident": "Returned to parked vehicle and found rear taillight cracked.",
                    "was_anyone_injured_no": "yes",
                    "were_there_witnesses_to_the_incident_no": "yes",
                },
                checks=(
                    SyntheticCheck("full_name", "Chris Mendez"),
                    SyntheticCheck("phone", "610-555-2211"),
                    SyntheticCheck("describe_the_incident", "Returned to parked vehicle and found rear taillight cracked."),
                    SyntheticCheck("id_family", "driver_s_license_no_selected", "family"),
                    SyntheticCheck("injury_family", "was_anyone_injured_no", "family"),
                    SyntheticCheck("witness_family", "were_there_witnesses_to_the_incident_no", "family"),
                ),
            ),
            SyntheticCase(
                case_id="edge_punctuation",
                values={
                    "date_of_report": "November 6",
                    "report_year": "26",
                    "full_name": "Ana-Marie O'Neill",
                    "passport_no_selected": "yes",
                    "passport_no": "Z1188021",
                    "phone": "646-555-8812",
                    "e_mail": "ana.oneill_claims@samplemail.com",
                    "time": "4:25",
                    "time_pm": "yes",
                    "location": "W. 33rd St. / 8th Ave.",
                    "describe_the_incident": "A courier bike clipped the mirror while squeezing between stopped traffic.",
                    "was_anyone_injured_no": "yes",
                    "were_there_witnesses_to_the_incident_no": "yes",
                },
                checks=(
                    SyntheticCheck("full_name", "Ana-Marie O'Neill"),
                    SyntheticCheck("e_mail", "ana.oneill_claims@samplemail.com"),
                    SyntheticCheck("location", "W. 33rd St. / 8th Ave."),
                    SyntheticCheck("id_family", "passport_no_selected", "family"),
                ),
            ),
            SyntheticCase(
                case_id="low_contrast_flatten",
                values={
                    "date_of_report": "December 9",
                    "report_year": "26",
                    "full_name": "Leah Foster",
                    "driver_s_license_no_selected": "yes",
                    "driver_s_license_no": "F2200914 (CT)",
                    "phone": "203-555-9008",
                    "e_mail": "leah.foster@example.com",
                    "time": "3:10",
                    "time_pm": "yes",
                    "location": "Route 15 northbound shoulder",
                    "describe_the_incident": "A disabled vehicle door opened into my lane while I was passing at low speed.",
                    "was_anyone_injured_no": "yes",
                    "were_there_witnesses_to_the_incident_no": "yes",
                },
                checks=(
                    SyntheticCheck("driver_s_license_no", "F2200914 (CT)"),
                    SyntheticCheck("phone", "203-555-9008"),
                    SyntheticCheck("e_mail", "leah.foster@example.com"),
                    SyntheticCheck("time_family", "time_pm", "family"),
                ),
                flatten_variant="low_contrast",
                flatten_dpi=144,
            ),
        )


def _copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        shutil.copyfile(source, target)
