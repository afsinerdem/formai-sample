from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Sequence

from formai.agents.acroform_generator import AcroFormGeneratorAgent
from formai.agents.data_extractor import DataExtractorAgent
from formai.agents.final_assembler import FinalAssemblerAgent
from formai.agents.input_evaluator import InputEvaluatorAgent
from formai.artifacts import (
    AcroInspectionArtifact,
    EvidenceArtifact,
    FieldDetectionArtifact,
    FillablePdfArtifact,
    IntakeArtifact,
    LayoutValidationArtifact,
    NormalizedValuesArtifact,
    RasterArtifact,
    RegionPlanArtifact,
    RouteArtifact,
    TemplateIdentityArtifact,
    TemplateLayoutArtifact,
    TranscriptArtifact,
    UserFeedbackArtifact,
    VerificationArtifact,
)
from formai.config import FormAIConfig
from formai.models import ExtractionResult, PipelineResult
from formai.node_context import NodeContext
from formai.nodes.assembly import build_render_plan_artifact
from formai.nodes.evidence import gather_field_evidence, resolve_ambiguous_fields, resolve_field_values
from formai.nodes.generation import normalize_field_names, to_fillable_artifact, to_layout_validation_artifact
from formai.nodes.intake import classify_document, intake_document, route_document
from formai.nodes.normalization import normalize_turkish_values
from formai.nodes.perception import plan_region_reads, rasterize_document, transcribe_document
from formai.nodes.template import analyze_template_layout, detect_template_fields, infer_template_identity
from formai.nodes.verification import build_user_feedback
from formai.perception.chandra_engine import ChandraDocumentPerceptionEngine
from formai.perception.qwen_adjudicator import QwenRegionAdjudicator
from formai.perception.surya_layout import SuryaLayoutEngine
from formai.pdf.rasterizer import rasterize_pdf
from formai.profiles import infer_profile_from_target_fields


