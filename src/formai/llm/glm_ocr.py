from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence

from formai.errors import IntegrationUnavailable, VisionProviderError
from formai.llm.base import VisionLLMClient
from formai.models import DetectedField, FieldValue, RenderedPage


class GLMOCRVisionClient(VisionLLMClient):
    def __init__(
        self,
        model: str,
        device_map: str = "auto",
        max_new_tokens: int = 1024,
    ):
        self.model = model
        self.device_map = device_map
        self.max_new_tokens = max_new_tokens
        self._torch = None
        self._processor = None
        self._model = None
        self._device = None

    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        raise IntegrationUnavailable(
            "GLM-OCR template field detection is not implemented yet. Heuristic layout detection will be used instead."
        )

    def extract_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        if not pages:
            return {}
        schema = {key: "" for key in expected_keys} or {"field_1": ""}
        prompt = (
            "Extract the requested field values from the provided document image(s). "
            "Return a JSON object only, with no prose or markdown. "
            "Use exactly the keys shown below, and make every value a string. "
            "If a field is missing or unreadable, return an empty string for that key. "
            "Use this JSON object schema exactly: "
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        payload = self._json_response(prompt, pages)
        normalized_payload = _normalize_extraction_payload(payload)
        values: Dict[str, FieldValue] = {}
        for key, item in normalized_payload.items():
            key = str(key).strip()
            if not key:
                continue
            value = str(item.get("value", ""))
            raw_confidence = item.get("confidence")
            if raw_confidence is None:
                confidence = 0.75 if value.strip() else 0.0
            else:
                confidence = float(raw_confidence)
            raw_text = str(item.get("raw_text", value))
            values[key] = FieldValue(
                value=value,
                confidence=confidence,
                source_key=key,
                raw_text=raw_text,
            )
        return values

    def _json_response(self, prompt: str, pages: Sequence[RenderedPage]) -> dict:
        try:
            response_text = self._generate(prompt, pages)
            return _extract_json_payload(response_text)
        except VisionProviderError:
            raise
        except Exception as exc:  # pragma: no cover - runtime inference failure
            raise VisionProviderError(f"GLM-OCR request failed: {exc}") from exc

    def _generate(self, prompt: str, pages: Sequence[RenderedPage]) -> str:
        self._ensure_loaded()
        with tempfile.TemporaryDirectory(prefix="formai_glm_ocr_") as temp_dir:
            image_paths = self._write_temp_images(Path(temp_dir), pages)
            content = [{"type": "image", "url": str(path)} for path in image_paths]
            content.append({"type": "text", "text": prompt})
            messages = [{"role": "user", "content": content}]
            inputs = self._processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            inputs.pop("token_type_ids", None)
            device = self._device or next(self._model.parameters()).device
            inputs = {
                key: value.to(device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }
            generated = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
            )
            prompt_length = inputs["input_ids"].shape[1]
            completion = generated[:, prompt_length:]
            return self._processor.batch_decode(
                completion,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0].strip()

    def _write_temp_images(self, directory: Path, pages: Sequence[RenderedPage]) -> List[Path]:
        paths = []
        for page in pages:
            suffix = ".png" if "png" in page.mime_type else ".jpg"
            path = directory / f"page_{page.page_number}{suffix}"
            path.write_bytes(page.image_bytes)
            paths.append(path)
        return paths

    def _ensure_loaded(self) -> None:
        if self._processor is not None and self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as exc:
            raise IntegrationUnavailable(
                "GLM-OCR dependencies are not installed. Install with: pip install -e '.[glm_ocr]'"
            ) from exc

        self._torch = torch
        self._processor = AutoProcessor.from_pretrained(
            self.model,
            trust_remote_code=True,
        )
        manual_device = self._preferred_manual_device(torch)
        if manual_device is not None:
            self._model = AutoModelForImageTextToText.from_pretrained(
                self.model,
                trust_remote_code=True,
                torch_dtype="auto",
            )
            self._device = torch.device(manual_device)
            self._model.to(self._device)
        else:
            self._model = AutoModelForImageTextToText.from_pretrained(
                self.model,
                trust_remote_code=True,
                torch_dtype="auto",
                device_map=self.device_map,
            )
            self._device = None

    def _preferred_manual_device(self, torch):
        requested = (self.device_map or "").strip().lower()
        if requested == "mps":
            if not torch.backends.mps.is_available():
                raise IntegrationUnavailable(
                    "FORMAI_GLM_OCR_DEVICE_MAP=mps was requested, but MPS is not available."
                )
            return "mps"
        if requested in {"cpu", "cuda"}:
            return requested
        if requested == "auto" and torch.backends.mps.is_available():
            return "mps"
        return None


def _extract_json_payload(text: str) -> dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = [line for line in candidate.splitlines() if not line.strip().startswith("```")]
        candidate = "\n".join(lines).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise VisionProviderError("GLM-OCR returned non-JSON output.")
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VisionProviderError("GLM-OCR returned invalid JSON output.") from exc


def _normalize_extraction_payload(payload: dict) -> Dict[str, dict]:
    if isinstance(payload.get("values"), list):
        normalized: Dict[str, dict] = {}
        for item in payload.get("values", []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            normalized[key] = {
                "value": str(item.get("value", "")),
                "raw_text": str(item.get("raw_text", item.get("value", ""))),
                "confidence": item.get("confidence", 0.0),
            }
        return normalized

    normalized = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            normalized[key] = {
                "value": str(value.get("value", "")),
                "raw_text": str(value.get("raw_text", value.get("value", ""))),
                "confidence": value.get("confidence", 0.0),
            }
            continue
        normalized[key] = {
            "value": str(value),
            "raw_text": str(value),
            "confidence": None,
        }
    return normalized
