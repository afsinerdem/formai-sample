from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List

from formai.agents.data_extractor import DataExtractorAgent
from formai.benchmarks.models import BenchmarkSample, ExpectedField
from formai.benchmarks.scoring import score_sample
from formai.config import FormAIConfig
from formai.models import FieldKind, RenderedPage
from formai.pipeline import build_default_pipeline
from formai.pdf.inspector import inspect_pdf_fields


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Turkish petition baseline report.")
    parser.add_argument("--template", required=True, help="Path to the petition template PDF.")
    parser.add_argument("--out-dir", required=True, help="Directory for reports and artifacts.")
    parser.add_argument(
        "--filled",
        default="",
        help="Optional filled sample path (PDF or image). If omitted, analyze + fillable reports only.",
    )
    parser.add_argument(
        "--expected-json",
        default="",
        help="Optional expected field JSON for field-by-field evaluation.",
    )
    args = parser.parse_args()

    root = Path.cwd()
    config = FormAIConfig.from_env(root)
    pipeline = build_default_pipeline(config)

    template_path = Path(args.template).expanduser().resolve()
    filled_path = Path(args.filled).expanduser().resolve() if args.filled else None
    expected_path = Path(args.expected_json).expanduser().resolve() if args.expected_json else None
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    analysis = pipeline.analyze(template_path)
    fillable_path = out_dir / "fillable.pdf"
    analysis, generation = pipeline.prepare_fillable(template_path, fillable_path)

    _write_json(out_dir / "analysis.json", analysis)
    if analysis.template_structure is not None:
        _write_json(out_dir / "template_structure.json", analysis.template_structure)
    _write_json(out_dir / "generation.json", generation)
    fillable_fields = inspect_pdf_fields(fillable_path)
    _write_json(out_dir / "fillable_fields.json", fillable_fields)
    overlap_report = _build_overlap_report(fillable_fields)
    _write_json(out_dir / "fillable_overlap_report.json", overlap_report)

    summary: Dict[str, Any] = {
        "template_path": str(template_path),
        "filled_path": str(filled_path) if filled_path else "",
        "profile": analysis.document_identity.profile,
        "document_family": analysis.document_identity.document_family.value,
        "analysis_confidence": analysis.confidence,
        "detected_field_count": len(analysis.detected_fields),
        "generated_field_count": len(generation.acro_fields),
        "fillable_overlap_pair_count": len(overlap_report),
        "artifacts": {
            "analysis": str(out_dir / "analysis.json"),
            "generation": str(out_dir / "generation.json"),
            "fillable": str(fillable_path),
            "fillable_fields": str(out_dir / "fillable_fields.json"),
            "fillable_overlap_report": str(out_dir / "fillable_overlap_report.json"),
        },
    }
    if analysis.template_structure is not None:
        summary["artifacts"]["template_structure"] = str(out_dir / "template_structure.json")

    if filled_path:
        extraction = _extract_from_path(
            extractor=pipeline.extractor,
            filled_path=filled_path,
            target_fields=generation.acro_fields,
        )
        final_path = out_dir / "final.pdf"
        assembly = pipeline.assembler.assemble(
            fillable_path,
            extraction,
            final_path,
            source_reference=filled_path,
        )
        _write_json(out_dir / "extraction.json", extraction)
        if extraction.transcript is not None:
            _write_json(out_dir / "filled_transcript.json", extraction.transcript)
        if extraction.field_evidence:
            _write_json(out_dir / "field_evidence.json", extraction.field_evidence)
        _write_json(out_dir / "assembly.json", assembly)
        if assembly.render_plan:
            _write_json(
                out_dir / "render_plan.json",
                {
                    "render_plan_summary": dict(assembly.render_plan_summary),
                    "items": list(assembly.render_plan),
                },
            )
        summary["extraction_confidence"] = extraction.confidence
        summary["review_item_count"] = len(extraction.review_items)
        summary["artifacts"].update(
            {
                "extraction": str(out_dir / "extraction.json"),
                "assembly": str(out_dir / "assembly.json"),
                "final": str(final_path),
            }
        )
        if extraction.transcript is not None:
            summary["artifacts"]["filled_transcript"] = str(out_dir / "filled_transcript.json")
        if extraction.field_evidence:
            summary["artifacts"]["field_evidence"] = str(out_dir / "field_evidence.json")
        if assembly.render_plan:
            summary["artifacts"]["render_plan"] = str(out_dir / "render_plan.json")
        if assembly.self_check is not None:
            _write_json(out_dir / "self_check.json", assembly.self_check)
            summary["self_check_passed"] = assembly.self_check.passed
            summary["self_check_overall_score"] = assembly.self_check.overall_score
            summary["artifacts"]["self_check"] = str(out_dir / "self_check.json")
        if expected_path and expected_path.exists():
            expected_fields = _load_expected_fields(expected_path)
            sample = BenchmarkSample(
                sample_id="turkish_petition_gold",
                dataset="turkish_petitions",
                split="gold_real",
                expected_fields=expected_fields,
            )
            report = score_sample(
                sample=sample,
                predicted_fields=extraction.structured_data,
                issues=extraction.issues,
                confidence=extraction.confidence,
                review_items=extraction.review_items,
            )
            _write_json(out_dir / "field_report.json", report)
            summary["field_normalized_exact_match"] = report.field_normalized_exact_match
            summary["field_coverage"] = report.field_coverage
            summary["document_success"] = report.document_success
            summary["artifacts"]["field_report"] = str(out_dir / "field_report.json")

    _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _extract_from_path(
    *,
    extractor: DataExtractorAgent,
    filled_path: Path,
    target_fields,
):
    suffix = filled_path.suffix.lower()
    if suffix == ".pdf":
        return extractor.extract(filled_path, target_fields)
    rendered_pages = [_render_image_page(filled_path)]
    return extractor.extract_from_rendered_pages(
        rendered_pages=rendered_pages,
        target_fields=target_fields,
        source_name=str(filled_path),
    )


def _render_image_page(image_path: Path) -> RenderedPage:
    from PIL import Image

    image = Image.open(image_path)
    width, height = image.size
    mime_type = "image/png"
    image_bytes = image_path.read_bytes()
    if image_path.suffix.lower() in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    return RenderedPage(
        page_number=1,
        mime_type=mime_type,
        image_bytes=image_bytes,
        width=width,
        height=height,
    )


def _load_expected_fields(path: Path) -> List[ExpectedField]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = [{"key": key, "value": value} for key, value in payload.items()]
    expected: List[ExpectedField] = []
    for item in payload:
        expected.append(
            ExpectedField(
                key=str(item["key"]),
                value=str(item.get("value", "")),
                field_kind=FieldKind(str(item.get("kind", "text"))),
            )
        )
    return expected


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _build_overlap_report(fields) -> List[Dict[str, Any]]:
    overlaps: List[Dict[str, Any]] = []
    for index, left in enumerate(fields):
        if left.box is None:
            continue
        for right in fields[index + 1 :]:
            if right.box is None:
                continue
            iou = left.box.intersection_over_union(right.box)
            if iou <= 0.04:
                continue
            overlaps.append(
                {
                    "left": left.name,
                    "right": right.name,
                    "iou": round(iou, 4),
                }
            )
    return overlaps


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, str):
            return enum_value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