class FormAIRunner:
    def __init__(
        self,
        *,
        config: FormAIConfig,
        evaluator: InputEvaluatorAgent,
        generator: AcroFormGeneratorAgent,
        extractor: DataExtractorAgent,
        assembler: FinalAssemblerAgent,
        layout_engine=None,
        context: NodeContext,
    ):
        self.config = config
        self.evaluator = evaluator
        self.generator = generator
        self.extractor = extractor
        self.assembler = assembler
        self.context = context
        self.layout_engine = layout_engine or SuryaLayoutEngine(enabled=self.config.layout_backend == "surya")
        self.perception_engine = ChandraDocumentPerceptionEngine(
            context.perception_client or context.verification_client or context.template_client or context.intake_client
        )
        self.adjudicator = QwenRegionAdjudicator(context.adjudicator_client or context.intake_client)

    def analyze(self, template_pdf: Path):
        analysis = self.evaluator.evaluate(template_pdf)
        rendered_pages = []
        try:
            rendered_pages = rasterize_pdf(template_pdf, dpi=self.config.raster_dpi)
        except Exception:
            rendered_pages = []
        classification = classify_document(
            analysis,
            rendered_pages,
            self.context.intake_client,
        )
        intake = intake_document(analysis, classification)
        route = route_document(intake)
        with ThreadPoolExecutor(max_workers=2) as executor:
            layout_future = executor.submit(analyze_template_layout, template_pdf, self.layout_engine)
            identity_future = executor.submit(infer_template_identity, analysis)
            layout = layout_future.result()
            identity = identity_future.result()
        fields = detect_template_fields(analysis, layout)
        return analysis, intake, route, layout, identity, fields

    def prepare_fillable(self, template_pdf: Path, output_path: Path):
        analysis, intake, route, layout, identity, fields = self.analyze(template_pdf)
        rename = normalize_field_names(analysis)
        generation = self.generator.generate(template_pdf, analysis, output_path)
        fillable = to_fillable_artifact(generation)
        validation = to_layout_validation_artifact(generation)
        return {
            "analysis": analysis,
            "intake": intake,
            "route": route,
            "layout": layout,
            "identity": identity,
            "fields": fields,
            "rename": rename,
            "fillable": fillable,
            "validation": validation,
            "generation": generation,
        }

    def inspect_existing_acroform(self, pdf_path: Path) -> AcroInspectionArtifact:
        analysis = self.evaluator.evaluate(pdf_path)
        return AcroInspectionArtifact(
            source_path=pdf_path,
            fields=list(analysis.existing_fields),
            issues=list(analysis.issues),
        )

    def extract(
        self,
        filled_pdf: Path,
        target_fields,
    ):
        cache_dir = self.config.working_dir / ".formai_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        raster_artifact, rendered_pages = rasterize_document(
            pdf_path=filled_pdf,
            dpi=self.config.raster_dpi,
            cache_dir=cache_dir,
        )
        return self.extract_from_rendered_pages(
            rendered_pages=rendered_pages,
            target_fields=target_fields,
            source_name=str(filled_pdf),
            raster_artifact=raster_artifact,
        )

    def extract_from_rendered_pages(
        self,
        *,
        rendered_pages,
        target_fields,
        source_name: str,
        raster_artifact: RasterArtifact | None = None,
    ):
        if raster_artifact is None:
            raster_artifact = RasterArtifact(
                source_path=Path(source_name),
                dpi=self.config.raster_dpi,
                pages=[],
            )
        with ThreadPoolExecutor(max_workers=2) as executor:
            transcript_future = executor.submit(transcribe_document, rendered_pages, self.perception_engine)
            coarse_layout_future = executor.submit(
                self.layout_engine.analyze_filled_pages,
                rendered_pages,
                None,
            )
            transcript_artifact = transcript_future.result()
            coarse_layout = coarse_layout_future.result()
        try:
            filled_layout = self.layout_engine.analyze_filled_pages(
                rendered_pages,
                transcript_artifact.transcript,
            )
        except Exception:
            filled_layout = coarse_layout
        extraction = self.extractor.extract_from_rendered_pages(
            rendered_pages=rendered_pages,
            target_fields=target_fields,
            source_name=source_name,
        )
        region_plan = plan_region_reads(
            target_fields=target_fields,
            extracted_values=extraction.structured_data,
            filled_layout=filled_layout,
            max_requests=max(4, int(getattr(self.config, "region_read_concurrency", 6) or 6) * 2),
        )
        region_reads = self.perception_engine.read_regions(rendered_pages, region_plan)
        evidence = gather_field_evidence(
            target_fields=target_fields,
            structured_data=extraction.structured_data,
            transcript=transcript_artifact.transcript,
            region_reads=region_reads,
        )
        adjudication = resolve_ambiguous_fields(evidence, self.adjudicator)
        resolution = resolve_field_values(
            structured_data=extraction.structured_data,
            adjudication=adjudication,
        )
        profile = infer_profile_from_target_fields(target_fields)
        normalized = normalize_turkish_values(
            resolved_values=resolution.values,
            profile=profile,
        )
        extraction.structured_data = normalized.values
        extraction.transcript = transcript_artifact.transcript
        extraction.transcript_summary = transcript_artifact.transcript.summary() if transcript_artifact.transcript else {}
        extraction.field_evidence = evidence.field_evidence
        extraction.confidence = normalized.confidence
        return {
            "raster": raster_artifact,
            "transcript": transcript_artifact,
            "filled_layout": filled_layout,
            "region_plan": region_plan,
            "region_reads": region_reads,
            "evidence": evidence,
            "adjudication": adjudication,
            "resolution": resolution,
            "normalized": normalized,
            "extraction": extraction,
        }

    def assemble(
        self,
        fillable_pdf_path: Path,
        extraction: ExtractionResult,
        output_path: Path,
        *,
        source_reference: Path | None = None,
        route: str = "filled_document",
    ):
        result = self.assembler.assemble(
            fillable_pdf_path,
            extraction,
            output_path,
            source_reference=source_reference,
        )
        verification = VerificationArtifact()
        if result.self_check is not None:
            verification = VerificationArtifact(
                passed=result.self_check.passed,
                overall_score=result.self_check.overall_score,
                evidence_score=result.self_check.evidence_score,
                llm_score=result.self_check.llm_score,
                geometry_score=result.self_check.geometry_score,
                review_required=result.self_check.review_required,
                warnings=list(result.self_check.layout_warnings),
            )
        feedback = build_user_feedback(
            route=route,
            confidence=result.confidence,
            verification=verification,
        )
        return {
            "assembly": result,
            "verification": verification,
            "feedback": feedback,
        }

    def run(
        self,
        *,
        template_pdf: Path,
        filled_pdf: Path,
        fillable_output: Path,
        final_output: Path,
    ) -> PipelineResult:
        prepared = self.prepare_fillable(template_pdf, fillable_output)
        extracted = self.extract(filled_pdf, prepared["generation"].acro_fields)
        assembled = self.assemble(
            prepared["generation"].output_path,
            extracted["extraction"],
            final_output,
            source_reference=filled_pdf,
            route=prepared["route"].route,
        )
        return PipelineResult(
            analysis=prepared["analysis"],
            generation=prepared["generation"],
            extraction=extracted["extraction"],
            assembly=assembled["assembly"],
        )
