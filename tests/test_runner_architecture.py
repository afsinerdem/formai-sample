import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from formai.config import FormAIConfig
from formai.artifacts import FilledLayoutArtifact
from formai.models import (
    AcroField,
    BoundingBox,
    DocumentIdentity,
    DocumentLanguage,
    DomainHint,
    DocumentFamily,
    DocumentKind,
    FieldKind,
    FieldValue,
    FilledDocumentTranscript,
    LayoutStyle,
    RenderedPage,
    ScriptStyle,
)
from formai.nodes.intake import intake_document, route_document
from formai.nodes.perception import plan_region_reads
from formai.perception.qwen_adjudicator import QwenRegionAdjudicator
from formai.perception.surya_layout import SuryaLayoutEngine
from formai.pipeline import (
    build_default_pipeline,
    build_document_perception_client,
    build_layout_engine,
    build_verification_client,
)
from formai.verification.engine import run_verification_check
from tests.fixture_factory import FixtureField, create_flat_template_pdf


def _reportlab_available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


class _FakeVerificationLLM:
    def review_visual_alignment(
        self,
        *,
        source_pages,
        output_pages,
        expected_values,
        profile_name,
        prompt_hint="",
    ):
        return {"overall_score": 0.86, "notes": "stable"}


class _FakePerceptionClient:
    def build_document_transcript(self, pages):
        spans = []
        for page in pages:
            text = getattr(page, "expected_text", "") or "Ada Lovelace"
            spans.append(
                SimpleNamespace(
                    text=text,
                    page_number=page.page_number,
                    confidence=0.84,
                )
            )
        return type(
            "Transcript",
            (),
            {
                "spans": spans,
                "provider": "fake_perception",
                "confidence": 0.84,
            },
        )()


class _FakeIntakeVisionClient:
    def classify_document(
        self,
        pages,
        *,
        existing_field_count=0,
        detected_field_count=0,
        embedded_text_chars=0,
    ):
        return {
            "document_kind": "flat",
            "route_hint": "blank_template",
            "document_family": "student_petition",
            "profile": "student_petition_tr",
            "language": "tr",
            "script_style": "printed",
            "layout_style": "table_form",
            "domain_hint": "education",
            "confidence": 0.88,
            "review_required": False,
            "summary": "student petition template",
        }


class _FakeAdjudicationClient:
    def adjudicate_field_candidates(self, *, candidate_values, expected_keys):
        return {
            "student_name": FieldValue(
                value="Ada Lovelace",
                confidence=0.91,
                source_key="student_name",
                raw_text="Ada Lovelace",
                source_kind="llm_adjudicated",
            )
        }


@unittest.skipUnless(_reportlab_available(), "reportlab is required")
class RunnerArchitectureTests(unittest.TestCase):
    def test_build_default_pipeline_uses_runner_backend(self):
        with tempfile.TemporaryDirectory(prefix="formai_runner_") as temp_dir:
            workdir = Path(temp_dir)
            config = FormAIConfig.from_env(workdir)
            config.runner_backend = "hamilton"
            config.vision_provider = "none"
            template_path = workdir / "template.pdf"
            create_flat_template_pdf(
                template_path,
                [
                    FixtureField("Policy Number", "Field1", 190, 720, 220),
                    FixtureField("Insured Name", "Field2", 190, 680, 220),
                ],
            )

            pipeline = build_default_pipeline(config)
            analysis = pipeline.analyze(template_path)

            self.assertEqual(analysis.document_kind, DocumentKind.FLAT)
            self.assertIsNotNone(pipeline.runner)

    def test_verification_prefers_vlm_and_perception_without_tesseract(self):
        with tempfile.TemporaryDirectory(prefix="formai_verify_") as temp_dir:
            workdir = Path(temp_dir)
            template_path = workdir / "template.pdf"
            output_path = workdir / "output.pdf"
            create_flat_template_pdf(
                template_path,
                [FixtureField("Insured Name", "Field1", 190, 720, 220)],
            )
            create_flat_template_pdf(
                output_path,
                [FixtureField("Insured Name", "Field1", 190, 720, 220)],
            )
            fields = [
                AcroField(
                    name="insured_name",
                    field_kind=FieldKind.TEXT,
                    box=BoundingBox(page_number=1, left=190, top=720, right=410, bottom=740),
                    page_number=1,
                )
            ]

            result = run_verification_check(
                source_reference=template_path,
                output_pdf_path=output_path,
                template_fields=fields,
                filled_values={"insured_name": "Ada Lovelace"},
                llm_client=_FakeVerificationLLM(),
                perception_client=_FakePerceptionClient(),
            )

            self.assertIsNotNone(result)
            self.assertGreater(result.llm_score, 0.8)
            self.assertGreater(result.overall_score, 0.7)


