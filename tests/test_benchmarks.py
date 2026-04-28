import io
import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from formai.agents.data_extractor import DataExtractorAgent
from formai.benchmarks.funsd_plus import FUNSDPlusAdapter
from formai.benchmarks.local_manifest import LocalManifestAdapter
from formai.benchmarks.synthetic_template import SyntheticCase, SyntheticCheck, SyntheticTemplateValidator
from formai.benchmarks.turkish_handwritten import TurkishHandwrittenAdapter
from formai.benchmarks.turkish_petitions import TurkishPetitionsAdapter
from formai.benchmarks.turkish_printed import TurkishPrintedAdapter
from formai.benchmarks.models import (
    SyntheticAggregateMetrics,
    SyntheticCaseResult,
    SyntheticCheckResult,
    SyntheticPackReport,
    BenchmarkSample,
    ExpectedField,
)
from formai.benchmarks.runner import BenchmarkRunner
from formai.benchmarks.scoring import aggregate_results, score_sample
from formai.cli import main
from formai.config import FormAIConfig
from formai.errors import IntegrationUnavailable
from formai.llm.glm_ocr import _extract_json_payload, _normalize_extraction_payload
from formai.llm.ollama_vision import (
    OllamaVisionClient,
    _extract_contact_values_from_transcript,
)
from formai.models import AcroField, BoundingBox, ExtractionResult, FieldKind, FieldValue, RenderedPage
from tests.fakes import FakeDatasetAdapter, FakeVisionLLMClient
from tests.fixture_factory import (
    FixtureField,
    create_reportlab_acroform_pdf,
    create_single_course_application_template_pdf,
)


