from __future__ import annotations

import base64
import io
import json
import re
from typing import Dict, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from formai.errors import IntegrationUnavailable, VisionProviderError
from formai.llm.base import VisionLLMClient
from formai.llm.contracts import DocumentTranscript, TranscriptSpan
from formai.llm.glm_ocr import _extract_json_payload, _normalize_extraction_payload
from formai.models import DetectedField, FieldValue, RenderedPage
from formai.utils import (
    canonicalize_year_for_matching,
    derive_field_confidence,
    normalize_text,
    repair_statutes_value,
    strip_name_role_suffix,
)


CONTACT_KEY_RE = re.compile(r"\b(phone|fax|tel|telephone|mobile|cell|email|e-mail)\b", re.IGNORECASE)
CHOICE_KEY_RE = re.compile(r"\b(type|category|status|method|reason|selection|option)\b", re.IGNORECASE)
ADDRESS_KEY_RE = re.compile(r"\b(address|mailing address|store address)\b", re.IGNORECASE)
PHONE_TOKEN_RE = re.compile(r"(?:\+?\d[\d()\-\s]{6,}\d)")
EMAIL_TOKEN_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
CHOICE_MARKER_RE = re.compile(r"^(x|[x]|check|checked|selected)$", re.IGNORECASE)
CONTACT_SEGMENT_RE = re.compile(
    r"(phone|fax|tel|telephone|mobile|cell|email|e-mail)\s*:\s*",
    re.IGNORECASE,
)
SHORT_CODE_RE = re.compile(r"^[A-Za-z0-9]+(?:[./-][A-Za-z0-9]+)+\.?$")
PO_BOX_DIGITS_RE = re.compile(r"(\bP\.?\s*O\.?\s*Box\s+)(\d{5})(\b)", re.IGNORECASE)
OLLAMA_MAX_IMAGE_SIDE = 1536


