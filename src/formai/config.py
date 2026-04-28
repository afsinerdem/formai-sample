from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FormAIConfig:
    working_dir: Path
    runner_backend: str = "hamilton"
    vision_provider: str = "auto"
    intake_backend: str = "qwen25_vl"
    layout_backend: str = "auto"
    perception_backend: str = "auto"
    resolver_backend: str = "auto"
    region_adjudicator_backend: str = "qwen25_vl"
    verification_backend: str = "qwen25_vl"
    visual_reviewer_backend: str = "auto"
    font_family: str = "noto_sans"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    chandra_model: str = "datalab-to/chandra-ocr-2"
    chandra_method: str = "hf"
    turkish_gemma_model: str = "ytu-ce-cosmos/Turkish-Gemma-9b-T1"
    turkish_gemma_device_map: str = "auto"
    turkish_gemma_max_new_tokens: int = 768
    glm_ocr_model: str = "zai-org/GLM-OCR"
    glm_ocr_device_map: str = "auto"
    glm_ocr_max_new_tokens: int = 1024
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "glm-ocr"
    ollama_fallback_model: str = ""
    ollama_timeout_seconds: int = 300
    overflow_strategy: str = "same_page_note"
    fir_dataset_dir: str = ""
    turkish_printed_dataset_dir: str = ""
    turkish_handwritten_dataset_dir: str = ""
    turkish_petitions_dataset_dir: str = ""
    validation_template_path: str = ""
    validation_fillable_template_path: str = ""
    validation_real_demo_manual_pass: bool = False
    api_jobs_dir: str = ""
    api_allowed_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    api_max_upload_bytes: int = 25 * 1024 * 1024
    api_max_image_pixels: int = 25_000_000
    raster_dpi: int = 180
    max_multiline_segment_crops: int = 2
    region_read_concurrency: int = 6
    enable_chandra_region_reads: bool = True
    enable_secondary_chandra_verify: bool = True
    min_mapping_confidence: float = 0.55
    min_field_detection_confidence: float = 0.50
    max_issue_count: int = 50
    enable_output_self_check: bool = True
    strict_verification_gate: bool = False
    self_check_min_source_similarity: float = 0.42
    self_check_min_output_similarity: float = 0.58
    commonforms_model: str = "FFDNet-L"
    commonforms_fast: bool = True
    commonforms_confidence: float = 0.6
    commonforms_multiline: bool = True

    @classmethod
    def from_env(cls, working_dir: Path) -> "FormAIConfig":
        return cls(
            working_dir=working_dir,
            runner_backend=os.getenv("FORMAI_RUNNER_BACKEND", "hamilton"),
            vision_provider=os.getenv("FORMAI_VISION_PROVIDER", "auto"),
            intake_backend=os.getenv("FORMAI_INTAKE_BACKEND", "qwen25_vl"),
            layout_backend=os.getenv("FORMAI_LAYOUT_BACKEND", "auto"),
            perception_backend=os.getenv("FORMAI_PERCEPTION_BACKEND", "auto"),
            resolver_backend=os.getenv("FORMAI_RESOLVER_BACKEND", "auto"),
            region_adjudicator_backend=os.getenv(
                "FORMAI_REGION_ADJUDICATOR_BACKEND",
                "qwen25_vl",
            ),
            verification_backend=os.getenv("FORMAI_VERIFICATION_BACKEND", "qwen25_vl"),
            visual_reviewer_backend=os.getenv("FORMAI_VISUAL_REVIEWER_BACKEND", "auto"),
            font_family=os.getenv("FORMAI_FONT_FAMILY", "noto_sans"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("FORMAI_OPENAI_MODEL", "gpt-4.1-mini"),
            chandra_model=os.getenv("FORMAI_CHANDRA_MODEL", "datalab-to/chandra-ocr-2"),
            chandra_method=os.getenv("FORMAI_CHANDRA_METHOD", "hf"),
            turkish_gemma_model=os.getenv(
                "FORMAI_TURKISH_GEMMA_MODEL",
                "ytu-ce-cosmos/Turkish-Gemma-9b-T1",
            ),
            turkish_gemma_device_map=os.getenv(
                "FORMAI_TURKISH_GEMMA_DEVICE_MAP",
                "auto",
            ),
            turkish_gemma_max_new_tokens=int(
                os.getenv("FORMAI_TURKISH_GEMMA_MAX_NEW_TOKENS", "768")
            ),
            glm_ocr_model=os.getenv("FORMAI_GLM_OCR_MODEL", "zai-org/GLM-OCR"),
            glm_ocr_device_map=os.getenv("FORMAI_GLM_OCR_DEVICE_MAP", "auto"),
            glm_ocr_max_new_tokens=int(os.getenv("FORMAI_GLM_OCR_MAX_NEW_TOKENS", "1024")),
            ollama_base_url=os.getenv("FORMAI_OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=os.getenv("FORMAI_OLLAMA_MODEL", "glm-ocr"),
            ollama_fallback_model=os.getenv("FORMAI_OLLAMA_FALLBACK_MODEL", ""),
            ollama_timeout_seconds=int(os.getenv("FORMAI_OLLAMA_TIMEOUT_SECONDS", "300")),
            overflow_strategy=os.getenv("FORMAI_OVERFLOW_STRATEGY", "same_page_note"),
            fir_dataset_dir=os.getenv("FORMAI_FIR_DATASET_DIR", ""),
            turkish_printed_dataset_dir=os.getenv("FORMAI_TURKISH_PRINTED_DATASET_DIR", ""),
            turkish_handwritten_dataset_dir=os.getenv(
                "FORMAI_TURKISH_HANDWRITTEN_DATASET_DIR",
                "",
            ),
            turkish_petitions_dataset_dir=os.getenv(
                "FORMAI_TURKISH_PETITIONS_DATASET_DIR",
                "",
            ),
            validation_template_path=os.getenv("FORMAI_VALIDATION_TEMPLATE_PATH", ""),
            validation_fillable_template_path=os.getenv(
                "FORMAI_VALIDATION_FILLABLE_TEMPLATE_PATH", ""
            ),
            validation_real_demo_manual_pass=os.getenv(
                "FORMAI_VALIDATION_REAL_DEMO_MANUAL_PASS",
                "false",
            ).lower()
            in {"1", "true", "yes"},
            api_jobs_dir=os.getenv("FORMAI_API_JOBS_DIR", ""),
            api_allowed_origins=os.getenv(
                "FORMAI_API_ALLOWED_ORIGINS",
                "http://127.0.0.1:3000,http://localhost:3000",
            ),
            api_max_upload_bytes=int(
                os.getenv("FORMAI_API_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
            ),
            api_max_image_pixels=int(
                os.getenv("FORMAI_API_MAX_IMAGE_PIXELS", "25000000")
            ),
            raster_dpi=int(os.getenv("FORMAI_RASTER_DPI", "180")),
            max_multiline_segment_crops=int(
                os.getenv("FORMAI_MAX_MULTILINE_SEGMENT_CROPS", "2")
            ),
            region_read_concurrency=int(
                os.getenv("FORMAI_REGION_READ_CONCURRENCY", "6")
            ),
            enable_chandra_region_reads=os.getenv(
                "FORMAI_ENABLE_CHANDRA_REGION_READS",
                "true",
            ).lower()
            in {"1", "true", "yes"},
            enable_secondary_chandra_verify=os.getenv(
                "FORMAI_ENABLE_SECONDARY_CHANDRA_VERIFY",
                "true",
            ).lower()
            in {"1", "true", "yes"},
            min_mapping_confidence=float(
                os.getenv("FORMAI_MIN_MAPPING_CONFIDENCE", "0.55")
            ),
            min_field_detection_confidence=float(
                os.getenv("FORMAI_MIN_FIELD_DETECTION_CONFIDENCE", "0.50")
            ),
            enable_output_self_check=os.getenv(
                "FORMAI_ENABLE_OUTPUT_SELF_CHECK",
                "true",
            ).lower()
            in {"1", "true", "yes"},
            strict_verification_gate=os.getenv(
                "FORMAI_STRICT_VERIFICATION_GATE",
                "false",
            ).lower()
            in {"1", "true", "yes"},
            self_check_min_source_similarity=float(
                os.getenv("FORMAI_SELF_CHECK_MIN_SOURCE_SIMILARITY", "0.42")
            ),
            self_check_min_output_similarity=float(
                os.getenv("FORMAI_SELF_CHECK_MIN_OUTPUT_SIMILARITY", "0.58")
            ),
            commonforms_model=os.getenv("FORMAI_COMMONFORMS_MODEL", "FFDNet-L"),
            commonforms_fast=os.getenv("FORMAI_COMMONFORMS_FAST", "true").lower() in {"1", "true", "yes"},
            commonforms_confidence=float(
                os.getenv("FORMAI_COMMONFORMS_CONFIDENCE", "0.6")
            ),
            commonforms_multiline=os.getenv("FORMAI_COMMONFORMS_MULTILINE", "true").lower()
            in {"1", "true", "yes"},
        )