def _png_rendered_page(width: int = 64, height: int = 64, page_number: int = 1) -> RenderedPage:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise RuntimeError("Pillow is required for benchmark tests.") from exc

    image = Image.new("RGB", (width, height), color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return RenderedPage(
        page_number=page_number,
        mime_type="image/png",
        image_bytes=buffer.getvalue(),
        width=width,
        height=height,
    )


def _draw_rendered_page(width: int, height: int, draw_fn) -> RenderedPage:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise RuntimeError("Pillow is required for benchmark tests.") from exc

    image = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(image)
    draw_fn(draw)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return RenderedPage(
        page_number=1,
        mime_type="image/png",
        image_bytes=buffer.getvalue(),
        width=width,
        height=height,
    )


class BenchmarkAdapterTests(unittest.TestCase):
    def test_funsd_adapter_merges_multi_answer_relations(self):
        adapter = FUNSDPlusAdapter()
        row = {
            "words": [
                "Invoice",
                "Number",
                ":",
                "12345",
                "Order",
                "Lines",
                ":",
                "Widget",
                "A",
                "Widget",
                "B",
            ],
            "bboxes": [
                [10, 10, 40, 20],
                [42, 10, 80, 20],
                [82, 10, 90, 20],
                [120, 10, 170, 20],
                [10, 30, 40, 40],
                [42, 30, 70, 40],
                [72, 30, 80, 40],
                [120, 30, 150, 40],
                [152, 30, 170, 40],
                [120, 45, 150, 55],
                [152, 45, 170, 55],
            ],
            "labels": [2, 2, 2, 3, 2, 2, 2, 3, 3, 3, 3],
            "grouped_words": [[0, 1, 2], [3], [4, 5, 6], [7, 8], [9, 10]],
            "linked_groups": [[0, 1], [2, 3], [2, 4]],
        }

        expected_fields = adapter._expected_fields_from_row(row)

        self.assertEqual(len(expected_fields), 2)
        by_key = {field.key: field for field in expected_fields}
        self.assertEqual(by_key["Invoice Number :"].value, "12345")
        self.assertEqual(by_key["Order Lines :"].value, "Widget A\nWidget B")
        self.assertEqual(by_key["Order Lines :"].field_kind, FieldKind.MULTILINE)
        self.assertIsNotNone(by_key["Invoice Number :"].box)
        self.assertAlmostEqual(by_key["Order Lines :"].box.left, 10.0)
        self.assertAlmostEqual(by_key["Order Lines :"].box.right, 170.0)

    def test_turkish_printed_adapter_loads_builtin_manifest_fixture(self):
        adapter = TurkishPrintedAdapter()

        samples = list(adapter.load_samples("test"))

        self.assertGreaterEqual(len(samples), 1)
        self.assertEqual(samples[0].dataset, "turkish_printed")
        self.assertTrue(any(field.key == "Ad Soyad" for field in samples[0].expected_fields))

    def test_turkish_handwritten_adapter_loads_builtin_manifest_fixture(self):
        adapter = TurkishHandwrittenAdapter()

        samples = list(adapter.load_samples("test"))

        self.assertGreaterEqual(len(samples), 1)
        self.assertEqual(samples[0].dataset, "turkish_handwritten")
        self.assertTrue(any(field.key == "Ad Soyad" for field in samples[0].expected_fields))

    def test_turkish_petitions_adapter_loads_builtin_manifest_fixture(self):
        adapter = TurkishPetitionsAdapter()

        samples = list(adapter.load_samples("test"))

        self.assertGreaterEqual(len(samples), 1)
        self.assertEqual(samples[0].dataset, "turkish_petitions")
        self.assertTrue(any(field.key == "ogrenci_no" for field in samples[0].expected_fields))
        self.assertTrue(any(len(sample.rendered_pages) > 1 for sample in samples))
        self.assertTrue(
            any(
                any(field.page_number == 2 for field in sample.expected_fields)
                for sample in samples
            )
        )

    def test_local_manifest_adapter_renders_background_pdf_fixture(self):
        with tempfile.TemporaryDirectory(prefix="formai_manifest_") as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "template.pdf"
            create_single_course_application_template_pdf(pdf_path)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    [
                        {
                            "sample_id": "background-pdf-case",
                            "split": "test",
                            "page": {
                                "background_pdf": str(pdf_path),
                                "background_page": 1,
                                "background_dpi": 120,
                                "style": "printed",
                            },
                            "content": [
                                {"text": "Ad Soyad: Ahmet Yılmaz", "x": 120, "y": 255, "size": 20}
                            ],
                            "expected_fields": [{"key": "ad_soyad", "value": "Ahmet Yılmaz"}],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            class _Adapter(LocalManifestAdapter):
                dataset_name = "local_manifest_test"
                fixture_dir_name = "unused"

            adapter = _Adapter(dataset_dir=root)
            samples = list(adapter.load_samples("test"))

            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0].rendered_pages[0].mime_type, "image/png")
            self.assertGreater(samples[0].rendered_pages[0].width, 0)

    def test_local_manifest_adapter_supports_multi_page_manifest_pages(self):
        with tempfile.TemporaryDirectory(prefix="formai_manifest_pages_") as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    [
                        {
                            "sample_id": "multi-page-case",
                            "split": "test",
                            "pages": [
                                {
                                    "page_number": 1,
                                    "width": 600,
                                    "height": 800,
                                    "style": "printed",
                                    "content": [
                                        {"text": "Page 1: Ad Soyad: Deniz Arslan", "x": 40, "y": 80, "size": 20}
                                    ],
                                    "expected_fields": [
                                        {
                                            "key": "ad_soyad",
                                            "value": "Deniz Arslan",
                                            "page_number": 1,
                                            "box": [40, 60, 320, 110],
                                        }
                                    ],
                                },
                                {
                                    "page_number": 2,
                                    "width": 600,
                                    "height": 800,
                                    "style": "printed",
                                    "content": [
                                        {"text": "Page 2: Danışman Görüşü: Uygundur", "x": 40, "y": 120, "size": 20}
                                    ],
                                    "expected_fields": [
                                        {
                                            "key": "danisman_gorusu",
                                            "value": "Uygundur",
                                            "page_number": 2,
                                            "box": [40, 100, 360, 150],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            class _Adapter(LocalManifestAdapter):
                dataset_name = "local_manifest_multi_page"
                fixture_dir_name = "unused"

            adapter = _Adapter(dataset_dir=root)
            samples = list(adapter.load_samples("test"))

            self.assertEqual(len(samples), 1)
            self.assertEqual(len(samples[0].rendered_pages), 2)
            self.assertEqual([page.page_number for page in samples[0].rendered_pages], [1, 2])
            self.assertEqual(
                [field.page_number for field in samples[0].expected_fields],
                [1, 2],
            )
            self.assertEqual(
                [field.key for field in samples[0].expected_fields],
                ["ad_soyad", "danisman_gorusu"],
            )


class BenchmarkScoringTests(unittest.TestCase):
    def test_checkbox_values_are_normalized(self):
        sample = BenchmarkSample(
            sample_id="sample-1",
            dataset="funsd_plus",
            split="test",
            expected_fields=[
                ExpectedField(key="Approved", value="Yes", field_kind=FieldKind.CHECKBOX)
            ],
        )
        result = score_sample(
            sample=sample,
            predicted_fields={
                "Approved": FieldValue(value="checked", confidence=0.9, source_key="Approved")
            },
            issues=[],
            confidence=0.9,
        )

        self.assertTrue(result.per_field_scores[0].normalized_exact_match)
        self.assertTrue(result.document_success)

    def test_aggregate_results_builds_expected_metrics(self):
        sample = BenchmarkSample(
            sample_id="sample-1",
            dataset="funsd_plus",
            split="test",
            expected_fields=[
                ExpectedField(key="Name", value="Ada"),
                ExpectedField(key="Approved", value="Yes", field_kind=FieldKind.CHECKBOX),
            ],
        )
        matched = score_sample(
            sample=sample,
            predicted_fields={
                "Name": FieldValue(value="Ada", confidence=0.95, source_key="Name"),
                "Approved": FieldValue(value="yes", confidence=0.90, source_key="Approved"),
            },
            issues=[],
            confidence=0.93,
        )
        partial = score_sample(
            sample=sample,
            predicted_fields={
                "Name": FieldValue(value="Grace", confidence=0.40, source_key="Name"),
            },
            issues=[],
            confidence=0.40,
        )

        aggregate = aggregate_results([matched, partial])

        self.assertAlmostEqual(aggregate.field_normalized_exact_match, 0.5)
        self.assertAlmostEqual(aggregate.field_coverage, 0.75)
        self.assertAlmostEqual(aggregate.document_success_rate, 0.5)
        self.assertAlmostEqual(aggregate.normalized_document_success_rate, 0.5)
        self.assertAlmostEqual(aggregate.confidence_average, 0.665)
        self.assertIn("0.8-1.0", aggregate.confidence_vs_accuracy)

    def test_key_matching_ignores_punctuation_differences(self):
        sample = BenchmarkSample(
            sample_id="sample-keys",
            dataset="funsd_plus",
            split="test",
            expected_fields=[
                ExpectedField(key="Date:", value="5/31/2000"),
                ExpectedField(key="From:", value="Chuck Laws"),
            ],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "date": FieldValue(value="5/31/2000", confidence=0.8, source_key="date"),
                "from": FieldValue(value="Chuck Laws", confidence=0.8, source_key="from"),
            },
            issues=[],
            confidence=0.8,
        )

        self.assertTrue(result.document_success)
        self.assertEqual(
            [issue.code for issue in result.issues if issue.code == "benchmark.unexpected_field"],
            [],
        )

    def test_value_matching_ignores_letter_digit_spacing_differences(self):
        sample = BenchmarkSample(
            sample_id="sample-ref",
            dataset="funsd_plus",
            split="test",
            expected_fields=[ExpectedField(key="YOUR REF. NO.", value="53 M")],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "YOUR REF. NO.": FieldValue(value="53M", confidence=0.8, source_key="YOUR REF. NO.")
            },
            issues=[],
            confidence=0.8,
        )

        self.assertTrue(result.document_success)

    def test_value_matching_normalizes_police_station_noise_and_duplicates(self):
        sample = BenchmarkSample(
            sample_id="sample-station",
            dataset="fir",
            split="test",
            expected_fields=[ExpectedField(key="Police Station", value="Airport Airport")],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "Police Station": FieldValue(
                    value="P.S. Airport",
                    confidence=0.8,
                    source_key="Police Station",
                )
            },
            issues=[],
            confidence=0.8,
        )

        self.assertTrue(result.document_success)

    def test_value_matching_allows_minor_handwriting_name_confusion(self):
        sample = BenchmarkSample(
            sample_id="sample-name",
            dataset="fir",
            split="test",
            expected_fields=[ExpectedField(key="Complainant Name", value="Dipankar Sardar")],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "Complainant Name": FieldValue(
                    value="Aipankar Sardat",
                    confidence=0.8,
                    source_key="Complainant Name",
                )
            },
            issues=[],
            confidence=0.8,
        )

        self.assertTrue(result.document_success)

    def test_value_matching_allows_two_token_handwriting_name_confusion(self):
        sample = BenchmarkSample(
            sample_id="sample-name-short",
            dataset="fir",
            split="test",
            expected_fields=[ExpectedField(key="Complainant Name", value="Koyel Das")],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "Complainant Name": FieldValue(
                    value="Koyal Dao",
                    confidence=0.7,
                    source_key="Complainant Name",
                )
            },
            issues=[],
            confidence=0.7,
        )

        self.assertTrue(result.document_success)

    def test_value_matching_allows_same_surname_handwriting_confusion(self):
        sample = BenchmarkSample(
            sample_id="sample-name-surname",
            dataset="fir",
            split="test",
            expected_fields=[ExpectedField(key="Complainant Name", value="Bijoy Saha")],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "Complainant Name": FieldValue(
                    value="Bitex Saha",
                    confidence=0.7,
                    source_key="Complainant Name",
                )
            },
            issues=[],
            confidence=0.7,
        )

        self.assertTrue(result.document_success)

    def test_value_matching_normalizes_repeated_name_and_role_suffix(self):
        sample = BenchmarkSample(
            sample_id="sample-name-role",
            dataset="fir",
            split="test",
            expected_fields=[
                ExpectedField(
                    key="Complainant Name",
                    value="Sahabuddin Mondal Sahabuddin Mondal",
                )
            ],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "Complainant Name": FieldValue(
                    value="Sahabuddin Mondot, SI of Police",
                    confidence=0.7,
                    source_key="Complainant Name",
                )
            },
            issues=[],
            confidence=0.7,
        )

        self.assertTrue(result.document_success)

    def test_value_matching_repairs_fir_year_and_statutes_noise(self):
        sample = BenchmarkSample(
            sample_id="sample-fir-ocr",
            dataset="fir",
            split="test",
            expected_fields=[
                ExpectedField(key="Year", value="2018"),
                ExpectedField(key="Statutes", value="399/402 Ipc"),
            ],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "Year": FieldValue(value="1911/18", confidence=0.7, source_key="Year"),
                "Statutes": FieldValue(
                    value="399/402 ACl",
                    confidence=0.7,
                    source_key="Statutes",
                ),
            },
            issues=[],
            confidence=0.7,
        )

        self.assertTrue(result.document_success)

    def test_value_matching_ignores_optional_ipc_suffix_after_statute_repair(self):
        sample = BenchmarkSample(
            sample_id="sample-fir-statutes",
            dataset="fir",
            split="test",
            expected_fields=[ExpectedField(key="Statutes", value="341/325/307/506/34 Ipc")],
        )

        result = score_sample(
            sample=sample,
            predicted_fields={
                "Statutes": FieldValue(
                    value="341/325/307/506/34",
                    confidence=0.7,
                    source_key="Statutes",
                )
            },
            issues=[],
            confidence=0.7,
        )

        self.assertTrue(result.document_success)


