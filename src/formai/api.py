from __future__ import annotations

import io
import json
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from formai.api_jobs import FileJobStore, JobRecord, JobRunner, copy_or_link_input
from formai.config import FormAIConfig
from formai.mapping import map_extracted_values_to_fields
from formai.models import ExtractionResult, FieldMapping, FieldValue, ReviewItem
from formai.pipeline import FormAIPipeline, build_default_pipeline
from formai.pdf.inspector import inspect_pdf_fields
from formai.utils import average_confidence, derive_field_confidence, ensure_parent_directory

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
except ImportError:  # pragma: no cover - dependency guard
    FastAPI = None
    File = Form = HTTPException = UploadFile = None
    CORSMiddleware = None
    FileResponse = None


class AnalyzeTemplateRequest(BaseModel):
    template_path: str
    artifact_output_path: str = ""


class PrepareFillableRequest(BaseModel):
    template_path: str
    output_path: str


class ExtractDataRequest(BaseModel):
    filled_path: str
    fillable_path: str
    artifact_output_path: str = ""


class ApiFieldValue(BaseModel):
    value: str
    confidence: float | None = None
    raw_text: str = ""
    source_kind: str = "api_input"
    review_reasons: List[str] = Field(default_factory=list)


class ApiFieldMapping(BaseModel):
    source_key: str
    target_field: str
    confidence: float
    status: str
    notes: str = ""


class ApiReviewItem(BaseModel):
    field_key: str
    predicted_value: str
    confidence: float
    reason_code: str
    raw_text: str = ""
    source_kind: str = ""


class AssembleRequest(BaseModel):
    fillable_path: str
    output_path: str
    structured_data: Dict[str, str | ApiFieldValue]
    mappings: List[ApiFieldMapping] = Field(default_factory=list)
    review_items: List[ApiReviewItem] = Field(default_factory=list)


class ArtifactDescriptor(BaseModel):
    artifact_id: str
    kind: str
    path: str
    mime_type: str
    size_bytes: int
    step_name: str
    created_at: str
    download_url: str


class StepResultPayload(BaseModel):
    step_name: str
    status: str
    started_at: str = ""
    finished_at: str = ""
    confidence: float = 0.0
    artifact_ids: List[str] = Field(default_factory=list)
    issues: List[dict] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)


class JobResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: str
    updated_at: str
    step_results: List[StepResultPayload] = Field(default_factory=list)
    artifacts: List[ArtifactDescriptor] = Field(default_factory=list)
    issues: List[dict] = Field(default_factory=list)
    review_items: List[dict] = Field(default_factory=list)
    confidence: float = 0.0
    error_message: str = ""


class APIInputValidationError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

    def to_detail(self) -> dict:
        return {"code": self.code, "message": self.message}


class InputSpec(BaseModel):
    role: str
    allowed_kinds: tuple[str, ...]


SUPPORTED_VISION_PROVIDERS = ("auto", "openai", "ollama", "glm_ocr")


