from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import urlopen

from formai.agents.acroform_generator import AcroFormGeneratorAgent
from formai.agents.data_extractor import DataExtractorAgent
from formai.agents.final_assembler import FinalAssemblerAgent
from formai.agents.input_evaluator import InputEvaluatorAgent
from formai.config import FormAIConfig
from formai.errors import IntegrationUnavailable
from formai.llm.base import NullVisionLLMClient, VisionLLMClient
from formai.llm.chandra_perception import ChandraPerceptionClient
from formai.llm.glm_ocr import GLMOCRVisionClient
from formai.llm.ollama_vision import OllamaVisionClient
from formai.llm.openai_vision import OpenAIVisionClient
from formai.llm.turkish_gemma_resolver import TurkishGemmaResolverClient
from formai.models import PipelineResult
from formai.pdf.inspector import inspect_pdf_fields
from formai.pdf.commonforms_adapter import CommonFormsAdapter
from formai.node_context import NodeContext
from formai.perception.surya_layout import SuryaLayoutEngine
from formai.runner import FormAIRunner

ROLE_MODEL_ALIASES = {
    "qwen25_vl": "qwen2.5vl:3b",
    "qwen2.5_vl": "qwen2.5vl:3b",
    "qwen2.5-vl": "qwen2.5vl:3b",
    "qwen2.5vl": "qwen2.5vl:3b",
    "gemma3": "gemma3:12b",
    "gemma_3": "gemma3:12b",
    "gemma-3": "gemma3:12b",
}

LOW_MEMORY_OLLAMA_MODEL_FALLBACKS = {
    "qwen2.5vl:3b": "glm-ocr",
    "gemma3:12b": "gemma3:4b",
}


class FormAIPipeline:
    def __init__(
        self,
        evaluator: InputEvaluatorAgent,
        generator: AcroFormGeneratorAgent,
        extractor: DataExtractorAgent,
        assembler: FinalAssemblerAgent,
        runner: FormAIRunner | None = None,
    ):
        self.evaluator = evaluator
        self.generator = generator
        self.extractor = extractor
        self.assembler = assembler
        self.runner = runner

    def run(
        self,
        template_pdf: Path,
        filled_pdf: Path,
        fillable_output: Path,
        final_output: Path,
    ) -> PipelineResult:
        if self.runner is not None and self.runner.config.runner_backend != "legacy":
            return self.runner.run(
                template_pdf=template_pdf,
                filled_pdf=filled_pdf,
                fillable_output=fillable_output,
                final_output=final_output,
            )
        analysis = self.evaluator.evaluate(template_pdf)
        generation = self.generator.generate(template_pdf, analysis, fillable_output)
        extraction = self.extractor.extract(filled_pdf, generation.acro_fields)
        assembly = self.assembler.assemble(
            generation.output_path,
            extraction,
            final_output,
            source_reference=filled_pdf,
        )
        return PipelineResult(
            analysis=analysis,
            generation=generation,
            extraction=extraction,
            assembly=assembly,
        )

    def analyze(self, template_pdf: Path):
        if self.runner is not None and self.runner.config.runner_backend != "legacy":
            return self.runner.analyze(template_pdf)[0]
        return self.evaluator.evaluate(template_pdf)

    def prepare_fillable(self, template_pdf: Path, output_path: Path):
        if self.runner is not None and self.runner.config.runner_backend != "legacy":
            prepared = self.runner.prepare_fillable(template_pdf, output_path)
            return prepared["analysis"], prepared["generation"]
        analysis = self.evaluator.evaluate(template_pdf)
        return analysis, self.generator.generate(template_pdf, analysis, output_path)

    def extract(self, filled_pdf: Path, fillable_pdf: Path):
        target_fields = inspect_pdf_fields(fillable_pdf)
        if self.runner is not None and self.runner.config.runner_backend != "legacy":
            return self.runner.extract(filled_pdf, target_fields)["extraction"]
        return self.extractor.extract(filled_pdf, target_fields)


