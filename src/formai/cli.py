from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

from formai.agents.data_extractor import DataExtractorAgent
from formai.benchmarks.colab import prepare_colab_benchmark_bundle
from formai.benchmarks.runner import BenchmarkRunner
from formai.config import FormAIConfig
from formai.errors import IntegrationUnavailable
from formai.pipeline import (
    build_default_pipeline,
    build_document_perception_client,
    build_schema_resolver_client,
    build_vision_client,
)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    config = FormAIConfig.from_env(Path.cwd())

    if args.command == "benchmark":
        summary = run_benchmark_command(args, config)
        print(_to_json(summary))
        return

    if args.command == "prepare-colab-benchmark":
        summary = run_prepare_colab_benchmark_command(args, config)
        print(_to_json(summary))
        return

    pipeline = build_default_pipeline(config)

    if args.command == "analyze":
        result = _run_with_stdout_noise_redirected(lambda: pipeline.analyze(Path(args.template)))
        print(_to_json(result))
        return

    if args.command == "prepare-fillable":
        analysis, result = _run_with_stdout_noise_redirected(
            lambda: pipeline.prepare_fillable(Path(args.template), Path(args.output))
        )
        print(_to_json({"analysis": analysis, "generation": result}))
        return

    if args.command == "run":
        result = _run_with_stdout_noise_redirected(
            lambda: pipeline.run(
                template_pdf=Path(args.template),
                filled_pdf=Path(args.filled),
                fillable_output=Path(args.fillable_output),
                final_output=Path(args.final_output),
            )
        )
        print(_to_json(result))
        return

    parser.error("Unknown command")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FormAI intelligent PDF form pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze template PDF structure")
    analyze.add_argument("--template", required=True)

    prepare = subparsers.add_parser(
        "prepare-fillable", help="Convert template PDF into a fillable AcroForm"
    )
    prepare.add_argument("--template", required=True)
    prepare.add_argument("--output", required=True)

    run = subparsers.add_parser("run", help="Run end-to-end pipeline")
    run.add_argument("--template", required=True)
    run.add_argument("--filled", required=True)
    run.add_argument("--fillable-output", required=True)
    run.add_argument("--final-output", required=True)

    benchmark = subparsers.add_parser("benchmark", help="Run extraction benchmark")
    benchmark.add_argument(
        "--dataset",
        required=True,
        choices=[
            "funsd_plus",
            "fir",
            "template_e2e",
            "turkish_printed",
            "turkish_handwritten",
            "turkish_petitions",
            "validation_matrix",
        ],
    )
    benchmark.add_argument("--provider", choices=["auto", "openai", "glm_ocr", "ollama"], default="")
    benchmark.add_argument("--vision-provider", choices=["auto", "openai", "glm_ocr", "ollama"], default="")
    benchmark.add_argument("--ollama-model", default="")
    benchmark.add_argument("--intake-backend", default="")
    benchmark.add_argument("--layout-backend", default="")
    benchmark.add_argument("--perception-backend", default="")
    benchmark.add_argument("--resolver-backend", default="")
    benchmark.add_argument("--region-adjudicator-backend", default="")
    benchmark.add_argument("--verification-backend", default="")
    benchmark.add_argument("--runner-backend", choices=["legacy", "hamilton"], default="")
    benchmark.add_argument("--split", default="test")
    benchmark.add_argument("--max-samples", type=int, default=100)
    benchmark.add_argument(
        "--pack",
        choices=["custom", "smoke", "regression", "tuning", "release"],
        default="custom",
    )
    benchmark.add_argument("--out-dir", default="")

    colab = subparsers.add_parser(
        "prepare-colab-benchmark",
        help="Create a Colab-ready benchmark bundle for remote GPU execution",
    )
    colab.add_argument(
        "--dataset",
        required=True,
        choices=[
            "funsd_plus",
            "fir",
            "template_e2e",
            "turkish_printed",
            "turkish_handwritten",
            "turkish_petitions",
            "validation_matrix",
        ],
    )
    colab.add_argument("--provider", choices=["auto", "openai", "glm_ocr", "ollama"], default="")
    colab.add_argument("--vision-provider", choices=["auto", "openai", "glm_ocr", "ollama"], default="")
    colab.add_argument("--intake-backend", default="")
    colab.add_argument("--layout-backend", default="")
    colab.add_argument("--perception-backend", default="")
    colab.add_argument("--resolver-backend", default="")
    colab.add_argument("--region-adjudicator-backend", default="")
    colab.add_argument("--verification-backend", default="")
    colab.add_argument("--runner-backend", choices=["legacy", "hamilton"], default="")
    colab.add_argument("--split", default="test")
    colab.add_argument("--max-samples", type=int, default=3)
    colab.add_argument(
        "--pack",
        choices=["custom", "smoke", "regression", "tuning", "release"],
        default="smoke",
    )
    colab.add_argument("--out-dir", default="")

    return parser