def create_app(
    config: FormAIConfig | None = None,
    pipeline: FormAIPipeline | None = None,
):
    if FastAPI is None or CORSMiddleware is None or FileResponse is None:
        raise RuntimeError(
            "fastapi is not installed. Install with: pip install -e '.[api]'"
        )

    config = config or FormAIConfig.from_env(Path.cwd())
    pipeline = pipeline or build_default_pipeline(config)
    job_store = FileJobStore(_job_base_dir(config))
    job_runner = JobRunner(job_store)
    service = APIJobService(config=config, pipeline=pipeline, store=job_store, runner=job_runner)

    app = FastAPI(title="FormAI API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(config),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "vision_provider": config.vision_provider,
            "working_dir": str(config.working_dir),
            "jobs_dir": str(_job_base_dir(config)),
        }

    # Legacy sync endpoints kept for internal compatibility.
    @app.post("/analyze-template")
    def analyze_template(request: AnalyzeTemplateRequest):
        result = pipeline.analyze(Path(request.template_path))
        artifact_path = _write_optional_artifact(request.artifact_output_path, result)
        return {
            "artifact_path": artifact_path,
            "result": _serialize(result),
        }

    @app.post("/prepare-fillable")
    def prepare_fillable(request: PrepareFillableRequest):
        analysis, generation = pipeline.prepare_fillable(
            Path(request.template_path),
            Path(request.output_path),
        )
        return {
            "artifact_path": str(Path(request.output_path)),
            "analysis": _serialize(analysis),
            "result": _serialize(generation),
        }

    @app.post("/extract-data")
    def extract_data(request: ExtractDataRequest):
        result = pipeline.extract(Path(request.filled_path), Path(request.fillable_path))
        artifact_path = _write_optional_artifact(request.artifact_output_path, result)
        return {
            "artifact_path": artifact_path,
            "result": _serialize(result),
        }

    @app.post("/assemble")
    def assemble(request: AssembleRequest):
        fillable_path = Path(request.fillable_path)
        structured_data = _coerce_structured_data(dict(request.structured_data))
        mappings = _coerce_mappings(request.mappings) or _derive_mappings(
            structured_data,
            fillable_path,
            config,
        )
        review_items = [ReviewItem(**item.model_dump()) for item in request.review_items]
        extraction = ExtractionResult(
            source_path=fillable_path,
            structured_data=structured_data,
            mappings=mappings,
            review_items=review_items,
            confidence=average_confidence(
                [field.confidence for field in structured_data.values()]
                + [mapping.confidence for mapping in mappings],
                default=0.0,
            ),
        )
        result = pipeline.assembler.assemble(
            fillable_pdf_path=fillable_path,
            extraction=extraction,
            output_path=Path(request.output_path),
        )
        return {
            "artifact_path": str(Path(request.output_path)),
            "result": _serialize(result),
        }

    # Async job endpoints used by UI and headless automation.
    @app.post("/jobs/analyze-template", response_model=JobResponse)
    async def create_analyze_job(
        template_file: UploadFile | None = File(default=None),
        template_path: str = Form(default=""),
        vision_provider: str = Form(default=""),
    ):
        provider_override = _resolve_provider_override_or_http(vision_provider)
        template_input = await _resolve_job_input_or_http(
            service,
            upload=template_file,
            local_path=template_path,
            upload_name="template",
            spec=InputSpec(role="template PDF", allowed_kinds=("pdf",)),
        )
        job = service.submit_analyze_job(template_input, provider_override=provider_override)
        return _job_response(job)

    @app.post("/jobs/prepare-fillable", response_model=JobResponse)
    async def create_prepare_fillable_job(
        template_file: UploadFile | None = File(default=None),
        template_path: str = Form(default=""),
        vision_provider: str = Form(default=""),
    ):
        provider_override = _resolve_provider_override_or_http(vision_provider)
        template_input = await _resolve_job_input_or_http(
            service,
            upload=template_file,
            local_path=template_path,
            upload_name="template",
            spec=InputSpec(role="template PDF", allowed_kinds=("pdf",)),
        )
        job = service.submit_prepare_fillable_job(template_input, provider_override=provider_override)
        return _job_response(job)

    @app.post("/jobs/extract-data", response_model=JobResponse)
    async def create_extract_job(
        filled_file: UploadFile | None = File(default=None),
        filled_path: str = Form(default=""),
        fillable_file: UploadFile | None = File(default=None),
        fillable_path: str = Form(default=""),
        vision_provider: str = Form(default=""),
    ):
        provider_override = _resolve_provider_override_or_http(vision_provider)
        filled_input = await _resolve_job_input_or_http(
            service,
            upload=filled_file,
            local_path=filled_path,
            upload_name="filled",
            spec=InputSpec(role="filled form", allowed_kinds=("pdf", "image")),
        )
        fillable_input = await _resolve_job_input_or_http(
            service,
            upload=fillable_file,
            local_path=fillable_path,
            upload_name="fillable",
            spec=InputSpec(role="fillable PDF", allowed_kinds=("pdf",)),
        )
        job = service.submit_extract_job(
            filled_input,
            fillable_input,
            provider_override=provider_override,
        )
        return _job_response(job)

    @app.post("/jobs/assemble", response_model=JobResponse)
    async def create_assemble_job(
        fillable_file: UploadFile | None = File(default=None),
        fillable_path: str = Form(default=""),
        extraction_json: UploadFile | None = File(default=None),
        extraction_path: str = Form(default=""),
        vision_provider: str = Form(default=""),
    ):
        provider_override = _resolve_provider_override_or_http(vision_provider)
        fillable_input = await _resolve_job_input_or_http(
            service,
            upload=fillable_file,
            local_path=fillable_path,
            upload_name="fillable",
            spec=InputSpec(role="fillable PDF", allowed_kinds=("pdf",)),
        )
        extraction_input = await _resolve_job_input_or_http(
            service,
            upload=extraction_json,
            local_path=extraction_path,
            upload_name="extraction",
            spec=InputSpec(role="extraction JSON", allowed_kinds=("json",)),
        )
        job = service.submit_assemble_job(
            fillable_input,
            extraction_input,
            provider_override=provider_override,
        )
        return _job_response(job)

    @app.post("/jobs/run-pipeline", response_model=JobResponse)
    async def create_run_pipeline_job(
        template_file: UploadFile | None = File(default=None),
        template_path: str = Form(default=""),
        filled_file: UploadFile | None = File(default=None),
        filled_path: str = Form(default=""),
        vision_provider: str = Form(default=""),
    ):
        provider_override = _resolve_provider_override_or_http(vision_provider)
        template_input = await _resolve_job_input_or_http(
            service,
            upload=template_file,
            local_path=template_path,
            upload_name="template",
            spec=InputSpec(role="template PDF", allowed_kinds=("pdf",)),
        )
        filled_input = await _resolve_job_input_or_http(
            service,
            upload=filled_file,
            local_path=filled_path,
            upload_name="filled",
            spec=InputSpec(role="filled form", allowed_kinds=("pdf", "image")),
        )
        job = service.submit_run_pipeline_job(
            template_input,
            filled_input,
            provider_override=provider_override,
        )
        return _job_response(job)

    @app.get("/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str):
        job = job_store.load_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return _job_response(job)

    @app.get("/jobs/{job_id}/artifacts", response_model=List[ArtifactDescriptor])
    def get_job_artifacts(job_id: str):
        job = job_store.load_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return [_artifact_descriptor(item) for item in job.artifacts]

    @app.get("/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str):
        artifact = job_store.get_artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        if not Path(artifact.path).exists():
            raise HTTPException(status_code=404, detail="Artifact file is no longer available.")
        return FileResponse(
            path=artifact.path,
            media_type=artifact.mime_type,
            filename=Path(artifact.path).name,
        )

    return app


class APIJobService:
    def __init__(
        self,
        *,
        config: FormAIConfig,
        pipeline: FormAIPipeline,
        store: FileJobStore,
        runner: JobRunner,
    ):
        self.config = config
        self.pipeline = pipeline
        self.store = store
        self.runner = runner

    async def resolve_job_input(
        self,
        *,
        upload,
        local_path: str,
        upload_name: str,
        spec: InputSpec,
    ) -> Path:
        if upload is not None:
            raw_bytes = await upload.read()
            validated = _validate_input_bytes(
                raw_bytes,
                filename=upload.filename or upload_name,
                role=spec.role,
                allowed_kinds=spec.allowed_kinds,
                config=self.config,
            )
            suffix = _normalized_suffix(validated["kind"], upload.filename or upload_name)
            temp_path = _job_base_dir(self.config) / "_uploads" / f"{uuid4().hex}_{upload_name}{suffix}"
            ensure_parent_directory(temp_path)
            temp_path.write_bytes(raw_bytes)
            return temp_path
        if local_path:
            path = Path(local_path)
            if not path.exists():
                raise APIInputValidationError(
                    f"Input path does not exist: {path}",
                    code="api.input.missing_path",
                    status_code=404,
                )
            if not path.is_file():
                raise APIInputValidationError(
                    f"Input path must be a file: {path}",
                    code="api.input.not_a_file",
                    status_code=422,
                )
            raw_bytes = path.read_bytes()
            _validate_input_bytes(
                raw_bytes,
                filename=path.name,
                role=spec.role,
                allowed_kinds=spec.allowed_kinds,
                config=self.config,
            )
            return path
        raise APIInputValidationError(
            f"Either upload or local path is required for `{upload_name}`.",
            code="api.input.missing_source",
            status_code=422,
        )

    def submit_analyze_job(self, template_input: Path, *, provider_override: str = "") -> JobRecord:
        job = self._create_job(
            "analyze_template",
            {"template_path": str(template_input)},
            provider_override=provider_override,
        )
        return self.runner.submit(job, self._execute_analyze)

    def submit_prepare_fillable_job(
        self,
        template_input: Path,
        *,
        provider_override: str = "",
    ) -> JobRecord:
        job = self._create_job(
            "prepare_fillable",
            {"template_path": str(template_input)},
            provider_override=provider_override,
        )
        return self.runner.submit(job, self._execute_prepare_fillable)

    def submit_extract_job(
        self,
        filled_input: Path,
        fillable_input: Path,
        *,
        provider_override: str = "",
    ) -> JobRecord:
        job = self._create_job(
            "extract_data",
            {
                "filled_path": str(filled_input),
                "fillable_path": str(fillable_input),
            },
            provider_override=provider_override,
        )
        return self.runner.submit(job, self._execute_extract)

    def submit_assemble_job(
        self,
        fillable_input: Path,
        extraction_input: Path,
        *,
        provider_override: str = "",
    ) -> JobRecord:
        job = self._create_job(
            "assemble",
            {
                "fillable_path": str(fillable_input),
                "extraction_path": str(extraction_input),
            },
            provider_override=provider_override,
        )
        return self.runner.submit(job, self._execute_assemble)

    def submit_run_pipeline_job(
        self,
        template_input: Path,
        filled_input: Path,
        *,
        provider_override: str = "",
    ) -> JobRecord:
        job = self._create_job(
            "run_pipeline",
            {
                "template_path": str(template_input),
                "filled_path": str(filled_input),
            },
            provider_override=provider_override,
        )
        return self.runner.submit(job, self._execute_run_pipeline)

    def _create_job(self, job_type: str, inputs: Dict[str, str], *, provider_override: str = "") -> JobRecord:
        job_inputs = dict(inputs)
        if provider_override:
            job_inputs["vision_provider"] = provider_override
        job = self.store.create_job(job_type, job_inputs)
        job_dir = Path(job.job_dir)
        copied_inputs: Dict[str, str] = {}
        for key, value in inputs.items():
            source = Path(value)
            dest = job_dir / "inputs" / source.name
            copy_or_link_input(source, dest)
            copied_inputs[key] = str(dest)
        return self.store.update_job(job.job_id, lambda current: current.inputs.update(copied_inputs))

    def _execute_analyze(self, job_id: str) -> None:
        self._mark_running(job_id)
        job = self._require_job(job_id)
        template_path = Path(job.inputs["template_path"])
        self.runner.start_step(job_id, "analyze")
        try:
            pipeline = self._pipeline_for_job(job)
            analysis = pipeline.analyze(template_path)
            artifact_path = Path(job.job_dir) / "artifacts" / "analysis.json"
            structure_artifact = Path(job.job_dir) / "artifacts" / "template_structure.json"
            _write_json_artifact(artifact_path, _normalize_analysis(analysis))
            if analysis.template_structure is not None:
                _write_json_artifact(structure_artifact, _serialize(analysis.template_structure))
            self.runner.finish_step(
                job_id,
                "analyze",
                data=_normalize_analysis(analysis),
                issues=[_serialize(issue) for issue in analysis.issues],
                confidence=analysis.confidence,
            )
            self.store.register_artifact(job_id, "analysis", artifact_path, "analyze")
            _register_artifact_if_exists(self.store, job_id, "template_structure", structure_artifact, "analyze")
            self.runner.mark_succeeded(
                job_id,
                issues=[_serialize(issue) for issue in analysis.issues],
                confidence=analysis.confidence,
            )
        except Exception as exc:  # pragma: no cover - integration failure path
            self.runner.mark_failed(job_id, str(exc), issues=[_error_issue_dict("api.analyze.failed", str(exc))])

    def _execute_prepare_fillable(self, job_id: str) -> None:
        self._mark_running(job_id)
        job = self._require_job(job_id)
        template_path = Path(job.inputs["template_path"])
        output_path = Path(job.job_dir) / "outputs" / "fillable.pdf"
        self.runner.start_step(job_id, "analyze")
        try:
            pipeline = self._pipeline_for_job(job)
            analysis, generation = pipeline.prepare_fillable(template_path, output_path)
            analysis_artifact = Path(job.job_dir) / "artifacts" / "analysis.json"
            structure_artifact = Path(job.job_dir) / "artifacts" / "template_structure.json"
            generation_artifact = Path(job.job_dir) / "artifacts" / "generation.json"
            _write_json_artifact(analysis_artifact, _normalize_analysis(analysis))
            if analysis.template_structure is not None:
                _write_json_artifact(structure_artifact, _serialize(analysis.template_structure))
            _write_json_artifact(generation_artifact, _normalize_generation(generation))
            self.runner.finish_step(
                job_id,
                "analyze",
                data=_normalize_analysis(analysis),
                issues=[_serialize(issue) for issue in analysis.issues],
                confidence=analysis.confidence,
            )
            self.store.register_artifact(job_id, "analysis", analysis_artifact, "analyze")
            _register_artifact_if_exists(self.store, job_id, "template_structure", structure_artifact, "analyze")
            self.runner.start_step(job_id, "prepare_fillable")
            self.runner.finish_step(
                job_id,
                "prepare_fillable",
                data=_normalize_generation(generation),
                issues=[_serialize(issue) for issue in generation.issues],
                confidence=generation.confidence,
            )
            self.store.register_artifact(job_id, "fillable_pdf", output_path, "prepare_fillable")
            self.store.register_artifact(job_id, "generation", generation_artifact, "prepare_fillable")
            self.runner.mark_succeeded(
                job_id,
                issues=[_serialize(issue) for issue in analysis.issues + generation.issues],
                confidence=average_confidence([analysis.confidence, generation.confidence], default=0.0),
            )
        except Exception as exc:  # pragma: no cover - integration failure path
            self.runner.mark_failed(job_id, str(exc), issues=[_error_issue_dict("api.prepare_fillable.failed", str(exc))])

    def _execute_extract(self, job_id: str) -> None:
        self._mark_running(job_id)
        job = self._require_job(job_id)
        filled_path = Path(job.inputs["filled_path"])
        fillable_path = Path(job.inputs["fillable_path"])
        self.runner.start_step(job_id, "extract_data")
        try:
            pipeline = self._pipeline_for_job(job)
            extraction = pipeline.extract(filled_path, fillable_path)
            extraction_artifact = Path(job.job_dir) / "artifacts" / "extraction.json"
            transcript_artifact = Path(job.job_dir) / "artifacts" / "filled_transcript.json"
            evidence_artifact = Path(job.job_dir) / "artifacts" / "field_evidence.json"
            _write_json_artifact(extraction_artifact, _normalize_extraction(extraction))
            if extraction.transcript is not None:
                _write_json_artifact(transcript_artifact, _serialize(extraction.transcript))
            if extraction.field_evidence:
                _write_json_artifact(
                    evidence_artifact,
                    {"field_evidence": [_serialize(item) for item in extraction.field_evidence]},
                )
            self.runner.finish_step(
                job_id,
                "extract_data",
                data=_normalize_extraction(extraction),
                issues=[_serialize(issue) for issue in extraction.issues],
                confidence=extraction.confidence,
            )
            self.store.register_artifact(job_id, "extraction", extraction_artifact, "extract_data")
            _register_artifact_if_exists(self.store, job_id, "filled_transcript", transcript_artifact, "extract_data")
            _register_artifact_if_exists(self.store, job_id, "field_evidence", evidence_artifact, "extract_data")
            self.runner.mark_succeeded(
                job_id,
                issues=[_serialize(issue) for issue in extraction.issues],
                review_items=[_serialize(item) for item in extraction.review_items],
                confidence=extraction.confidence,
            )
        except Exception as exc:  # pragma: no cover - integration failure path
            self.runner.mark_failed(job_id, str(exc), issues=[_error_issue_dict("api.extract.failed", str(exc))])

    def _execute_assemble(self, job_id: str) -> None:
        self._mark_running(job_id)
        job = self._require_job(job_id)
        fillable_path = Path(job.inputs["fillable_path"])
        extraction_payload = json.loads(Path(job.inputs["extraction_path"]).read_text(encoding="utf-8"))
        extraction = _extraction_from_api_payload(fillable_path, extraction_payload)
        output_path = Path(job.job_dir) / "outputs" / "final.pdf"
        self.runner.start_step(job_id, "assemble")
        try:
            pipeline = self._pipeline_for_job(job)
            assembly = pipeline.assembler.assemble(
                fillable_pdf_path=fillable_path,
                extraction=extraction,
                output_path=output_path,
            )
            assembly_artifact = Path(job.job_dir) / "artifacts" / "assembly.json"
            render_plan_artifact = Path(job.job_dir) / "artifacts" / "render_plan.json"
            verification_artifact = Path(job.job_dir) / "artifacts" / "verification.json"
            _write_json_artifact(assembly_artifact, _normalize_assembly(assembly))
            if assembly.render_plan:
                _write_json_artifact(
                    render_plan_artifact,
                    {
                        "render_plan_summary": dict(assembly.render_plan_summary),
                        "items": [_serialize(item) for item in assembly.render_plan],
                    },
                )
            if assembly.self_check is not None:
                _write_json_artifact(verification_artifact, _serialize(assembly.self_check))
            self.runner.finish_step(
                job_id,
                "assemble",
                data=_normalize_assembly(assembly),
                issues=[_serialize(issue) for issue in assembly.issues],
                confidence=assembly.confidence,
            )
            _register_artifact_if_exists(self.store, job_id, "final_pdf", output_path, "assemble")
            self.store.register_artifact(job_id, "assembly", assembly_artifact, "assemble")
            _register_artifact_if_exists(self.store, job_id, "render_plan", render_plan_artifact, "assemble")
            _register_artifact_if_exists(self.store, job_id, "verification", verification_artifact, "assemble")
            self.runner.mark_succeeded(
                job_id,
                issues=[_serialize(issue) for issue in assembly.issues],
                review_items=[_serialize(item) for item in extraction.review_items],
                confidence=assembly.confidence,
            )
        except Exception as exc:  # pragma: no cover - integration failure path
            self.runner.mark_failed(job_id, str(exc), issues=[_error_issue_dict("api.assemble.failed", str(exc))])

    def _execute_run_pipeline(self, job_id: str) -> None:
        self._mark_running(job_id)
        job = self._require_job(job_id)
        template_path = Path(job.inputs["template_path"])
        filled_path = Path(job.inputs["filled_path"])
        fillable_output = Path(job.job_dir) / "outputs" / "fillable.pdf"
        final_output = Path(job.job_dir) / "outputs" / "final.pdf"
        try:
            pipeline = self._pipeline_for_job(job)
            self.runner.start_step(job_id, "analyze")
            analysis, generation = pipeline.prepare_fillable(template_path, fillable_output)
            analysis_artifact = Path(job.job_dir) / "artifacts" / "analysis.json"
            structure_artifact = Path(job.job_dir) / "artifacts" / "template_structure.json"
            generation_artifact = Path(job.job_dir) / "artifacts" / "generation.json"
            _write_json_artifact(analysis_artifact, _normalize_analysis(analysis))
            if analysis.template_structure is not None:
                _write_json_artifact(structure_artifact, _serialize(analysis.template_structure))
            _write_json_artifact(generation_artifact, _normalize_generation(generation))
            self.runner.finish_step(
                job_id,
                "analyze",
                data=_normalize_analysis(analysis),
                issues=[_serialize(issue) for issue in analysis.issues],
                confidence=analysis.confidence,
            )
            self.store.register_artifact(job_id, "analysis", analysis_artifact, "analyze")
            _register_artifact_if_exists(self.store, job_id, "template_structure", structure_artifact, "analyze")

            self.runner.start_step(job_id, "prepare_fillable")
            self.runner.finish_step(
                job_id,
                "prepare_fillable",
                data=_normalize_generation(generation),
                issues=[_serialize(issue) for issue in generation.issues],
                confidence=generation.confidence,
            )
            self.store.register_artifact(job_id, "fillable_pdf", fillable_output, "prepare_fillable")
            self.store.register_artifact(job_id, "generation", generation_artifact, "prepare_fillable")

            self.runner.start_step(job_id, "extract_data")
            extraction = pipeline.extract(filled_path, fillable_output)
            extraction_artifact = Path(job.job_dir) / "artifacts" / "extraction.json"
            transcript_artifact = Path(job.job_dir) / "artifacts" / "filled_transcript.json"
            evidence_artifact = Path(job.job_dir) / "artifacts" / "field_evidence.json"
            _write_json_artifact(extraction_artifact, _normalize_extraction(extraction))
            if extraction.transcript is not None:
                _write_json_artifact(transcript_artifact, _serialize(extraction.transcript))
            if extraction.field_evidence:
                _write_json_artifact(
                    evidence_artifact,
                    {"field_evidence": [_serialize(item) for item in extraction.field_evidence]},
                )
            self.runner.finish_step(
                job_id,
                "extract_data",
                data=_normalize_extraction(extraction),
                issues=[_serialize(issue) for issue in extraction.issues],
                confidence=extraction.confidence,
            )
            self.store.register_artifact(job_id, "extraction", extraction_artifact, "extract_data")
            _register_artifact_if_exists(self.store, job_id, "filled_transcript", transcript_artifact, "extract_data")
            _register_artifact_if_exists(self.store, job_id, "field_evidence", evidence_artifact, "extract_data")

            self.runner.start_step(job_id, "assemble")
            assembly = pipeline.assembler.assemble(fillable_output, extraction, final_output)
            assembly_artifact = Path(job.job_dir) / "artifacts" / "assembly.json"
            render_plan_artifact = Path(job.job_dir) / "artifacts" / "render_plan.json"
            verification_artifact = Path(job.job_dir) / "artifacts" / "verification.json"
            _write_json_artifact(assembly_artifact, _normalize_assembly(assembly))
            if assembly.render_plan:
                _write_json_artifact(
                    render_plan_artifact,
                    {
                        "render_plan_summary": dict(assembly.render_plan_summary),
                        "items": [_serialize(item) for item in assembly.render_plan],
                    },
                )
            if assembly.self_check is not None:
                _write_json_artifact(verification_artifact, _serialize(assembly.self_check))
            self.runner.finish_step(
                job_id,
                "assemble",
                data=_normalize_assembly(assembly),
                issues=[_serialize(issue) for issue in assembly.issues],
                confidence=assembly.confidence,
            )
            _register_artifact_if_exists(self.store, job_id, "final_pdf", final_output, "assemble")
            self.store.register_artifact(job_id, "assembly", assembly_artifact, "assemble")
            _register_artifact_if_exists(self.store, job_id, "render_plan", render_plan_artifact, "assemble")
            _register_artifact_if_exists(self.store, job_id, "verification", verification_artifact, "assemble")

            issues = [
                _serialize(issue)
                for issue in analysis.issues + generation.issues + extraction.issues + assembly.issues
            ]
            self.runner.mark_succeeded(
                job_id,
                issues=issues,
                review_items=[_serialize(item) for item in extraction.review_items],
                confidence=average_confidence(
                    [
                        analysis.confidence,
                        generation.confidence,
                        extraction.confidence,
                        assembly.confidence,
                    ],
                    default=0.0,
                ),
            )
        except Exception as exc:  # pragma: no cover - integration failure path
            self.runner.mark_failed(job_id, str(exc), issues=[_error_issue_dict("api.run_pipeline.failed", str(exc))])

    def _mark_running(self, job_id: str) -> None:
        self.runner.mark_running(job_id)

    def _require_job(self, job_id: str) -> JobRecord:
        job = self.store.load_job(job_id)
        if job is None:
            raise FileNotFoundError(f"Job not found: {job_id}")
        return job

    def _pipeline_for_job(self, job: JobRecord) -> FormAIPipeline:
        provider = (job.inputs.get("vision_provider") or "").strip().lower()
        if not provider or provider == (self.config.vision_provider or "").strip().lower():
            return self.pipeline
        job_config = replace(self.config, vision_provider=provider)
        return build_default_pipeline(job_config)


def _job_base_dir(config: FormAIConfig) -> Path:
    if config.api_jobs_dir:
        return Path(config.api_jobs_dir)
    return config.working_dir / "tmp" / "api_jobs"


def _allowed_origins(config: FormAIConfig) -> list[str]:
    return [origin.strip() for origin in (config.api_allowed_origins or "").split(",") if origin.strip()]


def _write_optional_artifact(path: str, payload) -> str:
    if not path:
        return ""
    artifact_path = Path(path)
    ensure_parent_directory(artifact_path)
    artifact_path.write_text(
        json.dumps(_serialize(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return str(artifact_path)


def _write_json_artifact(path: Path, payload: dict) -> None:
    ensure_parent_directory(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _register_artifact_if_exists(
    store: FileJobStore,
    job_id: str,
    kind: str,
    path: Path,
    step_name: str,
) -> None:
    if path.exists():
        store.register_artifact(job_id, kind, path, step_name)


def _resolve_provider_override_or_http(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    if not normalized:
        return ""
    if normalized not in SUPPORTED_VISION_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "api.input.invalid_provider",
                "message": (
                    f"Unsupported OCR provider `{normalized}`. "
                    f"Supported providers: {', '.join(SUPPORTED_VISION_PROVIDERS)}."
                ),
            },
        )
    return normalized


async def _resolve_job_input_or_http(
    service: APIJobService,
    *,
    upload,
    local_path: str,
    upload_name: str,
    spec: InputSpec,
) -> Path:
    try:
        return await service.resolve_job_input(
            upload=upload,
            local_path=local_path,
            upload_name=upload_name,
            spec=spec,
        )
    except APIInputValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


def _validate_input_bytes(
    data: bytes,
    *,
    filename: str,
    role: str,
    allowed_kinds: tuple[str, ...],
    config: FormAIConfig,
) -> dict:
    if not data:
        raise APIInputValidationError(
            f"{role} is empty.",
            code="api.input.empty_file",
            status_code=422,
        )
    if len(data) > config.api_max_upload_bytes:
        raise APIInputValidationError(
            f"{role} exceeds the upload size limit of {config.api_max_upload_bytes} bytes.",
            code="api.input.file_too_large",
            status_code=413,
        )

    kind = _sniff_input_kind(data)
    if not kind:
        raise APIInputValidationError(
            f"{role} is not a supported PDF, image, or JSON file.",
            code="api.input.unsupported_type",
            status_code=415,
        )
    if kind not in allowed_kinds:
        allowed = ", ".join(allowed_kinds)
        raise APIInputValidationError(
            f"{role} must be one of: {allowed}. Uploaded content looks like `{kind}`.",
            code="api.input.unexpected_type",
            status_code=415,
        )

    if kind == "pdf":
        _validate_pdf_bytes(data, role)
    elif kind == "image":
        _validate_image_bytes(data, role, config)
    elif kind == "json":
        _validate_json_bytes(data, role)

    return {"kind": kind, "filename": filename}


def _sniff_input_kind(data: bytes) -> str:
    stripped = data.lstrip()
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if data.startswith(b"\xff\xd8\xff"):
        return "image"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image"
    if stripped[:1] in (b"{", b"["):
        return "json"
    return ""


def _validate_pdf_bytes(data: bytes, role: str) -> None:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        return

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise APIInputValidationError(
            f"{role} is not a readable PDF: {exc}",
            code="api.input.invalid_pdf",
            status_code=422,
        ) from exc

    if getattr(reader, "is_encrypted", False):
        raise APIInputValidationError(
            f"{role} is password protected and cannot be processed.",
            code="api.input.encrypted_pdf",
            status_code=422,
        )
    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise APIInputValidationError(
            f"{role} PDF pages could not be read: {exc}",
            code="api.input.invalid_pdf",
            status_code=422,
        ) from exc
    if page_count < 1:
        raise APIInputValidationError(
            f"{role} does not contain any readable PDF pages.",
            code="api.input.empty_pdf",
            status_code=422,
        )


def _validate_image_bytes(data: bytes, role: str, config: FormAIConfig) -> None:
    try:
        from PIL import Image, ImageFile, UnidentifiedImageError
    except ImportError:  # pragma: no cover
        return

    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise APIInputValidationError(
            f"{role} is not a readable raster image: {exc}",
            code="api.input.invalid_image",
            status_code=422,
        ) from exc

    if width <= 0 or height <= 0:
        raise APIInputValidationError(
            f"{role} has invalid image dimensions.",
            code="api.input.invalid_image",
            status_code=422,
        )
    if width * height > config.api_max_image_pixels:
        raise APIInputValidationError(
            f"{role} is too large to process safely ({width}x{height}px).",
            code="api.input.image_too_large",
            status_code=413,
        )


def _validate_json_bytes(data: bytes, role: str) -> None:
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise APIInputValidationError(
            f"{role} is not valid UTF-8 JSON: {exc}",
            code="api.input.invalid_json",
            status_code=422,
        ) from exc
    if not isinstance(payload, dict):
        raise APIInputValidationError(
            f"{role} must contain a JSON object.",
            code="api.input.invalid_json_shape",
            status_code=422,
        )


def _normalized_suffix(kind: str, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if kind == "pdf":
        return ".pdf"
    if kind == "json":
        return ".json"
    if kind == "image" and suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}:
        return suffix
    if kind == "image":
        return ".png"
    return suffix or ".bin"


def _coerce_structured_data(payload: Dict[str, str | object]) -> Dict[str, FieldValue]:
    structured_data: Dict[str, FieldValue] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            structured_data[key] = FieldValue(
                value=value,
                confidence=derive_field_confidence("api_input", value),
                source_key=key,
                raw_text=value,
                source_kind="api_input",
            )
            continue
        if hasattr(value, "model_dump"):
            item = value.model_dump()
        else:
            item = dict(value)
        field_value = str(item.get("value", ""))
        structured_data[key] = FieldValue(
            value=field_value,
            confidence=float(
                item.get("confidence")
                if item.get("confidence") is not None
                else derive_field_confidence(
                    str(item.get("source_kind", "api_input")),
                    field_value,
                    item.get("review_reasons", []),
                )
            ),
            source_key=key,
            raw_text=str(item.get("raw_text", field_value)),
            source_kind=str(item.get("source_kind", "api_input")),
            review_reasons=list(item.get("review_reasons", [])),
        )
    return structured_data


def _coerce_mappings(items) -> List[FieldMapping]:
    mappings: List[FieldMapping] = []
    for item in items:
        payload = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        mappings.append(
            FieldMapping(
                source_key=payload["source_key"],
                target_field=payload["target_field"],
                confidence=float(payload["confidence"]),
                status=payload["status"],
                notes=str(payload.get("notes", "")),
            )
        )
    return mappings


def _derive_mappings(
    structured_data: Dict[str, FieldValue],
    fillable_path: Path,
    config: FormAIConfig,
) -> List[FieldMapping]:
    target_fields = inspect_pdf_fields(fillable_path)
    return map_extracted_values_to_fields(
        structured_data,
        target_fields,
        config.min_mapping_confidence,
    )


def _normalize_analysis(result) -> dict:
    payload = _serialize(result)
    payload["existing_field_count"] = len(payload.get("existing_fields", []))
    payload["detected_field_count"] = len(payload.get("detected_fields", []))
    payload["template_structure_summary"] = dict(getattr(result, "template_structure_summary", {}) or {})
    return payload


def _normalize_generation(result) -> dict:
    payload = _serialize(result)
    payload["acro_field_count"] = len(payload.get("acro_fields", []))
    return payload


def _normalize_extraction(result: ExtractionResult) -> dict:
    mapping_by_source = {mapping.source_key: mapping for mapping in result.mappings}
    fields = []
    for key, value in sorted(result.structured_data.items()):
        mapping = mapping_by_source.get(key)
        fields.append(
            {
                "key": key,
                "value": value.value,
                "confidence": value.confidence,
                "raw_text": value.raw_text,
                "source_kind": value.source_kind,
                "review_reasons": list(value.review_reasons),
                "mapped_target": mapping.target_field if mapping else "",
            }
        )
    return {
        "source_path": str(result.source_path),
        "fields": fields,
        "transcript_summary": dict(result.transcript_summary),
        "transcript": _serialize(result.transcript) if result.transcript is not None else None,
        "field_evidence": [_serialize(item) for item in result.field_evidence],
        "mappings": [_serialize(item) for item in result.mappings],
        "review_items": [_serialize(item) for item in result.review_items],
        "issues": [_serialize(item) for item in result.issues],
        "confidence": result.confidence,
    }


def _normalize_assembly(result) -> dict:
    return {
        "output_path": str(result.output_path),
        "filled_values": dict(result.filled_values),
        "render_plan_summary": dict(getattr(result, "render_plan_summary", {}) or {}),
        "render_plan": [_serialize(item) for item in getattr(result, "render_plan", [])],
        "self_check": _serialize(result.self_check) if getattr(result, "self_check", None) is not None else None,
        "issues": [_serialize(item) for item in result.issues],
        "confidence": result.confidence,
    }


def _extraction_from_api_payload(fillable_path: Path, payload: dict) -> ExtractionResult:
    fields_payload = payload.get("fields", [])
    if isinstance(fields_payload, dict):
        structured_data = _coerce_structured_data(fields_payload)
    else:
        structured_data = {
            str(item["key"]): FieldValue(
                value=str(item.get("value", "")),
                confidence=float(item.get("confidence", 0.0)),
                source_key=str(item["key"]),
                raw_text=str(item.get("raw_text", item.get("value", ""))),
                source_kind=str(item.get("source_kind", "api_input")),
                review_reasons=list(item.get("review_reasons", [])),
            )
            for item in fields_payload
        }
    mappings = _coerce_mappings(payload.get("mappings", []))
    review_items = [ReviewItem(**item) for item in payload.get("review_items", [])]
    return ExtractionResult(
        source_path=fillable_path,
        structured_data=structured_data,
        mappings=mappings,
        review_items=review_items,
        confidence=float(payload.get("confidence", 0.0)),
    )


def _artifact_descriptor(item) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        artifact_id=item.artifact_id,
        kind=item.kind,
        path=item.path,
        mime_type=item.mime_type,
        size_bytes=item.size_bytes,
        step_name=item.step_name,
        created_at=item.created_at,
        download_url=f"/artifacts/{item.artifact_id}",
    )


def _job_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        job_type=job.job_type,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        step_results=[StepResultPayload(**item.to_dict()) for item in job.step_results],
        artifacts=[_artifact_descriptor(item) for item in job.artifacts],
        issues=list(job.issues),
        review_items=list(job.review_items),
        confidence=job.confidence,
        error_message=job.error_message,
    )


def _error_issue_dict(code: str, message: str) -> dict:
    return {"code": code, "message": message, "severity": "error", "context": {}}


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