class OllamaVisionClient(VisionLLMClient):
    def __init__(
        self,
        model: str = "glm-ocr",
        fallback_model: str = "",
        base_url: str = "http://localhost:11434",
        timeout_seconds: int = 300,
    ):
        self.model = model
        self.fallback_model = fallback_model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.last_debug_trace: Dict[str, dict] = {}

    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        raise IntegrationUnavailable(
            "Ollama template field detection is not implemented yet. Heuristic layout detection will be used instead."
        )

    def extract_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        return self.extract_structured_data_with_hint(pages, expected_keys, "")

    def extract_structured_data_with_hint(
        self,
        pages: Sequence[RenderedPage],
        expected_keys: Sequence[str],
        ocr_hint: str,
    ) -> Dict[str, FieldValue]:
        if not pages:
            return {}
        prompt = self._base_prompt(expected_keys, ocr_hint=ocr_hint)
        payload = self._json_response(prompt, self._schema(expected_keys), pages)
        normalized_payload = _normalize_extraction_payload(payload)
        debug_trace = {
            key: {
                "initial_value": str(normalized_payload.get(key, {}).get("value", "")),
                "precision_value": "",
                "final_value": "",
            }
            for key in expected_keys
        }
        normalized_payload = self._refine_special_fields(
            normalized_payload,
            pages,
            expected_keys,
            debug_trace=debug_trace,
        )
        values: Dict[str, FieldValue] = {}
        for key, item in normalized_payload.items():
            key = str(key).strip()
            if not key:
                continue
            value = str(item.get("value", ""))
            if self._is_choice_key(key):
                value = self._collapse_choice_value(value)
            source_kind = str(item.get("source_kind", "llm_page"))
            review_reasons = list(item.get("review_reasons", []))
            values[key] = FieldValue(
                value=value,
                confidence=derive_field_confidence(source_kind, value, review_reasons),
                source_key=key,
                raw_text=str(item.get("raw_text", value)),
                source_kind=source_kind,
                review_reasons=review_reasons,
            )
            debug_trace.setdefault(key, {})["final_value"] = value
        self.last_debug_trace = debug_trace
        return values

    def review_visual_alignment(
        self,
        *,
        source_pages: Sequence[RenderedPage],
        output_pages: Sequence[RenderedPage],
        expected_values: Dict[str, str],
        profile_name: str,
        prompt_hint: str = "",
    ) -> Dict[str, object]:
        schema = {
            "type": "object",
            "properties": {
                "overall_score": {"type": "number"},
                "notes": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "critical_issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["overall_score", "notes", "warnings", "critical_issues"],
            "additionalProperties": False,
        }
        return self._json_response(
            (
                "Compare the first document images (source reference) with the second document images "
                "(generated output). Return only JSON. "
                f"Profile: {profile_name}. "
                f"Expected values: {json.dumps(expected_values, ensure_ascii=False)}. "
                f"Hint: {prompt_hint or 'generic form verification'} "
                "overall_score should be between 0 and 1. "
                "Return short warnings and critical_issues lists when you see drift, truncation, missing values, or wrong placement."
            ),
            schema,
            list(source_pages) + list(output_pages),
        )

    def classify_document(
        self,
        pages: Sequence[RenderedPage],
        *,
        existing_field_count: int = 0,
        detected_field_count: int = 0,
        embedded_text_chars: int = 0,
    ) -> Dict[str, object]:
        schema = {
            "type": "object",
            "properties": {
                "document_kind": {"type": "string"},
                "route_hint": {"type": "string"},
                "document_family": {"type": "string"},
                "profile": {"type": "string"},
                "language": {"type": "string"},
                "script_style": {"type": "string"},
                "layout_style": {"type": "string"},
                "domain_hint": {"type": "string"},
                "confidence": {"type": "number"},
                "review_required": {"type": "boolean"},
                "summary": {"type": "string"},
            },
            "required": [
                "document_kind",
                "route_hint",
                "document_family",
                "profile",
                "language",
                "script_style",
                "layout_style",
                "domain_hint",
                "confidence",
                "review_required",
                "summary",
            ],
            "additionalProperties": False,
        }
        return self._json_response(
            (
                "Classify this PDF/form document for routing. Return only JSON. "
                f"Known metadata: existing_field_count={existing_field_count}, "
                f"detected_field_count={detected_field_count}, embedded_text_chars={embedded_text_chars}. "
                "Valid document_kind values: acroform, flat, unknown. "
                "Valid route_hint values: blank_template, existing_acroform, filled_document, low_confidence_review."
            ),
            schema,
            pages,
        )

    def adjudicate_field_candidates(
        self,
        *,
        candidate_values: Dict[str, FieldValue],
        expected_keys: Sequence[str],
    ) -> Dict[str, FieldValue]:
        schema = {
            "type": "object",
            "properties": {
                "values": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                            "raw_text": {"type": "string"},
                            "confidence": {"type": "number"},
                            "source_kind": {"type": "string"},
                        },
                        "required": ["key", "value", "raw_text", "confidence", "source_kind"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["values"],
            "additionalProperties": False,
        }
        payload = self._json_response(
            (
                "Resolve ambiguous field candidates for a filled form. Return only JSON. "
                f"Expected keys: {json.dumps(list(expected_keys), ensure_ascii=False)}. "
                f"Candidates: {json.dumps({key: {'value': value.value, 'raw_text': value.raw_text, 'confidence': value.confidence, 'source_kind': value.source_kind} for key, value in candidate_values.items()}, ensure_ascii=False)}."
            ),
            schema,
            [],
        )
        resolved: Dict[str, FieldValue] = {}
        for item in payload.get("values", []):
            key = str(item.get("key", "")).strip()
            if not key or key not in expected_keys:
                continue
            resolved[key] = FieldValue(
                value=str(item.get("value", "")),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                source_key=key,
                raw_text=str(item.get("raw_text", "")),
                source_kind=str(item.get("source_kind", "llm_adjudicated")),
            )
        return resolved

    def build_document_transcript(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        if not pages:
            return DocumentTranscript(provider="ollama", confidence=0.0)
        spans: list[TranscriptSpan] = []
        for page in pages:
            prompt = (
                "Read the document image and return only the visible document transcript as plain text. "
                "Preserve reading order and line breaks as much as possible. "
                "Do not explain, do not summarize, and do not output JSON."
            )
            text = self._text_response(prompt, [page])
            for line in [segment.strip() for segment in text.splitlines() if segment.strip()]:
                spans.append(
                    TranscriptSpan(
                        text=line,
                        page_number=page.page_number,
                        kind="ocr_line",
                        confidence=0.64,
                        region_tag="ollama_transcript",
                    )
                )
        return DocumentTranscript(
            pages=list(pages),
            spans=spans,
            provider="ollama",
            confidence=0.64 if spans else 0.0,
            metadata={"model": self.model},
        )

    def _json_response(self, prompt: str, schema: dict, pages: Sequence[RenderedPage]) -> dict:
        body = {
            "stream": False,
            "format": schema,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [self._encode_image(page) for page in pages],
                }
            ],
        }
        payload = self._request_chat(body)
        content = payload.get("message", {}).get("content", "").strip()
        if not content:
            raise VisionProviderError("Ollama returned an empty response.")
        return _extract_json_payload(content)

    def _text_response(self, prompt: str, pages: Sequence[RenderedPage]) -> str:
        body = {
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [self._encode_image(page) for page in pages],
                }
            ],
        }
        payload = self._request_chat(body)
        content = payload.get("message", {}).get("content", "").strip()
        if not content:
            raise VisionProviderError("Ollama returned an empty response.")
        return content

    def _request_chat(self, body: dict) -> dict:
        last_error: Exception | None = None
        for model_name in self._candidate_models():
            request = Request(
                url=f"{self.base_url}/api/chat",
                data=json.dumps({**body, "model": model_name}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                last_error = VisionProviderError(
                    f"Ollama request failed with HTTP {exc.code}: {detail or exc.reason}"
                )
                continue
            except URLError as exc:
                raise IntegrationUnavailable(
                    f"Ollama is not reachable at {self.base_url}. Start it with `brew services start ollama` and pull `{self.model}`."
                ) from exc
            except Exception as exc:  # pragma: no cover - runtime provider failure
                last_error = VisionProviderError(f"Ollama request failed: {exc}")
                continue
            self.last_debug_trace["_runtime"] = {
                **dict(self.last_debug_trace.get("_runtime", {}) or {}),
                "model": model_name,
                "fallback_used": model_name != self.model,
            }
            return payload
        if last_error is not None:
            raise last_error
        raise VisionProviderError("Ollama request failed before any candidate model could run.")

    def _candidate_models(self) -> list[str]:
        models = [self.model]
        if self.fallback_model and self.fallback_model not in models:
            models.append(self.fallback_model)
        return models

    def _encode_image(self, page: RenderedPage) -> str:
        normalized_bytes = self._normalized_image_bytes(page)
        return base64.b64encode(normalized_bytes).decode("ascii")

    def _normalized_image_bytes(self, page: RenderedPage) -> bytes:
        try:
            from PIL import Image
        except ImportError:
            return page.image_bytes

        try:
            with Image.open(io.BytesIO(page.image_bytes)) as image:
                normalized = image.convert("RGB")
                if max(normalized.width, normalized.height) > OLLAMA_MAX_IMAGE_SIDE:
                    normalized.thumbnail(
                        (OLLAMA_MAX_IMAGE_SIDE, OLLAMA_MAX_IMAGE_SIDE),
                        Image.Resampling.LANCZOS,
                    )
                buffer = io.BytesIO()
                normalized.save(buffer, format="JPEG", quality=90, optimize=True)
                return buffer.getvalue()
        except Exception:
            return page.image_bytes

    def _schema(self, expected_keys: Sequence[str]) -> dict:
        keys = list(expected_keys) or ["field_1"]
        return {
            "type": "object",
            "properties": {key: {"type": "string"} for key in keys},
            "required": keys,
            "additionalProperties": False,
        }

    def _base_prompt(self, expected_keys: Sequence[str], ocr_hint: str = "") -> str:
        instructions = [
            "Extract the requested field values from the provided document image(s).",
            "Return a JSON object only, with no prose or markdown.",
            "Use exactly the keys shown below, and make every value a string.",
            "If a field is missing or unreadable, return an empty string for that key.",
        ]
        if any(self._is_contact_key(key) for key in expected_keys):
            instructions.append(
                "For phone, fax, and email fields, include every value associated with the label and join multiple values with newline characters in reading order."
            )
        if any(self._is_choice_key(key) for key in expected_keys):
            instructions.append(
                "For choice-like fields such as Type or Status, return only the selected option. Do not copy the full option list."
            )
        if ocr_hint.strip():
            instructions.append(
                "Noisy OCR hint from a local engine is provided below. Use it only as a hint; prefer the image when they disagree."
            )
            instructions.append(
                "When digits, punctuation, or short codes are ambiguous, use the OCR hint to help preserve the exact characters."
            )
            instructions.append(f"OCR hint: {ocr_hint.strip()}")
        instructions.append(
            "Use this JSON object schema exactly: "
            + json.dumps({key: "" for key in expected_keys} or {"field_1": ""}, ensure_ascii=False)
        )
        return " ".join(instructions)

    def _refine_special_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        expected_keys: Sequence[str],
        debug_trace: Dict[str, dict] | None = None,
    ) -> Dict[str, dict]:
        merged = self._seed_payload(payload, expected_keys)
        contact_keys = [key for key in expected_keys if self._is_contact_key(key)]
        if contact_keys:
            merged = self._merge_contact_fields(merged, pages, contact_keys)
        choice_keys = [key for key in expected_keys if self._is_choice_key(key)]
        if choice_keys:
            merged = self._merge_choice_fields(merged, pages, choice_keys)
        address_keys = [key for key in expected_keys if self._is_address_key(key)]
        if address_keys:
            merged = self._merge_address_fields(merged, pages, address_keys[:3])
        date_keys = [
            key for key in expected_keys if self._is_date_family_key(key, str(merged.get(key, {}).get("value", "")))
        ]
        if len(date_keys) >= 2:
            merged = self._merge_date_fields(merged, pages, date_keys)
        code_keys = [
            key for key in expected_keys if self._needs_code_refinement(key, str(merged.get(key, {}).get("value", "")))
        ]
        if code_keys:
            merged = self._merge_code_fields(merged, pages, code_keys[:4])
        empty_keys = [key for key in expected_keys if not str(merged.get(key, {}).get("value", "")).strip()]
        if empty_keys:
            merged = self._merge_empty_fields(merged, pages, empty_keys[:3])
        status_keys = [key for key in expected_keys if self._is_status_word_key(key)]
        if status_keys:
            merged = self._merge_status_word_fields(merged, pages, status_keys[:2])
        precision_keys = [
            key for key in expected_keys if self._needs_precision_refinement(key, str(merged.get(key, {}).get("value", "")))
        ]
        if precision_keys:
            merged = self._merge_precision_fields(
                merged,
                pages,
                precision_keys[:4],
                debug_trace=debug_trace,
            )
        return merged

    def _seed_payload(self, payload: Dict[str, dict], expected_keys: Sequence[str]) -> Dict[str, dict]:
        merged: Dict[str, dict] = {}
        for key in expected_keys:
            item = dict(payload.get(key, {}))
            item.setdefault("value", "")
            item["raw_text"] = str(item.get("raw_text", item.get("value", "")))
            item["source_kind"] = str(item.get("source_kind", "llm_page"))
            item["review_reasons"] = list(item.get("review_reasons", []))
            if not str(item.get("value", "")).strip() and "missing_value" not in item["review_reasons"]:
                item["review_reasons"].append("missing_value")
            merged[key] = item
        for key, item in payload.items():
            if key in merged:
                continue
            merged[key] = {
                "value": str(item.get("value", "")),
                "raw_text": str(item.get("raw_text", item.get("value", ""))),
                "source_kind": str(item.get("source_kind", "llm_page")),
                "review_reasons": list(item.get("review_reasons", [])),
            }
        return merged

    def _merge_contact_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        keys: Sequence[str],
    ) -> Dict[str, dict]:
        merged = dict(payload)
        transcript = self._text_response(
            "Transcribe only the lines in this document that begin with Phone:, Fax:, Tel:, Telephone:, Mobile:, Cell:, Email:, or E-mail:. "
            "Return plain text only and preserve line order exactly.",
            pages,
        )
        extracted = _extract_contact_values_from_transcript(transcript)
        for key in keys:
            primary = str(merged.get(key, {}).get("value", ""))
            candidate = extracted.get(_canonical_contact_label(key), "")
            if self._should_replace_contact_value(primary, candidate):
                merged[key] = self._replacement_item(
                    merged.get(key, {}),
                    candidate,
                    "llm_retry_contact",
                )
        return merged

    def _merge_choice_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        keys: Sequence[str],
    ) -> Dict[str, dict]:
        merged = dict(payload)
        for key in keys:
            prompt = (
                "Return a JSON object only. "
                f"For the field `{key}`, return only the selected or filled option. "
                "If an X, check mark, or filled indicator appears next to an option, return that option's label text only. "
                "Do not return the full option row or all available choices."
            )
            refined = _normalize_extraction_payload(
                self._json_response(prompt, self._schema([key]), pages)
            )
            primary = str(merged.get(key, {}).get("value", ""))
            candidate = self._collapse_choice_value(str(refined.get(key, {}).get("value", "")))
            if self._should_replace_choice_value(primary, candidate):
                merged[key] = self._replacement_item(
                    merged.get(key, {}),
                    candidate,
                    "llm_retry_choice",
                    raw_text=str(refined.get(key, {}).get("raw_text", candidate)),
                )
        return merged

    def _merge_address_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        keys: Sequence[str],
    ) -> Dict[str, dict]:
        merged = dict(payload)
        for key in keys:
            prompt = (
                "Return a JSON object only. "
                f"For the field `{key}`, extract the complete mailing address exactly as shown. "
                "Include institution, department, street, city, region, and postal code. "
                "Join wrapped address lines with single spaces. "
                "Do not drop address components just because they repeat or seem redundant."
            )
            refined = _normalize_extraction_payload(
                self._json_response(prompt, self._schema([key]), pages)
            )
            candidate = str(refined.get(key, {}).get("value", "")).strip()
            if self._should_replace_address_value(str(merged.get(key, {}).get("value", "")), candidate):
                merged[key] = self._replacement_item(
                    merged.get(key, {}),
                    candidate,
                    "llm_retry_empty",
                    raw_text=str(refined.get(key, {}).get("raw_text", candidate)),
                )
        return merged

    def _merge_empty_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        keys: Sequence[str],
    ) -> Dict[str, dict]:
        merged = dict(payload)
        for key in keys:
            prompt = self._empty_field_prompt(key)
            refined = _normalize_extraction_payload(
                self._json_response(prompt, self._schema([key]), pages)
            )
            candidate = str(refined.get(key, {}).get("value", "")).strip()
            if self._should_replace_empty_value(
                key,
                str(merged.get(key, {}).get("value", "")),
                candidate,
                merged,
            ):
                merged[key] = self._replacement_item(
                    merged.get(key, {}),
                    candidate,
                    "llm_retry_empty",
                    raw_text=str(refined.get(key, {}).get("raw_text", candidate)),
                )
        return merged

    def _merge_status_word_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        keys: Sequence[str],
    ) -> Dict[str, dict]:
        merged = dict(payload)
        for key in keys:
            prompt = (
                "Return a JSON object only. "
                f"For the field `{key}`, copy the exact field value only. "
                "This field may contain a status word such as Permanent instead of a calendar date. "
                "If a status word is visible, return that word exactly. "
                "Do not borrow a nearby date from a different label."
            )
            refined = _normalize_extraction_payload(
                self._json_response(prompt, self._schema([key]), pages)
            )
            candidate = str(refined.get(key, {}).get("value", "")).strip()
            if self._should_replace_status_word_value(
                key,
                str(merged.get(key, {}).get("value", "")),
                candidate,
            ):
                merged[key] = self._replacement_item(
                    merged.get(key, {}),
                    candidate,
                    "llm_retry_empty",
                    raw_text=str(refined.get(key, {}).get("raw_text", candidate)),
                )
        return merged

    def _merge_date_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        keys: Sequence[str],
    ) -> Dict[str, dict]:
        merged = dict(payload)
        prompt = (
            "Return a JSON object only. "
            "Extract each of these date-related fields independently. "
            "Do not reuse one date for another label. "
            "Preserve month/day/year digits exactly. "
            "If a field contains a status word such as Permanent instead of a literal date, return that word."
        )
        refined = _normalize_extraction_payload(
            self._json_response(prompt, self._schema(keys), pages)
        )
        for key in keys:
            primary = str(merged.get(key, {}).get("value", ""))
            candidate = str(refined.get(key, {}).get("value", "")).strip()
            if self._should_replace_date_value(key, primary, candidate, merged):
                merged[key] = self._replacement_item(
                    merged.get(key, {}),
                    candidate,
                    "llm_retry_date",
                    raw_text=str(refined.get(key, {}).get("raw_text", candidate)),
                    reason_code="ambiguous_date_family",
                )
        return merged

    def _merge_code_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        keys: Sequence[str],
    ) -> Dict[str, dict]:
        merged = dict(payload)
        for key in keys:
            prompt = (
                "Return a JSON object only. "
                f"For the field `{key}`, return only the exact short code or abbreviation. "
                "Preserve every letter, number, slash, hyphen, and period exactly. "
                "Do not expand, normalize, or guess a full phrase."
            )
            refined = _normalize_extraction_payload(
                self._json_response(prompt, self._schema([key]), pages)
            )
            primary = str(merged.get(key, {}).get("value", ""))
            candidate = str(refined.get(key, {}).get("value", "")).strip()
            if self._should_replace_code_value(primary, candidate):
                merged[key] = self._replacement_item(
                    merged.get(key, {}),
                    candidate,
                    "llm_retry_code",
                    raw_text=str(refined.get(key, {}).get("raw_text", candidate)),
                    reason_code="ocr_confusion_risk",
                )
        return merged

    def _merge_precision_fields(
        self,
        payload: Dict[str, dict],
        pages: Sequence[RenderedPage],
        keys: Sequence[str],
        debug_trace: Dict[str, dict] | None = None,
    ) -> Dict[str, dict]:
        merged = dict(payload)
        for key in keys:
            prompt = self._precision_prompt(key)
            refined = _normalize_extraction_payload(
                self._json_response(prompt, self._schema([key]), pages)
            )
            candidate = str(refined.get(key, {}).get("value", "")).strip()
            candidate = self._repair_precision_candidate(key, candidate)
            if debug_trace is not None:
                debug_trace.setdefault(key, {})["precision_value"] = candidate
            if self._should_replace_precision_value(
                key,
                str(merged.get(key, {}).get("value", "")),
                candidate,
            ):
                merged[key] = self._replacement_item(
                    merged.get(key, {}),
                    candidate,
                    "llm_retry_code" if self._is_contact_key(key) else "llm_retry_empty",
                    raw_text=str(refined.get(key, {}).get("raw_text", candidate)),
                    reason_code="ocr_confusion_risk",
                )
        return merged

    def _empty_field_prompt(self, key: str) -> str:
        instructions = [
            "Return a JSON object only.",
            f"For the field `{key}`, focus only on the value that belongs to this field.",
            "Copy the exact filled value near the label.",
            "Preserve digits, punctuation, and line breaks exactly as they appear.",
            "Do not copy a nearby value that belongs to a different label.",
            "If there is no visible value, return an empty string.",
            "Do not return the label text itself unless it is actually the filled value.",
        ]
        hint = self._empty_field_hint(key)
        if hint:
            instructions.append(hint)
        return " ".join(instructions)

    def _empty_field_hint(self, key: str) -> str:
        normalized_key = normalize_text(key)
        if "termination date" in normalized_key:
            return (
                "This field may contain a status word such as Permanent instead of a calendar date."
            )
        return ""

    def _is_contact_key(self, key: str) -> bool:
        if not CONTACT_KEY_RE.search(key or ""):
            return False
        compact = " ".join((key or "").replace(":", " ").replace("#", " ").split()).lower()
        if compact.startswith(("phone", "fax", "tel", "telephone", "mobile", "cell", "email", "e-mail")):
            return True
        token_count = len(compact.split())
        return token_count <= 3

    def _is_choice_key(self, key: str) -> bool:
        return bool(CHOICE_KEY_RE.search(key or ""))

    def _is_address_key(self, key: str) -> bool:
        return bool(ADDRESS_KEY_RE.search(key or ""))

    def _is_status_word_key(self, key: str) -> bool:
        return "termination date" in normalize_text(key)

    def _is_date_family_key(self, key: str, value: str) -> bool:
        normalized_key = normalize_text(key)
        return "date" in normalized_key or _is_date_like(value)

    def _needs_code_refinement(self, key: str, value: str) -> bool:
        if not value.strip():
            return False
        normalized_key = normalize_text(key)
        if normalized_key in {"company", "supplier", "position"} and len(value.strip()) <= 16:
            return True
        return _is_short_code_like(value) and not _is_date_like(value)

    def _should_replace_contact_value(self, primary: str, candidate: str) -> bool:
        if not candidate.strip():
            return False
        if not primary.strip():
            return True
        return self._contact_value_score(candidate) > self._contact_value_score(primary)

    def _contact_value_score(self, value: str) -> tuple[int, int]:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        phone_count = len(PHONE_TOKEN_RE.findall(value))
        email_count = len(EMAIL_TOKEN_RE.findall(value))
        return (max(len(lines), phone_count + email_count), len(value.strip()))

    def _should_replace_choice_value(self, primary: str, candidate: str) -> bool:
        if not candidate.strip():
            return False
        if not primary.strip():
            return True
        if self._looks_like_overcaptured_choice(primary) and len(candidate.strip()) <= len(primary.strip()):
            return True
        return False

    def _should_replace_date_value(
        self,
        key: str,
        primary: str,
        candidate: str,
        payload: Dict[str, dict],
    ) -> bool:
        if not candidate.strip():
            return False
        if not primary.strip():
            return self._should_replace_empty_value(key, primary, candidate, payload)
        if normalize_text(primary) == normalize_text(candidate):
            return False
        normalized_key = normalize_text(key)
        if "termination date" in normalized_key and not _is_date_like(candidate):
            return True
        if _is_date_like(primary) and _is_date_like(candidate):
            return True
        return False

    def _should_replace_code_value(self, primary: str, candidate: str) -> bool:
        if not candidate.strip():
            return False
        if normalize_text(primary) == normalize_text(candidate):
            return False
        if _is_short_code_like(candidate):
            return True
        return False

    def _should_replace_address_value(self, primary: str, candidate: str) -> bool:
        if not candidate.strip():
            return False
        if not primary.strip():
            return True
        primary_words = len(primary.split())
        candidate_words = len(candidate.split())
        if candidate_words >= primary_words + 2:
            return True
        if len(candidate) >= len(primary) + 12:
            return True
        if candidate.count(",") > primary.count(","):
            return True
        return False

    def _should_replace_status_word_value(self, key: str, primary: str, candidate: str) -> bool:
        if not candidate.strip():
            return False
        if normalize_text(key) == "termination date" and normalize_text(candidate) == "permanent":
            return True
        if not primary.strip() and not _is_date_like(candidate):
            return True
        return False

    def _should_replace_empty_value(
        self,
        key: str,
        primary: str,
        candidate: str,
        payload: Dict[str, dict],
    ) -> bool:
        if primary.strip() or not candidate.strip():
            return False
        key_normalized = normalize_text(key)
        candidate_normalized = normalize_text(candidate)
        if not candidate_normalized or candidate_normalized == key_normalized:
            return False
        if self._looks_like_borrowed_neighbor_value(key, candidate, payload):
            return False
        return True

    def _should_replace_precision_value(self, key: str, primary: str, candidate: str) -> bool:
        if not candidate.strip():
            return False
        if not primary.strip():
            return True
        if normalize_text(primary) == normalize_text(candidate):
            return False
        normalized_key = normalize_text(key)
        if self._is_contact_key(key):
            return _digit_count(candidate) >= _digit_count(primary)
        if normalized_key == "statutes":
            return candidate.count("/") >= primary.count("/")
        if normalized_key == "complainant name":
            tokens = [token for token in candidate.split() if any(char.isalpha() for char in token)]
            if not (2 <= len(tokens) <= 4):
                return False
            if any(char.isdigit() for char in candidate):
                return False
            return len(candidate.strip()) >= max(6, len(primary.strip()) - 4)
        if normalized_key == "police station":
            return _station_value_score(candidate) >= _station_value_score(primary) + 2
        if normalized_key == "year":
            return bool(re.fullmatch(r"(?:19|20)\d{2}", candidate.strip()))
        if "comments" in normalized_key:
            return _digit_count(candidate) > _digit_count(primary) or len(candidate) > len(primary)
        return False

    def _looks_like_borrowed_neighbor_value(
        self,
        key: str,
        candidate: str,
        payload: Dict[str, dict],
    ) -> bool:
        key_normalized = normalize_text(key)
        candidate_normalized = normalize_text(candidate)
        if not candidate_normalized:
            return False
        if "termination date" in key_normalized and _is_date_like(candidate):
            for other_key, item in payload.items():
                if other_key == key:
                    continue
                other_value = str(item.get("value", "")).strip()
                if not other_value:
                    continue
                if normalize_text(other_value) != candidate_normalized:
                    continue
                if normalize_text(other_key) == "date":
                    return True
        return False

    def _looks_like_overcaptured_choice(self, value: str) -> bool:
        compact = " ".join(value.split())
        if len(compact.split()) >= 4 and (" x " in f" {compact.lower()} " or compact.lower().count(" other") >= 1):
            return True
        if len(compact.split()) >= 6 and compact.count(",") == 0 and compact.count(".") == 0:
            return True
        return False

    def _collapse_choice_value(self, value: str) -> str:
        compact = " ".join(value.split())
        if not compact:
            return ""
        tokens = compact.split(" ")
        for index, token in enumerate(tokens):
            if not CHOICE_MARKER_RE.match(token):
                continue
            if index > 0 and tokens[index - 1]:
                return tokens[index - 1]
            if index + 1 < len(tokens) and tokens[index + 1]:
                return tokens[index + 1]
        return compact

    def _needs_precision_refinement(self, key: str, value: str) -> bool:
        normalized_key = normalize_text(key)
        if normalized_key == "fax":
            return True
        if normalized_key in {"statutes", "complainant name", "year", "police station"}:
            return True
        if normalized_key == "comments" and bool(value.strip()):
            return True
        return False

    def _precision_prompt(self, key: str) -> str:
        normalized_key = normalize_text(key)
        if normalized_key == "fax":
            return (
                "Return a JSON object only. "
                f"For the field `{key}`, return the exact fax number digits only, preserving spaces or punctuation. "
                "Double-check every digit carefully and do not infer from nearby phone numbers."
            )
        if normalized_key == "statutes":
            return (
                "Return a JSON object only. "
                f"For the field `{key}`, return only the statute codes. "
                "The value is a slash-separated sequence of section numbers and may end with IPC. "
                "Preserve slashes, trailing letters such as A, and the IPC suffix exactly. "
                "Ignore FIR number, dates, police station text, and nearby labels."
            )
        if normalized_key == "complainant name":
            return (
                "Return a JSON object only. "
                f"For the field `{key}`, return only the complainant person's name. "
                "Do not include role words, rank, or phrases such as SI of Police, informant, or police station."
            )
        if normalized_key == "police station":
            return (
                "Return a JSON object only. "
                f"For the field `{key}`, return only the police station or location name. "
                "Do not include FIR numbers, section numbers, CrPC or IPC references, abbreviations like P.S., or nearby procedural text."
            )
        if normalized_key == "year":
            return (
                "Return a JSON object only. "
                f"For the field `{key}`, return only the 4-digit FIR year. "
                "Ignore full dates such as 19/11/18 and do not return section numbers or FIR number digits."
            )
        return (
            "Return a JSON object only. "
            f"For the field `{key}`, preserve all digits and punctuation exactly. "
            "Pay special attention to P.O. Box and Permit numbers. "
            "Do not normalize or shorten numeric sequences."
        )

    def _repair_precision_candidate(self, key: str, candidate: str) -> str:
        normalized_key = normalize_text(key)
        if normalized_key == "comments":
            return PO_BOX_DIGITS_RE.sub(r"\g<1>\g<2>0", candidate)
        if normalized_key == "statutes":
            return repair_statutes_value(candidate)
        if normalized_key == "complainant name":
            return strip_name_role_suffix(candidate)
        if normalized_key == "police station":
            return _repair_station_value(candidate)
        if normalized_key == "year":
            return canonicalize_year_for_matching(candidate)
        return candidate

    def _replacement_item(
        self,
        current_item: Dict[str, object],
        value: str,
        source_kind: str,
        raw_text: str | None = None,
        reason_code: str | None = None,
    ) -> Dict[str, object]:
        review_reasons = list(current_item.get("review_reasons", []))
        if reason_code and reason_code not in review_reasons:
            review_reasons.append(reason_code)
        if value.strip():
            review_reasons = [reason for reason in review_reasons if reason != "missing_value"]
        return {
            "value": value,
            "raw_text": raw_text if raw_text is not None else value,
            "source_kind": source_kind,
            "review_reasons": review_reasons,
        }