def build_default_pipeline(config: Optional[FormAIConfig] = None) -> FormAIPipeline:
    config = config or FormAIConfig.from_env(Path.cwd())
    intake_client = build_intake_client(config)
    template_detector = build_template_detector_client(config)
    perception_client = build_document_perception_client(config)
    resolver_client = build_schema_resolver_client(config)
    adjudicator_client = build_region_adjudicator_client(config)
    verification_client = build_verification_client(config)
    visual_review_client = build_visual_review_client(config)
    layout_engine = build_layout_engine(config)

    commonforms_adapter = CommonFormsAdapter(
        model_or_path=config.commonforms_model,
        device="cpu",
        fast=config.commonforms_fast,
        confidence=config.commonforms_confidence,
        multiline=config.commonforms_multiline,
    )
    return FormAIPipeline(
        evaluator=InputEvaluatorAgent(config, template_detector),
        generator=AcroFormGeneratorAgent(config, commonforms_adapter),
        extractor=DataExtractorAgent(
            config,
            resolver_client,
            ocr_reader=None,
            perception_client=perception_client,
            resolver_client=resolver_client,
        ),
        assembler=FinalAssemblerAgent(
            config,
            llm_client=verification_client or visual_review_client,
            perception_client=perception_client,
        ),
        runner=FormAIRunner(
            config=config,
            evaluator=InputEvaluatorAgent(config, template_detector),
            generator=AcroFormGeneratorAgent(config, commonforms_adapter),
            extractor=DataExtractorAgent(
                config,
                resolver_client,
                ocr_reader=None,
                perception_client=perception_client,
                resolver_client=resolver_client,
            ),
            assembler=FinalAssemblerAgent(
                config,
                llm_client=verification_client or visual_review_client,
                perception_client=perception_client,
            ),
            layout_engine=layout_engine,
            context=NodeContext(
                config=config,
                working_dir=config.working_dir,
                intake_client=intake_client,
                template_client=template_detector,
                perception_client=perception_client,
                resolver_client=resolver_client,
                adjudicator_client=adjudicator_client,
                verification_client=verification_client or visual_review_client,
            ),
        ),
    )


def build_layout_engine(config: FormAIConfig):
    backend = (config.layout_backend or "surya").strip().lower()
    if backend in {"", "surya", "auto"}:
        return SuryaLayoutEngine(enabled=True)
    return SuryaLayoutEngine(enabled=False)


def build_intake_client(config: FormAIConfig) -> VisionLLMClient:
    backend = (config.intake_backend or "auto").strip().lower()
    if backend in {"", "auto"}:
        return build_vision_client(config)
    return build_vision_client(_replace_role_backend(config, backend))


def build_template_detector_client(config: FormAIConfig) -> VisionLLMClient:
    return build_vision_client(config)


def build_document_perception_client(config: FormAIConfig) -> VisionLLMClient:
    backend = (config.perception_backend or "auto").strip().lower()
    if backend in {"", "auto"}:
        backend = "chandra" if _chandra_is_available() else (config.vision_provider or "auto")
    if backend == "chandra":
        return ChandraPerceptionClient(
            model=config.chandra_model,
            method=config.chandra_method,
        )
    return build_vision_client(_replace_role_backend(config, backend))


def build_schema_resolver_client(config: FormAIConfig) -> VisionLLMClient:
    backend = (config.resolver_backend or "auto").strip().lower()
    if backend in {"", "auto"}:
        return build_vision_client(config)
    if backend in {"turkish_gemma", "turkish-gemma", "turkish_gemma_9b_t1"}:
        return TurkishGemmaResolverClient(
            model=config.turkish_gemma_model,
            device_map=config.turkish_gemma_device_map,
            max_new_tokens=config.turkish_gemma_max_new_tokens,
        )
    return build_vision_client(_replace_role_backend(config, backend))


def build_visual_review_client(config: FormAIConfig) -> VisionLLMClient:
    backend = (config.visual_reviewer_backend or "auto").strip().lower()
    if backend in {"", "auto"}:
        return build_vision_client(config)
    return build_vision_client(_replace_role_backend(config, backend))


def build_region_adjudicator_client(config: FormAIConfig) -> VisionLLMClient:
    backend = (config.region_adjudicator_backend or "auto").strip().lower()
    if backend in {"", "auto"}:
        return build_vision_client(config)
    return build_vision_client(_replace_role_backend(config, backend))