class RunnerArchitectureLogicTests(unittest.TestCase):
    def test_intake_document_prefers_vlm_classification_when_available(self):
        analysis = SimpleNamespace(
            source_path=Path("/tmp/template.pdf"),
            document_kind=DocumentKind.FLAT,
            document_identity=DocumentIdentity(
                document_kind=DocumentKind.FLAT,
                language=DocumentLanguage.UNKNOWN,
                script_style=ScriptStyle.UNKNOWN,
                layout_style=LayoutStyle.UNKNOWN,
                document_family=DocumentFamily.UNKNOWN,
                domain_hint=DomainHint.UNKNOWN,
                profile="generic_printed_form",
                confidence=0.42,
                signals={},
            ),
            existing_fields=[],
            detected_fields=[],
            issues=[],
            confidence=0.38,
        )

        intake = intake_document(analysis, _FakeIntakeVisionClient().classify_document([]))
        route = route_document(intake)

        self.assertEqual(intake.route_source, "vlm")
        self.assertEqual(intake.document_identity.document_family, DocumentFamily.STUDENT_PETITION)
        self.assertEqual(intake.document_identity.profile, "student_petition_tr")
        self.assertEqual(route.route, "blank_template")

    def test_intake_document_scales_percentage_style_model_confidence(self):
        analysis = SimpleNamespace(
            source_path=Path("/tmp/template.pdf"),
            document_kind=DocumentKind.FLAT,
            document_identity=DocumentIdentity(
                document_kind=DocumentKind.FLAT,
                language=DocumentLanguage.UNKNOWN,
                script_style=ScriptStyle.UNKNOWN,
                layout_style=LayoutStyle.UNKNOWN,
                document_family=DocumentFamily.UNKNOWN,
                domain_hint=DomainHint.UNKNOWN,
                profile="generic_printed_form",
                confidence=0.0,
                signals={},
            ),
            existing_fields=[],
            detected_fields=[],
            issues=[],
            confidence=0.0,
        )

        intake = intake_document(
            analysis,
            {
                "route_hint": "filled_document",
                "confidence": 70,
                "document_family": "unknown",
                "profile": "generic_printed_form",
                "summary": "test",
            },
        )

        self.assertAlmostEqual(intake.confidence, 0.7, places=3)

    def test_qwen_adjudicator_uses_provider_surface(self):
        adjudicator = QwenRegionAdjudicator(_FakeAdjudicationClient())
        resolved = adjudicator.adjudicate(
            candidate_values={
                "student_name": FieldValue(
                    value="Ada",
                    confidence=0.4,
                    source_key="student_name",
                    raw_text="Ada",
                    source_kind="ocr",
                )
            },
            expected_keys=["student_name"],
        )

        self.assertEqual(resolved["student_name"].value, "Ada Lovelace")
        self.assertEqual(resolved["student_name"].source_kind, "llm_adjudicated")

    def test_surya_layout_engine_falls_back_without_dependency(self):
        engine = SuryaLayoutEngine(enabled=False)
        page = RenderedPage(
            page_number=1,
            mime_type="image/png",
            image_bytes=b"fake",
            width=1200,
            height=1600,
        )
        transcript = FilledDocumentTranscript(
            provider="fake",
            page_count=1,
            page_texts={1: "Ogrenci No Ada Lovelace Bilgisayar Muhendisligi"},
        )

        artifact = engine.analyze_filled_pages([page], transcript)

        self.assertIn(1, artifact.page_regions)
        self.assertEqual(len(artifact.page_regions[1]), 1)
        self.assertIn("page_1_text_density", artifact.region_density)

    def test_build_layout_engine_respects_backend_toggle(self):
        with tempfile.TemporaryDirectory(prefix="formai_layout_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            config.layout_backend = "native"

            engine = build_layout_engine(config)

            self.assertFalse(engine.enabled)

    def test_role_backend_alias_maps_to_qwen_ollama_model(self):
        with tempfile.TemporaryDirectory(prefix="formai_qwen_alias_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            config.vision_provider = "ollama"
            config.verification_backend = "qwen25_vl"

            with unittest.mock.patch(
                "formai.pipeline._ollama_model_is_likely_unsupported_locally",
                return_value=False,
            ):
                client = build_verification_client(config)

            self.assertEqual(getattr(client, "model", ""), "qwen2.5vl:3b")
            self.assertEqual(getattr(client, "fallback_model", ""), "glm-ocr")

    def test_role_backend_downshifts_to_safe_model_on_low_memory_apple_silicon(self):
        with tempfile.TemporaryDirectory(prefix="formai_qwen_downshift_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            config.vision_provider = "ollama"
            config.verification_backend = "qwen25_vl"
            config.ollama_model = "glm-ocr"

            with unittest.mock.patch(
                "formai.pipeline._ollama_model_is_likely_unsupported_locally",
                return_value=True,
            ):
                client = build_verification_client(config)

            self.assertEqual(getattr(client, "model", ""), "glm-ocr")
            self.assertEqual(getattr(client, "fallback_model", ""), "")

    def test_auto_perception_backend_falls_back_when_chandra_missing(self):
        with tempfile.TemporaryDirectory(prefix="formai_perception_auto_") as temp_dir:
            config = FormAIConfig.from_env(Path(temp_dir))
            config.vision_provider = "ollama"
            config.ollama_model = "glm-ocr"
            config.perception_backend = "auto"

            with unittest.mock.patch("formai.pipeline._chandra_is_available", return_value=False):
                client = build_document_perception_client(config)

            self.assertEqual(getattr(client, "model", ""), "glm-ocr")

    def test_region_plan_uses_layout_density_to_raise_priority(self):
        field = AcroField(
            name="student_name",
            label="Student Name",
            field_kind=FieldKind.TEXT,
            box=BoundingBox(page_number=1, left=10, top=10, right=80, bottom=24),
            page_number=1,
        )

        result = plan_region_reads(
            target_fields=[field],
            extracted_values={
                "student_name": FieldValue(
                    value="Ada",
                    confidence=0.61,
                    source_key="student_name",
                    raw_text="Ada",
                    source_kind="llm_page",
                )
            },
            filled_layout=FilledLayoutArtifact(region_density={"page_1_text_density": 0.8}),
        )

        self.assertEqual(len(result.requests), 1)
        self.assertGreaterEqual(result.requests[0].priority, 3)

    def test_region_plan_prioritizes_critical_student_petition_multiline_fields(self):
        field = AcroField(
            name="danisman_gorusu",
            label="Danisman Gorusu",
            field_kind=FieldKind.MULTILINE,
            box=BoundingBox(page_number=1, left=10, top=10, right=120, bottom=28),
            page_number=1,
        )

        result = plan_region_reads(
            target_fields=[field],
            extracted_values={
                "danisman_gorusu": FieldValue(
                    value="Uygundur.",
                    confidence=0.82,
                    source_key="danisman_gorusu",
                    raw_text="Uygundur.",
                    source_kind="llm_page",
                )
            },
        )

        self.assertEqual(len(result.requests), 1)
        self.assertGreaterEqual(result.requests[0].priority, 3)