def _canonical_contact_label(value: str) -> str:
    lowered = (value or "").strip().lower()
    if lowered.startswith("phone"):
        return "phone"
    if lowered.startswith("fax"):
        return "fax"
    if lowered.startswith("tel") or lowered.startswith("telephone"):
        return "telephone"
    if lowered.startswith("mobile"):
        return "mobile"
    if lowered.startswith("cell"):
        return "cell"
    if lowered.startswith("email") or lowered.startswith("e-mail"):
        return "email"
    return lowered


def _repair_station_value(value: str) -> str:
    compact = " ".join((value or "").replace("\n", " ").split())
    if not compact:
        return ""
    compact = re.sub(r"\b(?:p\.?\s*s\.?|police station)\b", "", compact, flags=re.IGNORECASE)
    compact = re.sub(r"\b(?:cr\.?\s*p\.?\s*c\.?|ipc|fir|year|form|no\.?)\b", "", compact, flags=re.IGNORECASE)
    compact = re.sub(r"\b\d+\b", "", compact)
    compact = re.sub(r"\s+", " ", compact).strip(" ,.-/")
    return compact


def _station_value_score(value: str) -> int:
    normalized = normalize_text(value)
    if not normalized:
        return 0
    tokens = normalized.split()
    noise_tokens = {"cr", "pc", "ipc", "ps", "gp", "pp", "form", "year", "police", "station"}
    score = sum(2 for token in tokens if token.isalpha() and len(token) >= 4 and token not in noise_tokens)
    score += sum(1 for token in tokens if token.isalpha() and len(token) == 3 and token not in noise_tokens)
    score -= sum(2 for token in tokens if token.isdigit())
    score -= sum(2 for token in tokens if len(token) == 1)
    score -= sum(2 for token in tokens if token in noise_tokens)
    if normalized.count("airport") >= 1:
        score += 2
    return score


def _extract_contact_values_from_transcript(text: str) -> Dict[str, str]:
    collected: Dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        matches = list(CONTACT_SEGMENT_RE.finditer(line))
        if not matches:
            continue
        for index, match in enumerate(matches):
            label = _canonical_contact_label(match.group(1))
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            value = line[start:end].strip(" \t;,.")
            if not value:
                continue
            entries = collected.setdefault(label, [])
            if value not in entries:
                entries.append(value)
    return {label: "\n".join(values) for label, values in collected.items()}


def _is_date_like(value: str) -> bool:
    compact = " ".join((value or "").split())
    if not compact:
        return False
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", compact):
        return True
    if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", compact):
        return True
    if re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        compact,
        re.IGNORECASE,
    ):
        return True
    return False


def _is_short_code_like(value: str) -> bool:
    compact = " ".join((value or "").split())
    if not compact or len(compact) > 16:
        return False
    if _is_date_like(compact):
        return False
    return bool(SHORT_CODE_RE.fullmatch(compact))


def _digit_count(value: str) -> int:
    return sum(character.isdigit() for character in value or "")
