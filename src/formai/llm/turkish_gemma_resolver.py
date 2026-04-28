from __future__ import annotations

import json
from typing import Sequence

from formai.errors import IntegrationUnavailable, VisionProviderError
from formai.llm.base import VisionLLMClient
from formai.llm.contracts import DocumentTranscript, FieldEvidence, FieldEvidenceGraph
from formai.models import DetectedField, FieldValue, RenderedPage


class TurkishGemmaResolverClient(VisionLLMClient):
    """Optional Turkish semantic resolver working from transcript text."""

    def __init__(
        self,
        model: str = "ytu-ce-cosmos/Turkish-Gemma-9b-T1",
        device_map: str = "auto",
        max_new_tokens: int = 768,
    ):
        self.model = model
        self.device_map = device_map
        self.max_new_tokens = max_new_tokens
        self._tokenizer = None
        self._model = None

    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        raise IntegrationUnavailable(
            "Turkish-Gemma resolver backend does not implement template field detection."
        )

    def extract_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> dict[str, FieldValue]:
        raise IntegrationUnavailable(
            "Turkish-Gemma is configured as a schema resolver backend and requires a document transcript."
        )

    def resolve_field_evidence(
        self,
        transcript: DocumentTranscript,
        expected_keys: Sequence[str],
    ) -> FieldEvidenceGraph:
        if not expected_keys:
            return FieldEvidenceGraph(source="turkish_gemma", profile_name="turkish_resolver")
        prompt = self._build_prompt(transcript, expected_keys)
        payload = self._json_response(prompt)
        values = payload.get("values", payload if isinstance(payload, dict) else {})
        evidences: list[FieldEvidence] = []
        confidences: list[float] = []
        for key in expected_keys:
            item = values.get(key, {})
            if isinstance(item, str):
                item = {"value": item}
            resolved_value = str(item.get("value", "") or "")
            confidence = float(item.get("confidence", 0.0) or 0.0)
            reason = str(item.get("reason", "") or "turkish_gemma_resolver")
            raw_candidates = item.get("candidates", [])
            if not isinstance(raw_candidates, list):
                raw_candidates = []
            evidences.append(
                FieldEvidence(
                    field_key=key,
                    page_number=1,
                    resolved_value=resolved_value,
                    resolution_reason=reason,
                    ocr_candidates=[str(candidate) for candidate in raw_candidates if str(candidate).strip()],
                    confidence_breakdown={"field_confidence": confidence},
                )
            )
            confidences.append(confidence)
        return FieldEvidenceGraph(
            field_evidence=evidences,
            source="turkish_gemma",
            profile_name="turkish_resolver",
            confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
        )

    def _build_prompt(self, transcript: DocumentTranscript, expected_keys: Sequence[str]) -> str:
        lines = []
        for span in transcript.spans[:300]:
            text = str(getattr(span, "text", "")).strip()
            if not text:
                continue
            page_number = int(getattr(span, "page_number", 1))
            lines.append(f"[page {page_number}] {text}")
        transcript_text = "\n".join(lines).strip()
        if not transcript_text:
            transcript_text = "No transcript text was available."
        schema = {
            key: {
                "value": "",
                "confidence": 0.0,
                "reason": "",
                "candidates": [],
            }
            for key in expected_keys
        }
        return (
            "Sen FormAI icin Turkce form cozumleyicisisin. "
            "Verilen OCR/layout transcript'inden sadece istenen alanlari cikar. "
            "Tahmin yapiyorsan confidence dusur. Komsu alandan borrow etme. "
            "Bos ya da emin olunmayan alanlar icin value bos string olsun. "
            "Sadece gecerli JSON dondur. "
            f"Istenen alanlar: {', '.join(expected_keys)}. "
            f"JSON semasi: {json.dumps({'values': schema}, ensure_ascii=False)}\n\n"
            f"Transcript:\n{transcript_text}"
        )

    def _json_response(self, prompt: str) -> dict:
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise IntegrationUnavailable(
                "Turkish-Gemma resolver requires `transformers`."
            ) from exc
        if self._tokenizer is None or self._model is None:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model,
                device_map=self.device_map,
                torch_dtype="auto",
            )
        inputs = self._tokenizer(prompt, return_tensors="pt")
        inputs = {
            key: value.to(self._model.device) if hasattr(value, "to") else value
            for key, value in inputs.items()
        }
        try:
            output = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
            )
        except Exception as exc:  # pragma: no cover - runtime inference failure
            raise VisionProviderError(f"Turkish-Gemma resolver failed: {exc}") from exc
        prompt_length = inputs["input_ids"].shape[1]
        text = self._tokenizer.decode(
            output[0][prompt_length:],
            skip_special_tokens=True,
        ).strip()
        return _parse_json_payload(text)


def _parse_json_payload(text: str) -> dict:
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
        raise VisionProviderError("Turkish-Gemma returned non-JSON output.")
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VisionProviderError("Turkish-Gemma returned invalid JSON output.") from exc