def build_verification_client(config: FormAIConfig) -> VisionLLMClient:
    backend = (config.verification_backend or "auto").strip().lower()
    if backend in {"", "auto"}:
        return build_visual_review_client(config)
    return build_vision_client(_replace_role_backend(config, backend))


def build_vision_client(config: FormAIConfig) -> VisionLLMClient:
    provider = (config.vision_provider or "auto").strip().lower()
    if provider in {"", "auto"}:
        if _ollama_is_available(config):
            provider = "ollama"
        elif config.openai_api_key:
            provider = "openai"
        else:
            provider = "none"
    if provider == "glm_ocr":
        return GLMOCRVisionClient(
            model=config.glm_ocr_model,
            device_map=config.glm_ocr_device_map,
            max_new_tokens=config.glm_ocr_max_new_tokens,
        )
    if provider == "ollama":
        return OllamaVisionClient(
            model=config.ollama_model,
            fallback_model=config.ollama_fallback_model,
            base_url=config.ollama_base_url,
            timeout_seconds=config.ollama_timeout_seconds,
        )
    if provider == "openai":
        if config.openai_api_key:
            return OpenAIVisionClient(
                api_key=config.openai_api_key,
                model=config.openai_model,
            )
        return NullVisionLLMClient()
    if provider in {"none", "disabled", "off"}:
        return NullVisionLLMClient()
    raise IntegrationUnavailable(
        f"Unsupported vision provider: {provider}. Supported providers: auto, openai, glm_ocr, ollama."
    )


def build_crop_ocr_reader(config: FormAIConfig):
    return None


def _ollama_is_available(config: FormAIConfig) -> bool:
    try:
        with urlopen(f"{config.ollama_base_url.rstrip('/')}/api/tags", timeout=1.2) as response:
            return int(getattr(response, "status", 200)) < 500
    except (URLError, ValueError):
        return False


def _chandra_is_available() -> bool:
    try:
        from chandra.model import InferenceManager  # noqa: F401
    except Exception:
        return False
    return True


def _replace_provider(config: FormAIConfig, provider: str) -> FormAIConfig:
    return FormAIConfig(
        **{
            **config.__dict__,
            "vision_provider": provider,
        }
    )


def _replace_role_backend(config: FormAIConfig, backend: str) -> FormAIConfig:
    if backend == "chandra":
        return config
    if backend in {"openai", "ollama", "glm_ocr", "glm-ocr"}:
        return _replace_provider(config, backend.replace("-", "_"))
    resolved_backend = ROLE_MODEL_ALIASES.get(backend, backend)
    payload = {**config.__dict__}
    provider = (config.vision_provider or "auto").strip().lower()
    if provider in {"", "auto", "ollama"}:
        payload["vision_provider"] = "ollama"
        fallback_model = config.ollama_fallback_model or config.ollama_model
        if _ollama_model_is_likely_unsupported_locally(resolved_backend):
            payload["ollama_model"] = LOW_MEMORY_OLLAMA_MODEL_FALLBACKS.get(
                resolved_backend,
                fallback_model,
            ) or fallback_model
            payload["ollama_fallback_model"] = ""
        else:
            payload["ollama_fallback_model"] = fallback_model
            payload["ollama_model"] = resolved_backend
    elif provider == "openai":
        payload["openai_model"] = resolved_backend
    else:
        payload["ollama_model"] = resolved_backend
    return FormAIConfig(**payload)


def _ollama_model_is_likely_unsupported_locally(model: str) -> bool:
    normalized = model.strip().lower()
    if normalized not in LOW_MEMORY_OLLAMA_MODEL_FALLBACKS:
        return False
    return _is_low_memory_apple_silicon()


def _is_low_memory_apple_silicon() -> bool:
    if platform.system().lower() != "darwin":
        return False
    machine = platform.machine().lower()
    if machine not in {"arm64", "aarch64"}:
        return False
    total_gb = _total_memory_gb()
    return total_gb > 0 and total_gb <= 24


def _total_memory_gb() -> int:
    try:
        output = subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"],
            text=True,
        ).strip()
        bytes_total = int(output)
        return int(round(bytes_total / (1024 ** 3)))
    except Exception:
        return 0
