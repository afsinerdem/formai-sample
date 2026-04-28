from __future__ import annotations

import base64
import json
from typing import Dict, List, Sequence

from formai.errors import IntegrationUnavailable, VisionProviderError
from formai.models import BoundingBox, DetectedField, FieldKind, FieldValue, RenderedPage
from formai.llm.base import VisionLLMClient


class OpenAIVisionClient(VisionLLMClient):
    """OpenAI Responses API adapter for template analysis and form extraction.

    This class intentionally keeps the provider boundary small so it can be
    replaced if the SDK or provider changes.
    """

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise IntegrationUnavailable("OPENAI_API_KEY is required for OpenAIVisionClient.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise IntegrationUnavailable(
                "openai package is not installed. Install with: pip install -e '.[vision]'"
            ) from exc

        self._client = OpenAI(api_key=api_key)
        self.model = model

    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "label": {"type": "string"},
                            "field_kind": {"type": "string"},
                            "page_number": {"type": "integer"},
                            "left": {"type": "number"},
                            "top": {"type": "number"},
                            "right": {"type": "number"},
                            "bottom": {"type": "number"},
                            "confidence": {"type": "number"},
                            "page_hint_text": {"type": "string"},
                        },
                        "required": [
                            "label",
                            "field_kind",
                            "page_number",
                            "left",
                            "top",
                            "right",
                            "bottom",
                            "confidence",
                            "page_hint_text",
                        ],
                    },
                }
            },
            "required": ["fields"],
        }

        prompt = (
            "You are analyzing a blank or partially blank form template. "
            "Return every fillable field candidate with a label, approximate bounding box, "
            "page number, field kind, and confidence. Use normalized page-local coordinates "
            "in the original PDF coordinate system if possible."
        )
        payload = self._json_response(prompt, schema, pages)
        results: List[DetectedField] = []
        for field in payload.get("fields", []):
            results.append(
                DetectedField(
                    label=field["label"],
                    field_kind=_resolve_field_kind(field["field_kind"]),
                    box=BoundingBox(
                        page_number=int(field["page_number"]),
                        left=float(field["left"]),
                        top=float(field["top"]),
                        right=float(field["right"]),
                        bottom=float(field["bottom"]),
                    ),
                    confidence=float(field["confidence"]),
                    page_hint_text=field.get("page_hint_text", ""),
                )
            )
        return results

    def extract_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "values": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                            "raw_text": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["key", "value", "raw_text", "confidence"],
                    },
                }
            },
            "required": ["values"],
        }

        keys = ", ".join(expected_keys) if expected_keys else "unknown"
        prompt = (
            "You are extracting data from a filled form. "
            "Return a strict JSON payload. "
            "Prefer these canonical keys when applicable: "
            f"{keys}. "
            "For handwriting, preserve uncertain content in raw_text and lower confidence."
        )
        payload = self._json_response(prompt, schema, pages)
        values: Dict[str, FieldValue] = {}
        for item in payload.get("values", []):
            values[item["key"]] = FieldValue(
                value=item["value"],
                confidence=float(item["confidence"]),
                source_key=item["key"],
                raw_text=item["raw_text"],
            )
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
            "additionalProperties": False,
            "properties": {
                "overall_score": {"type": "number"},
                "notes": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "critical_issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["overall_score", "notes", "warnings", "critical_issues"],
        }
        payload = self._json_response(
            (
                "You are visually comparing a reference document image and a generated PDF render. "
                "Score how well the generated output preserves the expected field values and alignment. "
                f"Profile: {profile_name}. "
                f"Expected values: {json.dumps(expected_values, ensure_ascii=False)}. "
                f"Hint: {prompt_hint or 'generic form verification'} "
                "The first images are the source document. The second images are the generated output. "
                "Return short warnings and critical_issues lists when you see drift, truncation, missing values, or wrong regions."
            ),
            schema,
            list(source_pages) + list(output_pages),
        )
        return payload

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
            "additionalProperties": False,
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
        }
        payload = self._json_response(
            (
                "Classify this PDF/form document for downstream routing. "
                "Return only strict JSON. "
                f"Known metadata: existing_field_count={existing_field_count}, "
                f"detected_field_count={detected_field_count}, embedded_text_chars={embedded_text_chars}. "
                "Valid document_kind values: acroform, flat, unknown. "
                "Valid route_hint values: blank_template, existing_acroform, filled_document, low_confidence_review. "
                "Use the metadata as hints, but use the images to decide when possible."
            ),
            schema,
            pages,
        )
        return payload

    def adjudicate_field_candidates(
        self,
        *,
        candidate_values: Dict[str, FieldValue],
        expected_keys: Sequence[str],
    ) -> Dict[str, FieldValue]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "values": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                            "raw_text": {"type": "string"},
                            "confidence": {"type": "number"},
                            "source_kind": {"type": "string"},
                        },
                        "required": ["key", "value", "raw_text", "confidence", "source_kind"],
                    },
                }
            },
            "required": ["values"],
        }
        payload = self._json_response(
            (
                "Resolve ambiguous form field candidates. Return only strict JSON. "
                f"Expected keys: {json.dumps(list(expected_keys), ensure_ascii=False)}. "
                f"Candidates: {json.dumps({key: {'value': value.value, 'raw_text': value.raw_text, 'confidence': value.confidence, 'source_kind': value.source_kind} for key, value in candidate_values.items()}, ensure_ascii=False)}."
            ),
            schema,
            [],
        )
        resolved: Dict[str, FieldValue] = {}
        for item in payload.get("values", []):
            key = str(item["key"]).strip()
            if not key or key not in expected_keys:
                continue
            resolved[key] = FieldValue(
                value=item["value"],
                confidence=float(item["confidence"]),
                source_key=key,
                raw_text=item["raw_text"],
                source_kind=item["source_kind"],
            )
        return resolved

    def _json_response(self, prompt: str, schema: dict, pages: Sequence[RenderedPage]) -> dict:
        try:
            response = self._client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}]
                        + [self._image_item(page) for page in pages],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "formai_schema",
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
        except Exception as exc:  # pragma: no cover - runtime provider failure
            raise VisionProviderError(f"Vision provider request failed: {exc}") from exc

        if not getattr(response, "output_text", ""):
            raise VisionProviderError("Vision provider returned an empty response.")
        try:
            return json.loads(response.output_text)
        except json.JSONDecodeError as exc:
            raise VisionProviderError("Vision provider returned invalid JSON output.") from exc

    def _image_item(self, page: RenderedPage) -> dict:
        b64 = base64.b64encode(page.image_bytes).decode("ascii")
        return {
            "type": "input_image",
            "image_url": f"data:{page.mime_type};base64,{b64}",
        }


def _resolve_field_kind(value: str) -> FieldKind:
    normalized = (value or "").strip().lower()
    if normalized in {"checkbox", "check"}:
        return FieldKind.CHECKBOX
    if normalized == "radio":
        return FieldKind.RADIO
    if normalized == "signature":
        return FieldKind.SIGNATURE
    if normalized == "date":
        return FieldKind.DATE
    if normalized in {"number", "numeric"}:
        return FieldKind.NUMBER
    if normalized in {"multiline", "textarea"}:
        return FieldKind.MULTILINE
    if normalized == "text":
        return FieldKind.TEXT
    return FieldKind.UNKNOWN