def _run_with_stdout_noise_redirected(operation):
    captured_stdout = io.StringIO()
    with redirect_stdout(captured_stdout):
        result = operation()
    noise = captured_stdout.getvalue()
    if noise:
        print(noise, file=sys.stderr, end="")
    return result


def run_benchmark_command(args, config: FormAIConfig | None = None):
    config = config or FormAIConfig.from_env(Path.cwd())
    provider = args.vision_provider or args.provider or config.vision_provider
    config.vision_provider = provider
    if args.ollama_model:
        config.ollama_model = args.ollama_model
    if args.intake_backend:
        config.intake_backend = args.intake_backend
    if args.layout_backend:
        config.layout_backend = args.layout_backend
    if args.perception_backend:
        config.perception_backend = args.perception_backend
    if args.resolver_backend:
        config.resolver_backend = args.resolver_backend
    if args.region_adjudicator_backend:
        config.region_adjudicator_backend = args.region_adjudicator_backend
    if args.verification_backend:
        config.verification_backend = args.verification_backend
    if args.runner_backend:
        config.runner_backend = args.runner_backend
    if provider == "openai" and not config.openai_api_key:
        raise SystemExit(
            "OPENAI_API_KEY is required for benchmark runs when --provider openai is used."
        )

    try:
        runner = _build_benchmark_runner(config)
    except IntegrationUnavailable as exc:
        raise SystemExit(str(exc)) from exc
    output_dir = Path(args.out_dir) if args.out_dir else runner.default_output_dir(args.dataset)
    try:
        if args.dataset == "validation_matrix":
            report = runner.run_validation_matrix(
                output_dir=output_dir,
                split=args.split,
                max_samples=args.max_samples,
                pack=args.pack if args.pack != "custom" else "smoke",
            )
            return {
                "dataset": report.dataset,
                "profile": report.profile,
                "split": report.split,
                "pack": getattr(report, "pack", args.pack if args.pack != "custom" else "smoke"),
                "passed": report.passed,
                "dataset_summaries": report.dataset_summaries,
                "gates": report.gates,
                "manual_review_queue_count": len(report.manual_review_queue),
                "output_dir": report.output_dir,
                "artifacts": {
                    "validation_summary": output_dir / "validation_summary.json",
                    "manual_review_queue": output_dir / "manual_review_queue.json",
                    "worst_cases": output_dir / "worst_cases.md",
                    "dataset_summaries": output_dir / "dataset_summaries",
                },
            }
        if args.dataset == "template_e2e":
            report = runner.synthetic_validator.run(
                output_dir=output_dir,
                split=args.split,
                max_cases=args.max_samples,
                pack=args.pack,
            )
            return {
                "dataset": report.dataset,
                "profile": report.profile,
                "split": report.split,
                "pack": report.pack,
                "sample_count": report.sample_count,
                "aggregate_metrics": {
                    "field_match_rate": report.aggregate_metrics.field_match_rate,
                    "case_success_rate": report.aggregate_metrics.case_success_rate,
                    "confidence_average": report.aggregate_metrics.confidence_average,
                },
                "issue_counts": report.issue_counts,
                "review_reason_counts": report.review_reason_counts,
                "output_dir": report.output_dir,
                "artifacts": {
                    "summary": output_dir / "summary.json",
                    "report": output_dir / "report.json",
                    "cases": output_dir / "cases.jsonl",
                    "worst_cases": output_dir / "worst_cases.md",
                    "showcase": output_dir / "showcase",
                },
            }
        report = runner.run(
            dataset_name=args.dataset,
            split=args.split,
            max_samples=args.max_samples,
            output_dir=output_dir,
            profile="release",
            pack=args.pack,
        )
    except (IntegrationUnavailable, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    return {
        "dataset": report.dataset,
        "profile": report.profile,
        "split": report.split,
        "pack": getattr(report, "pack", args.pack),
        "sample_count": report.sample_count,
        "aggregate_metrics": report.aggregate_metrics,
        "issue_counts": report.issue_counts,
        "output_dir": report.output_dir,
        "artifacts": {
            "summary": output_dir / "summary.json",
            "samples": output_dir / "samples.jsonl",
            "worst_cases": output_dir / "worst_cases.md",
            "showcase": output_dir / "showcase",
        },
    }


def run_prepare_colab_benchmark_command(args, config: FormAIConfig | None = None):
    config = config or FormAIConfig.from_env(Path.cwd())
    output_dir = Path(args.out_dir) if args.out_dir else _default_colab_bundle_dir(config, args.dataset)
    provider = args.vision_provider or args.provider or "glm_ocr"
    intake_backend = args.intake_backend or "glm_ocr"
    layout_backend = args.layout_backend or "surya"
    perception_backend = args.perception_backend or "chandra"
    resolver_backend = args.resolver_backend or "glm_ocr"
    region_adjudicator_backend = args.region_adjudicator_backend or "glm_ocr"
    verification_backend = args.verification_backend or "glm_ocr"
    runner_backend = args.runner_backend or "hamilton"

    bundle = prepare_colab_benchmark_bundle(
        config=config,
        dataset=args.dataset,
        split=args.split,
        max_samples=args.max_samples,
        pack=args.pack,
        output_dir=output_dir,
        provider=provider,
        intake_backend=intake_backend,
        layout_backend=layout_backend,
        perception_backend=perception_backend,
        resolver_backend=resolver_backend,
        region_adjudicator_backend=region_adjudicator_backend,
        verification_backend=verification_backend,
        runner_backend=runner_backend,
    )
    return {
        "dataset": args.dataset,
        "split": args.split,
        "pack": args.pack,
        "sample_count": args.max_samples,
        "bundle_dir": bundle.bundle_dir,
        "artifacts": {
            "workspace_archive": bundle.workspace_archive,
            "benchmark_spec": bundle.benchmark_spec,
            "bootstrap_script": bundle.bootstrap_script,
            "runner_script": bundle.runner_script,
            "readme": bundle.readme_path,
        },
        "remote_output_dir": bundle.remote_output_dir,
        "benchmark_command": bundle.benchmark_command,
        "recommended_stack": {
            "provider": provider,
            "intake_backend": intake_backend,
            "layout_backend": layout_backend,
            "perception_backend": perception_backend,
            "resolver_backend": resolver_backend,
            "region_adjudicator_backend": region_adjudicator_backend,
            "verification_backend": verification_backend,
            "runner_backend": runner_backend,
        },
    }


def _build_benchmark_runner(config: FormAIConfig) -> BenchmarkRunner:
    llm_client = build_vision_client(config)
    perception_client = build_document_perception_client(config)
    resolver_client = build_schema_resolver_client(config)
    extractor = DataExtractorAgent(
        config,
        llm_client,
        ocr_reader=None,
        perception_client=perception_client,
        resolver_client=resolver_client,
    )
    return BenchmarkRunner(
        extractor,
        pipeline_factory=lambda: build_default_pipeline(config),
    )


def _default_colab_bundle_dir(config: FormAIConfig, dataset: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return config.working_dir / "tmp" / "colab_benchmarks" / dataset / timestamp


def _to_json(value) -> str:
    return json.dumps(_serialize(value), indent=2, ensure_ascii=False)


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


if __name__ == "__main__":
    main()