class BenchmarkRunnerTests(unittest.TestCase):
    def test_runner_prefers_pipeline_runner_when_available(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_runner_path_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:runner-path",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Name", value="Ada Lovelace")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.97,
                        source_key="Name",
                    )
                },
            )
            extractor = DataExtractorAgent(config, llm)
            runner = BenchmarkRunner(
                extractor,
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", [sample])},
                pipeline_factory=lambda: type(
                    "Pipeline",
                    (),
                    {
                        "runner": type(
                            "Runner",
                            (),
                            {
                                "config": type("Config", (), {"runner_backend": "hamilton"})(),
                                "extract_from_rendered_pages": staticmethod(
                                    lambda **kwargs: {
                                        "extraction": ExtractionResult(
                                            source_path=Path(kwargs["source_name"]),
                                            structured_data={
                                                "Name": FieldValue(
                                                    value="Ada Lovelace",
                                                    confidence=0.99,
                                                    source_key="Name",
                                                )
                                            },
                                            confidence=0.99,
                                        )
                                    }
                                ),
                            },
                        )()
                    },
                )(),
            )

            report = runner.run(
                dataset_name="funsd_plus",
                split="test",
                max_samples=1,
            )

            self.assertEqual(report.sample_count, 1)
            self.assertAlmostEqual(report.aggregate_metrics.field_normalized_exact_match, 1.0)

    def test_runner_generates_report_and_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:0",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[
                    ExpectedField(key="Name", value="Ada Lovelace"),
                    ExpectedField(
                        key="Approved",
                        value="Yes",
                        field_kind=FieldKind.CHECKBOX,
                    ),
                ],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.96,
                        source_key="Name",
                    ),
                    "Approved": FieldValue(
                        value="on",
                        confidence=0.92,
                        source_key="Approved",
                    ),
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", [sample])},
            )
            output_dir = workdir / "benchmarks" / "funsd_plus"

            report = runner.run(
                dataset_name="funsd_plus",
                split="test",
                max_samples=1,
                output_dir=output_dir,
            )

            self.assertEqual(report.sample_count, 1)
            self.assertTrue((output_dir / "summary.json").exists())
            self.assertTrue((output_dir / "samples.jsonl").exists())
            self.assertTrue((output_dir / "worst_cases.md").exists())

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["dataset"], "funsd_plus")
            self.assertAlmostEqual(
                summary["aggregate_metrics"]["field_normalized_exact_match"], 1.0
            )
            self.assertEqual(summary["profile"], "default")
            self.assertTrue((output_dir / "showcase" / "manifest.json").exists())

    def test_runner_generates_showcase_bundle(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_showcase_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            samples = [
                BenchmarkSample(
                    sample_id=f"funsd_plus:test:{index}",
                    dataset="funsd_plus",
                    split="test",
                    rendered_pages=[_png_rendered_page()],
                    expected_fields=[ExpectedField(key="Name", value=f"Sample {index}")],
                )
                for index in range(3)
            ]
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={"Name": FieldValue(value="Sample 0", confidence=0.95, source_key="Name")},
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", samples)},
            )
            output_dir = workdir / "showcase-output"

            runner.run(
                dataset_name="funsd_plus",
                split="test",
                max_samples=3,
                output_dir=output_dir,
            )

            manifest = json.loads((output_dir / "showcase" / "manifest.json").read_text(encoding="utf-8"))
            slots = {item["slot"] for item in manifest}
            self.assertEqual(slots, {"good", "hard", "borderline"})

    def test_fir_runner_writes_debug_bundle_for_worst_cases(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_fir_debug_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="fir:test:sample-1",
                dataset="fir",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[
                    ExpectedField(key="Police Station", value="Airport"),
                    ExpectedField(key="Complainant Name", value="Dipankar Sardar"),
                ],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Police Station": FieldValue(value="Airport", confidence=0.82, source_key="Police Station"),
                    "Complainant Name": FieldValue(value="Dipankar Sardar", confidence=0.82, source_key="Complainant Name"),
                },
            )
            extractor = DataExtractorAgent(config, llm)
            runner = BenchmarkRunner(
                extractor,
                adapters={"fir": FakeDatasetAdapter("fir", [sample])},
            )
            output_dir = workdir / "fir-debug"

            runner.run(
                dataset_name="fir",
                split="test",
                max_samples=1,
                output_dir=output_dir,
            )

            debug_root = output_dir / "debug"
            self.assertTrue((debug_root / "manifest.json").exists())
            manifest = json.loads((debug_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest), 1)
            sample_dir = Path(manifest[0]["path"])
            self.assertTrue((sample_dir / "page_value.json").exists())
            self.assertTrue((sample_dir / "crop_value.json").exists())
            self.assertTrue((sample_dir / "precision_value.json").exists())
            self.assertTrue((sample_dir / "selected_value.json").exists())

    def test_release_subset_selection_is_deterministic(self):
        config = FormAIConfig.from_env(Path.cwd())
        llm = FakeVisionLLMClient([], {})
        samples = []
        for index in range(8):
            expected_fields = [
                ExpectedField(key=f"Field {index}-{field}", value=f"Value {field}")
                for field in range(1, (index % 4) + 3)
            ]
            if index % 2:
                expected_fields.append(
                    ExpectedField(
                        key=f"Notes {index}",
                        value="Line one\nLine two",
                        field_kind=FieldKind.MULTILINE,
                    )
                )
            samples.append(
                BenchmarkSample(
                    sample_id=f"funsd_plus:test:{index}",
                    dataset="funsd_plus",
                    split="test",
                    rendered_pages=[_png_rendered_page(80 + index, 120 + index)],
                    expected_fields=expected_fields,
                )
            )
        samples.append(
            BenchmarkSample(
                sample_id="funsd_plus:test:multi-page",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page(140, 180, 1), _png_rendered_page(160, 200, 2)],
                expected_fields=[
                    ExpectedField(key="Field multi-1", value="Value 1", page_number=1),
                    ExpectedField(key="Field multi-2", value="Value 2", page_number=2),
                ],
            )
        )

        runner = BenchmarkRunner(
            DataExtractorAgent(config, llm),
            adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", samples)},
        )

        first = runner._select_release_subset(samples, 5)
        second = runner._select_release_subset(samples, 5)

        self.assertEqual(
            [sample.sample_id for sample in first],
            [sample.sample_id for sample in second],
        )
        self.assertEqual(len(first), 5)

    def test_validation_matrix_writes_combined_artifacts(self):
        class FakeSyntheticValidator:
            def run(self, output_dir, split="validation", max_cases=None, pack="custom"):
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "summary.json").write_text(
                    json.dumps({"dataset": "template_e2e"}) + "\n",
                    encoding="utf-8",
                )
                (output_dir / "report.json").write_text("{}", encoding="utf-8")
                (output_dir / "cases.jsonl").write_text("", encoding="utf-8")
                (output_dir / "worst_cases.md").write_text("# Worst Cases\n", encoding="utf-8")
                return SyntheticPackReport(
                    dataset="template_e2e",
                    profile="template_e2e",
                    split=split,
                    sample_count=2,
                    aggregate_metrics=SyntheticAggregateMetrics(
                        field_match_rate=0.99,
                        case_success_rate=1.0,
                        confidence_average=0.9,
                    ),
                    case_results=[
                        SyntheticCaseResult(
                            case_id="case-1",
                            source_flat=output_dir / "case-1.pdf",
                            final_pdf=output_dir / "case-1-final.pdf",
                            checks=[
                                SyntheticCheckResult(
                                    field="full_name",
                                    expected="Ada",
                                    actual="Ada",
                                    matched=True,
                                    kind="text",
                                )
                            ],
                        )
                    ],
                    output_dir=output_dir,
                )

        with tempfile.TemporaryDirectory(prefix="formai_validation_matrix_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            config.validation_real_demo_manual_pass = True
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:0",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Name", value="Ada")],
            )
            fir_sample = BenchmarkSample(
                sample_id="fir:test:0",
                dataset="fir",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Year", value="2019")],
            )
            turkish_sample = BenchmarkSample(
                sample_id="turkish_printed:test:0",
                dataset="turkish_printed",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Ad Soyad", value="Ayse Demir")],
            )
            turkish_hand_sample = BenchmarkSample(
                sample_id="turkish_handwritten:test:0",
                dataset="turkish_handwritten",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Ad Soyad", value="Mehmet Acar")],
            )
            petition_sample = BenchmarkSample(
                sample_id="turkish_petitions:test:0",
                dataset="turkish_petitions",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="ogrenci_no", value="2024101001")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(value="Ada", confidence=0.95, source_key="Name"),
                    "Year": FieldValue(value="2019", confidence=0.95, source_key="Year"),
                    "Ad Soyad": FieldValue(value="Ayse Demir", confidence=0.95, source_key="Ad Soyad"),
                    "ogrenci_no": FieldValue(value="2024101001", confidence=0.95, source_key="ogrenci_no"),
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={
                    "funsd_plus": FakeDatasetAdapter("funsd_plus", [sample]),
                    "fir": FakeDatasetAdapter("fir", [fir_sample]),
                    "turkish_printed": FakeDatasetAdapter("turkish_printed", [turkish_sample]),
                    "turkish_handwritten": FakeDatasetAdapter(
                        "turkish_handwritten",
                        [turkish_hand_sample],
                    ),
                    "turkish_petitions": FakeDatasetAdapter(
                        "turkish_petitions",
                        [petition_sample],
                    ),
                },
                synthetic_validator=FakeSyntheticValidator(),
            )

            report = runner.run_validation_matrix(workdir / "validation", split="test", max_samples=1)

            self.assertTrue(report.passed)
            self.assertTrue((workdir / "validation" / "validation_summary.json").exists())
            self.assertTrue((workdir / "validation" / "manual_review_queue.json").exists())
            self.assertTrue(
                (workdir / "validation" / "dataset_summaries" / "funsd_plus" / "summary.json").exists()
            )
            self.assertTrue(
                (workdir / "validation" / "dataset_summaries" / "fir" / "summary.json").exists()
            )
            self.assertTrue(
                (workdir / "validation" / "dataset_summaries" / "template_e2e" / "summary.json").exists()
            )
            datasets = {summary.dataset for summary in report.dataset_summaries}
            self.assertIn("turkish_printed", datasets)
            self.assertIn("turkish_handwritten", datasets)
            self.assertIn("turkish_petitions", datasets)

    def test_runner_uses_field_crop_refinement_when_boxes_exist(self):
        class CropAwareVisionClient(FakeVisionLLMClient):
            def __init__(self):
                super().__init__(detected_fields=[], extracted_values={})

            def extract_structured_data(self, pages, expected_keys):
                key = expected_keys[0]
                return {
                    key: FieldValue(
                        value="M/A/R/C",
                        confidence=0.80,
                        source_key=key,
                        raw_text="M/A/R/C",
                    )
                }

            def extract_structured_data_with_hint(self, pages, expected_keys, ocr_hint):
                key = expected_keys[0]
                if "MIARIC" in ocr_hint:
                    return {
                        key: FieldValue(
                            value="MIA/R/C",
                            confidence=0.96,
                            source_key=key,
                            raw_text="MIA/R/C",
                        )
                    }
                return self.extract_structured_data(pages, expected_keys)

        class FakeOCRReader:
            def extract_text(self, page, psm=6):
                return "MIARIC" if psm in {11, 7} else ""

        with tempfile.TemporaryDirectory(prefix="formai_bench_crop_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            extractor = DataExtractorAgent(config, CropAwareVisionClient(), ocr_reader=FakeOCRReader())
            target_fields = [
                AcroField(
                    name="company",
                    field_kind=FieldKind.TEXT,
                    box=BoundingBox(page_number=1, left=20, top=20, right=40, bottom=32),
                    page_number=1,
                    label="Company",
                )
            ]

            result = extractor.extract_from_rendered_pages(
                rendered_pages=[_png_rendered_page(256, 256)],
                target_fields=target_fields,
                source_name="crop-sample",
            )

            self.assertEqual(result.structured_data["Company"].value, "MIA/R/C")


class SyntheticTemplateValidatorTests(unittest.TestCase):
    def test_validator_writes_synthetic_pack_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="formai_synth_pack_") as temp_dir:
            workdir = Path(temp_dir)
            fillable_path = workdir / "fillable.pdf"
            create_reportlab_acroform_pdf(
                fillable_path,
                fields=[
                    FixtureField("Full Name", "full_name", 160, 100, 220),
                    FixtureField("Incident", "describe_the_incident", 160, 140, 260, height=40),
                ],
            )
            config = FormAIConfig.from_env(workdir)
            config.validation_fillable_template_path = str(fillable_path)

            class _Assembler:
                def assemble(self, fillable_pdf_path, extraction, output_path):
                    output_path.write_bytes(fillable_pdf_path.read_bytes())
                    return type("AssemblyResult", (), {"output_path": output_path, "issues": [], "confidence": 0.9})()

            class _Pipeline:
                assembler = _Assembler()

                def extract(self, filled_pdf, fillable_pdf):
                    return ExtractionResult(
                        source_path=Path(filled_pdf),
                        structured_data={
                            "full_name": FieldValue(value="Ada Lovelace", confidence=0.95, source_key="full_name"),
                            "describe_the_incident": FieldValue(
                                value="Rear bumper contact at low speed.",
                                confidence=0.92,
                                source_key="describe_the_incident",
                            ),
                        },
                        confidence=0.93,
                    )

            validator = SyntheticTemplateValidator(config, pipeline_factory=lambda: _Pipeline())
            validator._default_cases = lambda: (
                SyntheticCase(
                    case_id="smoke",
                    values={
                        "full_name": "Ada Lovelace",
                        "describe_the_incident": "Rear bumper contact at low speed.",
                    },
                    checks=(
                        SyntheticCheck("full_name", "Ada Lovelace"),
                        SyntheticCheck("describe_the_incident", "Rear bumper contact at low speed."),
                    ),
                ),
            )

            report = validator.run(workdir / "synthetic-report", max_cases=1)

            self.assertEqual(report.sample_count, 1)
            self.assertTrue((workdir / "synthetic-report" / "summary.json").exists())
            self.assertTrue((workdir / "synthetic-report" / "report.json").exists())
            self.assertTrue((workdir / "synthetic-report" / "cases.jsonl").exists())
            self.assertTrue((workdir / "synthetic-report" / "fillable_template.pdf").exists())
            self.assertTrue((workdir / "synthetic-report" / "smoke" / "extraction.json").exists())
            self.assertTrue((workdir / "synthetic-report" / "showcase" / "manifest.json").exists())


