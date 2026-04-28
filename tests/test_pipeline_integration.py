import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from formai.agents.acroform_generator import AcroFormGeneratorAgent
from formai.agents.data_extractor import DataExtractorAgent
from formai.agents.final_assembler import FinalAssemblerAgent
from formai.agents.input_evaluator import InputEvaluatorAgent
from formai.config import FormAIConfig
from formai.llm.base import NullVisionLLMClient
from formai.models import BoundingBox, DetectedField, FieldKind, FieldValue
from formai.pipeline import FormAIPipeline, build_vision_client
from formai.pdf.inspector import inspect_pdf_fields
from tests.fakes import FakeCommonFormsAdapter, FakeVisionLLMClient
from tests.fixture_factory import (
    DEFAULT_FIELDS,
    FixtureField,
    create_flat_filled_pdf,
    create_flat_template_pdf,
    create_reportlab_acroform_pdf,
    create_single_course_application_template_pdf,
    create_turkish_student_petition_template_pdf,
)


def _reportlab_available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_reportlab_available(), "reportlab is required for PDF integration tests")
class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="formai_test_")
        self.workdir = Path(self.temp_dir.name)
        self.config = FormAIConfig.from_env(self.workdir)
        self.fixture_fields = [
            FixtureField("Policy Number", "Field1", 190, 100, 220, value="PN-42"),
            FixtureField("Insured Name", "Field2", 190, 140, 220, value="Ada Lovelace"),
            FixtureField("Incident Date", "Field3", 190, 180, 180, value="2026-03-16"),
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_input_evaluator_detects_existing_acroform_and_flags_names(self):
        pdf_path = self.workdir / "fixture_acroform.pdf"
        create_reportlab_acroform_pdf(pdf_path, self.fixture_fields)

        agent = InputEvaluatorAgent(self.config, FakeVisionLLMClient([], {}))
        result = agent.evaluate(pdf_path)

        self.assertEqual(result.document_kind.value, "acroform")
        self.assertEqual(len(result.existing_fields), 3)
        self.assertFalse(all(review.is_valid for review in result.field_name_reviews))

    def test_pipeline_runs_end_to_end_with_real_pdf_outputs(self):
        template_path = self.workdir / "template.pdf"
        filled_path = self.workdir / "filled.pdf"
        fillable_output = self.workdir / "fillable.pdf"
        final_output = self.workdir / "final.pdf"

        fixture_fields = [
            FixtureField("Policy Number", "Field1", 190, 720, 220, value="PN-42"),
            FixtureField("Insured Name", "Field2", 190, 680, 220, value="Ada Lovelace"),
            FixtureField("Incident Date", "Field3", 190, 640, 180, value="2026-03-16"),
        ]
        create_flat_template_pdf(template_path, fixture_fields)
        create_flat_filled_pdf(filled_path, fixture_fields)

        detected_fields = [
            DetectedField(
                label=field.label,
                field_kind=FieldKind.TEXT,
                box=BoundingBox(
                    page_number=1,
                    left=field.x,
                    top=field.y,
                    right=field.x + field.width,
                    bottom=field.y + field.height,
                ),
                confidence=0.95,
            )
            for field in fixture_fields
        ]
        extracted_values = {
            "policy_number": FieldValue(
                value="PN-42",
                confidence=0.96,
                source_key="policy_number",
            ),
            "insured_name": FieldValue(
                value="Ada Lovelace",
                confidence=0.95,
                source_key="insured_name",
            ),
            "incident_date": FieldValue(
                value="2026-03-16",
                confidence=0.94,
                source_key="incident_date",
            ),
        }
        llm = FakeVisionLLMClient(detected_fields, extracted_values)
        pipeline = FormAIPipeline(
            evaluator=InputEvaluatorAgent(self.config, llm),
            generator=AcroFormGeneratorAgent(self.config, FakeCommonFormsAdapter(fixture_fields)),
            extractor=DataExtractorAgent(self.config, llm),
            assembler=FinalAssemblerAgent(self.config),
        )

        result = pipeline.run(template_path, filled_path, fillable_output, final_output)

        self.assertTrue(fillable_output.exists())
        self.assertTrue(final_output.exists())
        self.assertGreater(result.overall_confidence, 0.8)
        fillable_fields = inspect_pdf_fields(fillable_output)
        self.assertEqual(len(fillable_fields), 3)
        self.assertEqual(inspect_pdf_fields(final_output), [])

        from pypdf import PdfReader

        final_text = PdfReader(str(final_output)).pages[0].extract_text()
        self.assertIn("PN-42", final_text)
        self.assertIn("Ada Lovelace", final_text)
        self.assertIn("2026-03-16", final_text)

    def test_build_vision_client_auto_without_providers_returns_null_client(self):
        self.config.vision_provider = "auto"
        self.config.openai_api_key = ""
        with unittest.mock.patch("formai.pipeline._ollama_is_available", return_value=False):
            client = build_vision_client(self.config)
        self.assertIsInstance(client, NullVisionLLMClient)

    def test_input_evaluator_infers_document_identity_and_routes_student_petition_detector(self):
        pdf_path = self.workdir / "student_petition.pdf"
        create_turkish_student_petition_template_pdf(pdf_path)

        agent = InputEvaluatorAgent(self.config, FakeVisionLLMClient([], {}))
        result = agent.evaluate(pdf_path)

        self.assertEqual(result.document_kind.value, "flat")
        self.assertEqual(result.document_identity.language.value, "tr")
        self.assertEqual(result.document_identity.document_family.value, "student_petition")
        self.assertEqual(result.document_identity.domain_hint.value, "education")
        self.assertEqual(result.document_identity.profile, "student_petition_tr")
        self.assertEqual(result.routing_strategy, "structure_first")
        labels = {field.label for field in result.detected_fields}
        self.assertIn("ogrenci_no", labels)
        self.assertIn("ad_soyad", labels)
        self.assertIn("ogrenci_aciklamasi", labels)
        self.assertGreaterEqual(len(result.detected_fields), 8)

    def test_input_evaluator_routes_single_course_application_variant(self):
        pdf_path = self.workdir / "tek_ders_basvuru.pdf"
        create_single_course_application_template_pdf(pdf_path)

        agent = InputEvaluatorAgent(self.config, FakeVisionLLMClient([], {}))
        result = agent.evaluate(pdf_path)

        self.assertEqual(result.document_kind.value, "flat")
        self.assertEqual(result.document_identity.document_family.value, "student_petition")
        self.assertEqual(result.document_identity.domain_hint.value, "education")
        self.assertEqual(result.document_identity.profile, "student_petition_tr")
        self.assertEqual(result.routing_strategy, "structure_first")
        labels = {field.label for field in result.detected_fields}
        for key in {
            "tarih",
            "ogrenci_no",
            "ad_soyad",
            "telefon",
            "e_posta",
            "adres",
            "ders_adi",
            "danisman_adi",
            "mali_onay_ad_soyad",
        }:
            self.assertIn(key, labels)
        self.assertGreaterEqual(len(result.detected_fields), 15)

    def test_input_evaluator_preserves_vision_first_for_profile_aware_documents(self):
        pdf_path = self.workdir / "tek_ders_scanned_like.pdf"
        create_single_course_application_template_pdf(pdf_path)

        agent = InputEvaluatorAgent(self.config, FakeVisionLLMClient([], {}))
        with patch(
            "formai.agents.input_evaluator.analyze_pdf_routing",
            return_value=type(
                "Routing",
                (),
                {
                    "routing_strategy": "vision_first",
                    "page_character_counts": [0],
                    "has_embedded_text": False,
                },
            )(),
        ):
            result = agent.evaluate(pdf_path)

        self.assertEqual(result.document_identity.profile, "student_petition_tr")
        self.assertEqual(result.routing_strategy, "vision_first")
        self.assertEqual(result.routing_diagnostics["has_embedded_text"], "false")


if __name__ == "__main__":
    unittest.main()