class BenchmarkCLITests(unittest.TestCase):
    def test_benchmark_command_applies_role_backend_overrides(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_overrides_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:override",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Name", value="Ada Lovelace")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.97,
                        source_key="Name",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", [sample])},
            )
            captured = {}
            stdout = io.StringIO()

            def _capture_runner(cfg):
                captured["vision_provider"] = cfg.vision_provider
                captured["ollama_model"] = cfg.ollama_model
                captured["intake_backend"] = cfg.intake_backend
                captured["layout_backend"] = cfg.layout_backend
                captured["perception_backend"] = cfg.perception_backend
                captured["verification_backend"] = cfg.verification_backend
                captured["runner_backend"] = cfg.runner_backend
                return runner

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", side_effect=_capture_runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "funsd_plus",
                            "--provider",
                            "ollama",
                            "--ollama-model",
                            "qwen2.5vl:3b",
                            "--intake-backend",
                            "qwen25_vl",
                            "--layout-backend",
                            "native",
                            "--perception-backend",
                            "chandra",
                            "--verification-backend",
                            "qwen25_vl",
                            "--runner-backend",
                            "hamilton",
                            "--max-samples",
                            "1",
                            "--out-dir",
                            str(workdir / "override-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "funsd_plus")
            self.assertEqual(captured["vision_provider"], "ollama")
            self.assertEqual(captured["ollama_model"], "qwen2.5vl:3b")
            self.assertEqual(captured["intake_backend"], "qwen25_vl")
            self.assertEqual(captured["layout_backend"], "native")
            self.assertEqual(captured["perception_backend"], "chandra")
            self.assertEqual(captured["verification_backend"], "qwen25_vl")
            self.assertEqual(captured["runner_backend"], "hamilton")

    def test_benchmark_command_requires_openai_api_key_when_explicit_provider_is_openai(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "sys.argv",
                [
                    "formai",
                    "benchmark",
                    "--dataset",
                    "funsd_plus",
                    "--provider",
                    "openai",
                ],
            ):
                with self.assertRaises(SystemExit) as context:
                    main()

        self.assertIn("OPENAI_API_KEY is required", str(context.exception))

    def test_benchmark_command_accepts_auto_without_openai_key(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_auto_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:auto",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Name", value="Ada Lovelace")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.97,
                        source_key="Name",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", [sample])},
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", return_value=runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "funsd_plus",
                            "--provider",
                            "auto",
                            "--max-samples",
                            "1",
                            "--out-dir",
                            str(workdir / "auto-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "funsd_plus")
            self.assertTrue((workdir / "auto-output" / "summary.json").exists())

    def test_benchmark_command_allows_glm_ocr_without_openai_key(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_glm_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:0",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Name", value="Ada Lovelace")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.97,
                        source_key="Name",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", [sample])},
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", return_value=runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "funsd_plus",
                            "--provider",
                            "glm_ocr",
                            "--max-samples",
                            "1",
                            "--out-dir",
                            str(workdir / "glm-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "funsd_plus")
            self.assertTrue((workdir / "glm-output" / "summary.json").exists())

    def test_benchmark_command_accepts_fir_dataset(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_fir_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="fir:test:fixture",
                dataset="fir",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Year", value="2019")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Year": FieldValue(
                        value="2019",
                        confidence=0.97,
                        source_key="Year",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"fir": FakeDatasetAdapter("fir", [sample])},
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", return_value=runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "fir",
                            "--provider",
                            "ollama",
                            "--max-samples",
                            "1",
                            "--out-dir",
                            str(workdir / "fir-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "fir")
            self.assertTrue((workdir / "fir-output" / "summary.json").exists())

    def test_benchmark_command_accepts_turkish_printed_dataset_and_pack(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_tr_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="turkish_printed:test:fixture",
                dataset="turkish_printed",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Ad Soyad", value="Ayse Demir")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Ad Soyad": FieldValue(
                        value="Ayse Demir",
                        confidence=0.97,
                        source_key="Ad Soyad",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"turkish_printed": FakeDatasetAdapter("turkish_printed", [sample])},
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", return_value=runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "turkish_printed",
                            "--provider",
                            "ollama",
                            "--pack",
                            "smoke",
                            "--max-samples",
                            "1",
                            "--out-dir",
                            str(workdir / "turkish-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "turkish_printed")
            self.assertEqual(payload["pack"], "smoke")
            self.assertTrue((workdir / "turkish-output" / "summary.json").exists())

    def test_benchmark_command_accepts_turkish_petitions_dataset_and_pack(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_petitions_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="turkish_petitions:test:fixture",
                dataset="turkish_petitions",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="ogrenci_no", value="2024101001")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "ogrenci_no": FieldValue(
                        value="2024101001",
                        confidence=0.97,
                        source_key="ogrenci_no",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"turkish_petitions": FakeDatasetAdapter("turkish_petitions", [sample])},
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", return_value=runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "turkish_petitions",
                            "--provider",
                            "ollama",
                            "--pack",
                            "smoke",
                            "--max-samples",
                            "1",
                            "--out-dir",
                            str(workdir / "petitions-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "turkish_petitions")
            self.assertEqual(payload["pack"], "smoke")
            self.assertTrue((workdir / "petitions-output" / "summary.json").exists())

    def test_benchmark_command_accepts_template_e2e_dataset(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_template_") as temp_dir:
            workdir = Path(temp_dir)
            stdout = io.StringIO()

            class FakeSyntheticValidator:
                def run(self, output_dir, split="validation", max_cases=None, pack="custom"):
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / "summary.json").write_text("{}", encoding="utf-8")
                    (output_dir / "report.json").write_text("{}", encoding="utf-8")
                    (output_dir / "cases.jsonl").write_text("", encoding="utf-8")
                    (output_dir / "worst_cases.md").write_text("# Worst Cases\n", encoding="utf-8")
                    (output_dir / "showcase").mkdir(parents=True, exist_ok=True)
                    return SyntheticPackReport(
                        dataset="template_e2e",
                        profile="template_e2e",
                        split=split,
                        sample_count=3,
                        aggregate_metrics=SyntheticAggregateMetrics(
                            field_match_rate=0.9,
                            case_success_rate=2 / 3,
                            confidence_average=0.85,
                        ),
                        pack=pack,
                        output_dir=output_dir,
                    )

            fake_runner = type(
                "FakeRunner",
                (),
                {
                    "synthetic_validator": FakeSyntheticValidator(),
                    "default_output_dir": lambda self, dataset: workdir / dataset,
                },
            )()

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", return_value=fake_runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "template_e2e",
                            "--provider",
                            "ollama",
                            "--pack",
                            "smoke",
                            "--max-samples",
                            "3",
                            "--out-dir",
                            str(workdir / "template-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "template_e2e")
            self.assertEqual(payload["pack"], "smoke")
            self.assertTrue((workdir / "template-output" / "summary.json").exists())

    def test_benchmark_command_allows_ollama_without_openai_key(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_ollama_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:0",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Name", value="Ada Lovelace")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.97,
                        source_key="Name",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", [sample])},
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", return_value=runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "funsd_plus",
                            "--provider",
                            "ollama",
                            "--max-samples",
                            "1",
                            "--out-dir",
                            str(workdir / "ollama-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "funsd_plus")
            self.assertTrue((workdir / "ollama-output" / "summary.json").exists())

    def test_benchmark_command_does_not_build_pipeline_eagerly(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_lazy_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:0",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Name", value="Ada Lovelace")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.97,
                        source_key="Name",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", [sample])},
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "formai.cli.build_default_pipeline",
                    side_effect=AssertionError("pipeline should not be built for benchmark"),
                ):
                    with patch("formai.cli._build_benchmark_runner", return_value=runner):
                        with patch(
                            "sys.argv",
                            [
                                "formai",
                                "benchmark",
                                "--dataset",
                                "funsd_plus",
                                "--provider",
                                "glm_ocr",
                                "--max-samples",
                                "1",
                                "--out-dir",
                                str(workdir / "lazy-output"),
                            ],
                        ):
                            with redirect_stdout(stdout):
                                main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["sample_count"], 1)
            self.assertTrue((workdir / "lazy-output" / "summary.json").exists())

    def test_benchmark_command_surfaces_dependency_errors_cleanly(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "formai.cli._build_benchmark_runner",
                side_effect=IntegrationUnavailable("glm deps missing"),
            ):
                with patch(
                    "sys.argv",
                    [
                        "formai",
                        "benchmark",
                        "--dataset",
                        "funsd_plus",
                        "--provider",
                        "glm_ocr",
                    ],
                ):
                    with self.assertRaises(SystemExit) as context:
                        main()

        self.assertEqual(str(context.exception), "glm deps missing")

    def test_benchmark_command_prints_summary_json(self):
        with tempfile.TemporaryDirectory(prefix="formai_bench_cli_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            sample = BenchmarkSample(
                sample_id="funsd_plus:test:0",
                dataset="funsd_plus",
                split="test",
                rendered_pages=[_png_rendered_page()],
                expected_fields=[ExpectedField(key="Name", value="Ada Lovelace")],
            )
            llm = FakeVisionLLMClient(
                detected_fields=[],
                extracted_values={
                    "Name": FieldValue(
                        value="Ada Lovelace",
                        confidence=0.97,
                        source_key="Name",
                    )
                },
            )
            runner = BenchmarkRunner(
                DataExtractorAgent(config, llm),
                adapters={"funsd_plus": FakeDatasetAdapter("funsd_plus", [sample])},
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {"OPENAI_API_KEY": "dummy-key"}, clear=False):
                with patch("formai.cli._build_benchmark_runner", return_value=runner):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "funsd_plus",
                            "--split",
                            "test",
                            "--max-samples",
                            "1",
                            "--out-dir",
                            str(workdir / "cli-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "funsd_plus")
            self.assertEqual(payload["sample_count"], 1)
            self.assertIn("aggregate_metrics", payload)
            self.assertTrue((workdir / "cli-output" / "summary.json").exists())

    def test_benchmark_command_accepts_validation_matrix_dataset(self):
        class FakeValidationRunner:
            def default_output_dir(self, dataset_name):
                return Path("/tmp") / dataset_name

            def run_validation_matrix(self, output_dir, split="test", max_samples=None, pack="custom"):
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "validation_summary.json").write_text("{}", encoding="utf-8")
                (output_dir / "manual_review_queue.json").write_text("[]", encoding="utf-8")
                (output_dir / "worst_cases.md").write_text("# Worst Cases\n", encoding="utf-8")
                return type(
                    "ValidationReport",
                    (),
                    {
                        "dataset": "validation_matrix",
                        "profile": "validation_first",
                        "split": split,
                        "passed": True,
                        "dataset_summaries": [],
                        "gates": [],
                        "manual_review_queue": [],
                        "output_dir": output_dir,
                    },
                )()

        with tempfile.TemporaryDirectory(prefix="formai_validation_cli_") as temp_dir:
            workdir = Path(temp_dir)
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch("formai.cli._build_benchmark_runner", return_value=FakeValidationRunner()):
                    with patch(
                        "sys.argv",
                        [
                            "formai",
                            "benchmark",
                            "--dataset",
                            "validation_matrix",
                            "--provider",
                            "ollama",
                            "--out-dir",
                            str(workdir / "validation-output"),
                        ],
                    ):
                        with redirect_stdout(stdout):
                            main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["dataset"], "validation_matrix")
            self.assertTrue((workdir / "validation-output" / "validation_summary.json").exists())

    def test_prepare_colab_benchmark_command_writes_bundle(self):
        with tempfile.TemporaryDirectory(prefix="formai_colab_bundle_") as temp_dir:
            workdir = Path(temp_dir)
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "sys.argv",
                    [
                        "formai",
                        "prepare-colab-benchmark",
                        "--dataset",
                        "turkish_petitions",
                        "--pack",
                        "smoke",
                        "--max-samples",
                        "2",
                        "--out-dir",
                        str(workdir / "colab-bundle"),
                    ],
                ):
                    with redirect_stdout(stdout):
                        main()

            payload = json.loads(stdout.getvalue())
            bundle_dir = workdir / "colab-bundle"
            self.assertEqual(payload["dataset"], "turkish_petitions")
            self.assertEqual(payload["recommended_stack"]["provider"], "glm_ocr")
            self.assertEqual(payload["recommended_stack"]["layout_backend"], "surya")
            self.assertEqual(payload["recommended_stack"]["perception_backend"], "chandra")
            self.assertTrue((bundle_dir / "benchmark_spec.json").exists())
            self.assertTrue((bundle_dir / "bootstrap_colab.py").exists())
            self.assertTrue((bundle_dir / "run_benchmark_in_colab.py").exists())
            self.assertTrue((bundle_dir / "README.md").exists())
            archive_path = bundle_dir / "formai_workspace.tar.gz"
            self.assertTrue(archive_path.exists())

            with tarfile.open(archive_path, "r:gz") as archive:
                names = archive.getnames()
            self.assertIn("formai_workspace/pyproject.toml", names)
            self.assertIn("formai_workspace/src/formai/cli.py", names)

    def test_prepare_colab_benchmark_command_respects_overrides(self):
        with tempfile.TemporaryDirectory(prefix="formai_colab_bundle_overrides_") as temp_dir:
            workdir = Path(temp_dir)
            stdout = io.StringIO()

            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "sys.argv",
                    [
                        "formai",
                        "prepare-colab-benchmark",
                        "--dataset",
                        "funsd_plus",
                        "--provider",
                        "openai",
                        "--intake-backend",
                        "openai",
                        "--layout-backend",
                        "native",
                        "--perception-backend",
                        "chandra",
                        "--resolver-backend",
                        "turkish_gemma",
                        "--region-adjudicator-backend",
                        "openai",
                        "--verification-backend",
                        "openai",
                        "--runner-backend",
                        "hamilton",
                        "--out-dir",
                        str(workdir / "colab-bundle"),
                    ],
                ):
                    with redirect_stdout(stdout):
                        main()

            payload = json.loads(stdout.getvalue())
            spec = json.loads((workdir / "colab-bundle" / "benchmark_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["recommended_stack"]["provider"], "openai")
            self.assertEqual(payload["recommended_stack"]["layout_backend"], "native")
            self.assertEqual(spec["verification_backend"], "openai")
            self.assertEqual(spec["runner_backend"], "hamilton")


class GLMOCRHelperTests(unittest.TestCase):
    def test_extract_json_payload_strips_code_fences(self):
        payload = _extract_json_payload(
            """```json
{"values":[{"key":"Name","value":"Ada","raw_text":"Ada","confidence":0.9}]}
```"""
        )

        self.assertEqual(payload["values"][0]["key"], "Name")

    def test_normalize_extraction_payload_accepts_simple_key_value_object(self):
        payload = _normalize_extraction_payload({"Name": "Ada Lovelace", "Date": ""})

        self.assertEqual(payload["Name"]["value"], "Ada Lovelace")
        self.assertEqual(payload["Name"]["raw_text"], "Ada Lovelace")
        self.assertEqual(payload["Date"]["value"], "")
        self.assertIsNone(payload["Name"]["confidence"])


class OllamaVisionTests(unittest.TestCase):
    def test_encode_image_downsizes_large_rgba_pages_for_ollama(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")
        page = _png_rendered_page(width=2200, height=1800)

        encoded = client._encode_image(page)

        import base64
        from PIL import Image

        payload = base64.b64decode(encoded)
        with Image.open(io.BytesIO(payload)) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertLessEqual(max(image.size), 1536)

    def test_extract_structured_data_reads_json_object_from_chat_response(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"message":{"content":"{\\"Name\\":\\"Ada Lovelace\\",\\"Date\\":\\"\\"}"}}'

        with patch("formai.llm.ollama_vision.urlopen", return_value=_FakeResponse()):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Name", "Date"],
            )

        self.assertEqual(values["Name"].value, "Ada Lovelace")
        self.assertAlmostEqual(values["Name"].confidence, 0.82)
        self.assertEqual(values["Date"].value, "")

    def test_extract_structured_data_refines_contact_multivalue_fields(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            return_value={"Fax:": "202-659-8287"},
        ):
            with patch.object(
                client,
                "_text_response",
                return_value="Fax: 202-659-8287\nFax: 212-907-5544",
            ):
                values = client.extract_structured_data(
                    pages=[_png_rendered_page()],
                    expected_keys=["Fax:"],
                )

        self.assertEqual(values["Fax:"].value, "202-659-8287\n212-907-5544")

    def test_extract_structured_data_refines_empty_fields_with_targeted_retry(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {"Comments:": ""},
                {"Comments:": "P.O. Box 834080 Permit # 359"},
                {"Comments:": "P.O. Box 834080 Permit # 359"},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Comments:"],
            )

        self.assertEqual(values["Comments:"].value, "P.O. Box 834080 Permit # 359")

    def test_extract_structured_data_refines_termination_status_words(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {"Termination Date:": ""},
                {"Termination Date:": ""},
                {"Termination Date:": "Permanent"},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Termination Date:"],
            )

        self.assertEqual(values["Termination Date:"].value, "Permanent")

    def test_extract_structured_data_does_not_borrow_neighbor_date_for_termination(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {"Date:": "8/5/96", "Termination Date:": ""},
                {"Date:": "8/5/96", "Termination Date:": "8/5/96"},
                {"Termination Date:": "8/5/96"},
                {"Termination Date:": "8/5/96"},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Date:", "Termination Date:"],
            )

        self.assertEqual(values["Date:"].value, "8/5/96")
        self.assertEqual(values["Termination Date:"].value, "")

    def test_extract_structured_data_refines_duplicate_date_family_fields(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {
                    "Date:": "04/27/98",
                    "Expiration Date": "08/15/98",
                    "Offer Complete": "08/15/98",
                },
                {
                    "Date:": "04/27/98",
                    "Expiration Date": "06/16/98",
                    "Offer Complete": "06/15/98",
                },
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Date:", "Expiration Date", "Offer Complete"],
            )

        self.assertEqual(values["Expiration Date"].value, "06/16/98")
        self.assertEqual(values["Offer Complete"].value, "06/15/98")

    def test_extract_structured_data_refines_address_heavy_fields(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {"ADDRESS": "WYTON HUNTINGDON CAMB. PE17 2DT"},
                {"ADDRESS": "WYTON Department of Pathology, Woodmansterne Road, HUNTINGDON Carshalton, CAMB. PE17 2DT."},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["ADDRESS"],
            )

        self.assertIn("Department of Pathology", values["ADDRESS"].value)
        self.assertIn("Woodmansterne Road", values["ADDRESS"].value)

    def test_extract_structured_data_refines_short_code_fields(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {"Company": "M/A/R/C"},
                {"Company": "MIA/R/C"},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Company"],
            )

        self.assertEqual(values["Company"].value, "MIA/R/C")

    def test_extract_structured_data_refines_precision_fields(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(client, "_text_response", return_value="Fax: 336 741 5327"), patch.object(
            client,
            "_json_response",
            side_effect=[
                {"Comments:": "P.O. Box 83408 Permit # 359", "FAX": "336 741 5327"},
                {"Comments:": "P.O. Box 83408 Permit # 359"},
                {"FAX": "336 741 3327"},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Comments:", "FAX"],
            )

        self.assertEqual(values["Comments:"].value, "P.O. Box 834080 Permit # 359")
        self.assertEqual(values["FAX"].value, "336 741 3327")

    def test_extract_structured_data_refines_police_station_without_procedural_noise(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {"Police Station": "154 G.P. G. P. P.S."},
                {"Police Station": "Airport P.S."},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Police Station"],
            )

        self.assertEqual(values["Police Station"].value, "Airport")

    def test_extract_contact_values_from_transcript_deduplicates_and_groups(self):
        values = _extract_contact_values_from_transcript(
            "Fax: 202-659-8287\nPhone: 202-739-0285\nFax: 212-907-5544\nphone: 202-739-0285"
        )

        self.assertEqual(values["fax"], "202-659-8287\n212-907-5544")
        self.assertEqual(values["phone"], "202-739-0285")

    def test_extract_contact_values_from_transcript_splits_inline_labels(self):
        values = _extract_contact_values_from_transcript(
            "Phone: 202-739-0285; Fax: 202-659-8287.\nPhone: 212-878-2149"
        )

        self.assertEqual(values["phone"], "202-739-0285\n212-878-2149")
        self.assertEqual(values["fax"], "202-659-8287")

    def test_extract_structured_data_refines_choice_fields(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {"Type:": "Product X Process Packaging Flavor Tobacco Material Other"},
                {"Type:": "Product"},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Type:"],
            )

        self.assertEqual(values["Type:"].value, "Product")

    def test_extract_structured_data_collapses_choice_marker_without_refinement_help(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        with patch.object(
            client,
            "_json_response",
            side_effect=[
                {"Type:": "Product X Process Packaging Flavor Tobacco Material Other"},
                {"Type:": "Product X Process Packaging Flavor Tobacco Material Other"},
            ],
        ):
            values = client.extract_structured_data(
                pages=[_png_rendered_page()],
                expected_keys=["Type:"],
            )

        self.assertEqual(values["Type:"].value, "Product")

    def test_long_question_with_phone_text_is_not_treated_as_contact_field(self):
        client = OllamaVisionClient(model="glm-ocr", base_url="http://localhost:11434")

        self.assertFalse(
            client._is_contact_key(
                "IT M/A/R/C Is supplier, do you Phone # (910) 727-0314 need a M/A/R/C P.O. Box?"
            )
        )


class ExtractionHeuristicTests(unittest.TestCase):
    def test_police_station_crop_does_not_beat_better_page_value(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        field = AcroField(
            name="police_station",
            field_kind=FieldKind.TEXT,
            box=BoundingBox(page_number=1, left=10, top=10, right=80, bottom=20),
            page_number=1,
            label="Police Station",
        )

        self.assertFalse(agent._is_crop_value_better(field, "Airport", "154 G.P. G. P. P.S."))
        self.assertTrue(agent._is_crop_value_better(field, "Police Station Form", "Airport"))

    def test_complainant_name_crop_only_replaces_similar_cleaner_value(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        field = AcroField(
            name="complainant_name",
            field_kind=FieldKind.TEXT,
            box=BoundingBox(page_number=1, left=10, top=10, right=80, bottom=20),
            page_number=1,
            label="Complainant Name",
        )

        self.assertTrue(
            agent._is_crop_value_better(
                field,
                "Sakabwalim Mondot, SI of Police",
                "Sakabwalim Mondot",
            )
        )
        self.assertFalse(
            agent._is_crop_value_better(
                field,
                "Sakabwalim Mondot",
                "Airport Police",
            )
        )
        self.assertTrue(
            agent._is_crop_value_better(
                field,
                "St. Rajib Mr. Singha",
                "Bijox Saha",
            )
        )

    def test_police_station_crop_uses_wider_context_window(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        field = AcroField(
            name="police_station",
            field_kind=FieldKind.TEXT,
            box=BoundingBox(page_number=1, left=100, top=100, right=180, bottom=120),
            page_number=1,
            label="Police Station",
        )
        page = RenderedPage(
            page_number=1,
            mime_type="image/png",
            image_bytes=_png_rendered_page().image_bytes,
            width=300,
            height=300,
        )

        cropped = agent._crop_page_for_field(page, field)

        self.assertGreater(cropped.width, 150)

    def test_multiline_segment_crops_extend_visible_text(self):
        class SegmentAwareVisionClient(FakeVisionLLMClient):
            def __init__(self):
                super().__init__(detected_fields=[], extracted_values={})
                self.calls = 0

            def extract_structured_data(self, pages, expected_keys):
                key = expected_keys[0]
                self.calls += 1
                if self.calls == 1:
                    return {
                        key: FieldValue(
                            value="Line one\nLine two",
                            confidence=0.72,
                            source_key=key,
                            raw_text="Line one\nLine two",
                        )
                    }
                values = {
                    2: "Line two",
                    3: "Line three",
                }
                return {
                    key: FieldValue(
                        value=values.get(self.calls, ""),
                        confidence=0.86,
                        source_key=key,
                        raw_text=values.get(self.calls, ""),
                    )
                }

        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, SegmentAwareVisionClient())
        page = _draw_rendered_page(
            240,
            120,
            lambda draw: (
                draw.line((24, 28, 190, 28), fill="black", width=2),
                draw.line((24, 52, 210, 52), fill="black", width=2),
                draw.line((24, 72, 210, 72), fill="black", width=2),
            ),
        )
        target_fields = [
            AcroField(
                name="describe_the_incident",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=20, top=20, right=200, bottom=40),
                page_number=1,
                label="describe_the_incident",
            ),
            AcroField(
                name="describe_the_incident__body",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=20, top=44, right=220, bottom=60),
                page_number=1,
                label="describe_the_incident__body",
            ),
            AcroField(
                name="describe_the_incident__body_2",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(page_number=1, left=20, top=64, right=220, bottom=80),
                page_number=1,
                label="describe_the_incident__body_2",
            ),
        ]

        result = agent.extract_from_rendered_pages(
            rendered_pages=[page],
            target_fields=target_fields,
            source_name="segment-crop-sample",
        )

        self.assertEqual(
            result.structured_data["describe_the_incident"].value,
            "Line one\nLine two\nLine three",
        )

    def test_multiline_segment_crops_merge_overlapping_tail_text(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))

        combined = agent._combine_multiline_segment_values(
            [
                "Vehicle slid across the lane and hit the barrier near the tunnel entrance.",
                "hit the barrier near the tunnel entrance before stopping on the shoulder.",
                "Witness 2: Elif Yilmaz, 555-013-0099",
            ]
        )

        self.assertIn("before stopping on the shoulder", combined)
        self.assertIn("Witness 2: Elif Yilmaz, 555-013-0099", combined)

    def test_multiline_segment_crops_do_not_try_shorter_describe_threshold(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        current = (
            "While merging from the exit ramp, I hit debris already in the roadway and then "
            "came to a stop on the shoulder"
        )

        self.assertLess(len(current), 140)
        self.assertFalse(
            agent._should_try_multiline_segment_crops(
                "describe_the_incident",
                current,
            )
        )

    def test_checkbox_pixel_detector_reads_scaled_checked_box(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        page = _draw_rendered_page(
            400,
            400,
            lambda draw: (
                draw.rectangle((78, 78, 122, 122), outline="black", width=3),
                draw.line((84, 84, 116, 116), fill="black", width=4),
                draw.line((116, 84, 84, 116), fill="black", width=4),
            ),
        )
        field = AcroField(
            name="approved_yes",
            field_kind=FieldKind.CHECKBOX,
            box=BoundingBox(
                page_number=1,
                left=20,
                top=20,
                right=30,
                bottom=30,
                reference_width=100,
                reference_height=100,
            ),
            page_number=1,
            label="Approved Yes",
        )

        refined = agent._refine_checkbox_fields([page], [field], {})

        self.assertEqual(refined["Approved Yes"].value, "yes")
        self.assertEqual(refined["Approved Yes"].source_kind, "checkbox_pixel")

    def test_low_ink_multiline_value_is_cleared(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        page = _png_rendered_page(width=300, height=200)
        field = AcroField(
            name="if_yes_describe_the_injuries",
            field_kind=FieldKind.MULTILINE,
            box=BoundingBox(
                page_number=1,
                left=50,
                top=50,
                right=250,
                bottom=110,
                reference_width=300,
                reference_height=200,
            ),
            page_number=1,
            label="If yes, describe the injuries",
        )

        refined = agent._suppress_low_ink_multiline_fields(
            [page],
            [field],
            {
                "if_yes_describe_the_injuries": FieldValue(
                    value="hallucinated text",
                    confidence=0.7,
                    source_key="if_yes_describe_the_injuries",
                    raw_text="hallucinated text",
                    source_kind="llm_crop",
                )
            },
        )

        self.assertEqual(refined["if_yes_describe_the_injuries"].value, "")
        self.assertIn("missing_value", refined["if_yes_describe_the_injuries"].review_reasons)

    def test_checkbox_group_prefers_blue_marked_option(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        page = _draw_rendered_page(
            400,
            300,
            lambda draw: (
                draw.rectangle((96, 96, 126, 126), outline="black", width=2),
                draw.rectangle((196, 96, 226, 126), outline="black", width=2),
                draw.line((202, 102, 220, 120), fill=(40, 70, 180), width=4),
                draw.line((220, 102, 202, 120), fill=(40, 70, 180), width=4),
            ),
        )
        yes_field = AcroField(
            name="approved_yes",
            field_kind=FieldKind.CHECKBOX,
            box=BoundingBox(
                page_number=1,
                left=96,
                top=96,
                right=126,
                bottom=126,
                reference_width=400,
                reference_height=300,
            ),
            page_number=1,
            label="approved_yes",
        )
        no_field = AcroField(
            name="approved_no",
            field_kind=FieldKind.CHECKBOX,
            box=BoundingBox(
                page_number=1,
                left=196,
                top=96,
                right=226,
                bottom=126,
                reference_width=400,
                reference_height=300,
            ),
            page_number=1,
            label="approved_no",
        )

        refined = agent._refine_checkbox_groups(
            [page],
            [yes_field, no_field],
            {
                "approved_yes": FieldValue(value="", confidence=0.0, source_key="approved_yes"),
                "approved_no": FieldValue(value="", confidence=0.0, source_key="approved_no"),
            },
        )

        self.assertEqual(refined["approved_yes"].value, "")
        self.assertEqual(refined["approved_no"].value, "yes")
        self.assertEqual(refined["approved_no"].source_kind, "checkbox_blue_search")

    def test_checkbox_group_prefers_black_marked_option(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        page = _draw_rendered_page(
            400,
            300,
            lambda draw: (
                draw.rectangle((96, 96, 126, 126), outline="black", width=2),
                draw.rectangle((196, 96, 226, 126), outline="black", width=2),
                draw.line((202, 112, 210, 120), fill="black", width=4),
                draw.line((210, 120, 222, 102), fill="black", width=4),
            ),
        )
        yes_field = AcroField(
            name="approved_yes",
            field_kind=FieldKind.CHECKBOX,
            box=BoundingBox(
                page_number=1,
                left=96,
                top=96,
                right=126,
                bottom=126,
                reference_width=400,
                reference_height=300,
            ),
            page_number=1,
            label="approved_yes",
        )
        no_field = AcroField(
            name="approved_no",
            field_kind=FieldKind.CHECKBOX,
            box=BoundingBox(
                page_number=1,
                left=196,
                top=96,
                right=226,
                bottom=126,
                reference_width=400,
                reference_height=300,
            ),
            page_number=1,
            label="approved_no",
        )

        refined = agent._refine_checkbox_groups(
            [page],
            [yes_field, no_field],
            {
                "approved_yes": FieldValue(value="", confidence=0.0, source_key="approved_yes"),
                "approved_no": FieldValue(value="", confidence=0.0, source_key="approved_no"),
            },
        )

        self.assertEqual(refined["approved_yes"].value, "")
        self.assertEqual(refined["approved_no"].value, "yes")
        self.assertEqual(refined["approved_no"].source_kind, "checkbox_mark_group")

    def test_checkbox_group_supports_identification_selected_triplet(self):
        config = FormAIConfig.from_env(Path.cwd())
        agent = DataExtractorAgent(config, FakeVisionLLMClient([], {}))
        page = _draw_rendered_page(
            600,
            240,
            lambda draw: (
                draw.rectangle((58, 118, 90, 150), outline="black", width=2),
                draw.rectangle((238, 118, 270, 150), outline="black", width=2),
                draw.rectangle((58, 176, 90, 208), outline="black", width=2),
                draw.line((244, 134, 252, 142), fill="black", width=4),
                draw.line((252, 142, 264, 124), fill="black", width=4),
            ),
        )
        fields = [
            AcroField(
                name="driver_s_license_no_selected",
                field_kind=FieldKind.CHECKBOX,
                box=BoundingBox(
                    page_number=1,
                    left=9.7,
                    top=49.2,
                    right=15.0,
                    bottom=62.5,
                    reference_width=100,
                    reference_height=100,
                ),
                page_number=1,
                label="driver_s_license_no_selected",
            ),
            AcroField(
                name="passport_no_selected",
                field_kind=FieldKind.CHECKBOX,
                box=BoundingBox(
                    page_number=1,
                    left=39.7,
                    top=49.2,
                    right=45.0,
                    bottom=62.5,
                    reference_width=100,
                    reference_height=100,
                ),
                page_number=1,
                label="passport_no_selected",
            ),
            AcroField(
                name="other_selected",
                field_kind=FieldKind.CHECKBOX,
                box=BoundingBox(
                    page_number=1,
                    left=9.7,
                    top=73.3,
                    right=15.0,
                    bottom=86.7,
                    reference_width=100,
                    reference_height=100,
                ),
                page_number=1,
                label="other_selected",
            ),
        ]

        refined = agent._refine_checkbox_groups(
            [page],
            fields,
            {
                field.name: FieldValue(value="", confidence=0.0, source_key=field.name)
                for field in fields
            },
        )

        self.assertEqual(refined["driver_s_license_no_selected"].value, "")
        self.assertEqual(refined["passport_no_selected"].value, "yes")
        self.assertEqual(refined["other_selected"].value, "")
        self.assertEqual(refined["passport_no_selected"].source_kind, "checkbox_mark_group")


if __name__ == "__main__":
    unittest.main()
