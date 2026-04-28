from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
import re
from typing import Dict, List, Sequence

from formai.agents.base import BaseAgent
from formai.errors import IntegrationUnavailable, VisionProviderError
from formai.llm.base import VisionLLMClient
from formai.mapping import map_extracted_values_to_fields
from formai.models import (
    AcroField,
    ExtractionResult,
    FieldEvidence,
    FieldEvidenceCandidate,
    FieldValue,
    FieldKind,
    FilledDocumentTranscript,
    IssueSeverity,
    ProcessingIssue,
    RenderedPage,
    ReviewItem,
    TranscriptLine,
)
from formai.profiles import (
    STUDENT_PETITION_PROFILE,
    infer_profile_from_target_fields,
    normalize_structured_data_for_profile,
    profile_expected_keys,
)
from formai.postprocessing import apply_domain_postprocessing
from formai.pdf.cropper import crop_rendered_page
from formai.pdf.inspector import extract_non_empty_field_values
from formai.pdf.rasterizer import rasterize_pdf
from formai.segmentation import (
    coalesce_segmented_field_values,
    continuation_field_index,
    is_continuation_field_name,
    logical_field_name,
)
from formai.utils import average_confidence, derive_field_confidence, normalize_text
from formai.utils import strip_name_role_suffix, text_similarity

HONORIFIC_NAME_TOKEN_RE = re.compile(r"\b(?:mr|mrs|ms|miss|st|dr|sri|smt)\b", re.IGNORECASE)
TURKISH_YEAR_RANGE_RE = re.compile(r"\b((?:19|20)\d{2}\s*[-/.]\s*(?:19|20)\d{2})\b")
TURKISH_DATE_RE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-](?:19|20)?\d{2,4})\b")
TURKISH_SEMESTER_RE = re.compile(r"\b(g[üu]z|bahar|yaz)\b", re.IGNORECASE)
TURKISH_DEPARTMENT_TAIL_RE = re.compile(
    r"\b(b[öo]l[üu]m(?:[üu]ne)?|program(?:[ıi]na)?)\b.*$",
    re.IGNORECASE,
)
STUDENT_PETITION_ALWAYS_CROP_KEYS = {
    "tarih",
    "ogrenci_no",
    "fakulte_birim",
    "ad_soyad",
    "bolum_program",
    "egitim_yili",
    "yariyil",
    "ders_kodu",
    "ders_adi",
    "gno",
    "danisman_adi",
    "danisman_tarih_imza",
    "mali_onay_ders_akts",
    "mali_onay_ad_soyad",
    "mali_onay_tarih_imza",
}


class DataExtractorAgent(BaseAgent):
    def __init__(
        self,
        config,
        llm_client: VisionLLMClient,
        ocr_reader=None,
        perception_client=None,
        resolver_client=None,
    ):
        super().__init__(config)
        self.llm_client = llm_client
        self.ocr_reader = ocr_reader
        self.perception_client = perception_client or llm_client
        self.resolver_client = resolver_client or llm_client
        self.last_debug_trace: Dict[str, dict] = {}

    def extract(self, filled_pdf_path: Path, target_fields: Sequence[AcroField]) -> ExtractionResult:
        issues: List[ProcessingIssue] = []
        try:
            structured_data = self._extract_direct_field_values(filled_pdf_path)
        except IntegrationUnavailable as exc:
            issues.append(
                ProcessingIssue(
                    code="pdf.inspection.unavailable",
                    message=str(exc),
                    severity=IssueSeverity.WARNING,
                )
            )
            structured_data = {}
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="pdf.value_extraction.failed",
                    message=f"Direct PDF field extraction failed: {exc}",
                    severity=IssueSeverity.WARNING,
                )
            )
            structured_data = {}

        if structured_data:
            return self._build_extraction_result(
                source_path=filled_pdf_path,
                target_fields=target_fields,
                structured_data=structured_data,
                transcript=None,
                field_evidence=(),
                issues=issues,
            )

        try:
            rendered_pages = rasterize_pdf(filled_pdf_path, dpi=self.config.raster_dpi)
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="data.rasterization.failed",
                    message=f"Failed to rasterize input PDF: {exc}",
                    severity=IssueSeverity.ERROR,
                )
            )
            return ExtractionResult(
                source_path=filled_pdf_path,
                issues=issues,
                confidence=0.0,
            )

        return self.extract_from_rendered_pages(
            rendered_pages=rendered_pages,
            target_fields=target_fields,
            source_name=str(filled_pdf_path),
            initial_issues=issues,
        )

    def extract_from_rendered_pages(
        self,
        rendered_pages: Sequence[RenderedPage],
        target_fields: Sequence[AcroField],
        source_name: str,
        initial_issues: Sequence[ProcessingIssue] | None = None,
    ) -> ExtractionResult:
        issues: List[ProcessingIssue] = list(initial_issues or [])
        self.last_debug_trace = {}
        profile = infer_profile_from_target_fields(target_fields)
        transcript = self._build_transcript(rendered_pages)
        try:
            expected_keys = profile_expected_keys(target_fields, profile)
            structured_data = self._resolve_structured_data(
                rendered_pages=rendered_pages,
                expected_keys=expected_keys,
                transcript=transcript,
            )
        except (IntegrationUnavailable, RuntimeError, VisionProviderError) as exc:
            issues.append(
                ProcessingIssue(
                    code="data.extraction.failed",
                    message=str(exc),
                    severity=IssueSeverity.ERROR,
                )
            )
            return ExtractionResult(
                source_path=Path(source_name),
                issues=issues,
                confidence=0.0,
            )
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="data.extraction.unexpected_error",
                    message=f"Unexpected extraction failure: {exc}",
                    severity=IssueSeverity.ERROR,
                )
            )
            return ExtractionResult(
                source_path=Path(source_name),
                issues=issues,
                confidence=0.0,
            )

        self.last_debug_trace = self._seed_debug_trace(structured_data)
        structured_data = self._refine_checkbox_fields(rendered_pages, target_fields, structured_data)
        structured_data = self._refine_checkbox_groups(rendered_pages, target_fields, structured_data)
        structured_data = self._refine_with_field_crops(
            rendered_pages,
            target_fields,
            structured_data,
            debug_trace=self.last_debug_trace,
            profile=profile,
        )
        structured_data = self._suppress_low_ink_multiline_fields(
            rendered_pages,
            target_fields,
            structured_data,
        )
        field_evidence = self._build_field_evidence(
            target_fields=target_fields,
            structured_data=structured_data,
            transcript=transcript,
        )
        return self._build_extraction_result(
            source_path=Path(source_name),
            target_fields=target_fields,
            structured_data=structured_data,
            transcript=transcript,
            field_evidence=field_evidence,
            issues=issues,
            profile=profile,
        )

    def _extract_direct_field_values(self, filled_pdf_path: Path) -> Dict[str, FieldValue]:
        direct_values = coalesce_segmented_field_values(
            extract_non_empty_field_values(filled_pdf_path)
        )
        structured_data: Dict[str, FieldValue] = {}
        for field_name, value in direct_values.items():
            source_key = normalize_text(field_name).replace(" ", "_") or field_name
            structured_data[source_key] = FieldValue(
                value=value,
                confidence=0.99,
                source_key=source_key,
                raw_text=value,
                source_kind="pdf_direct",
            )
        return structured_data

    def _build_extraction_result(
        self,
        source_path: Path,
        target_fields: Sequence[AcroField],
        structured_data: Dict[str, FieldValue],
        issues: List[ProcessingIssue],
        transcript: FilledDocumentTranscript | None = None,
        field_evidence: Sequence[FieldEvidence] = (),
        profile: str | None = None,
    ) -> ExtractionResult:
        profile = profile or infer_profile_from_target_fields(target_fields)
        structured_data = normalize_structured_data_for_profile(structured_data, profile)
        structured_data = apply_domain_postprocessing(structured_data, profile=profile)
        self._update_selected_debug_values(structured_data)
        mappings = map_extracted_values_to_fields(
            structured_data, target_fields, self.config.min_mapping_confidence, profile=profile
        )
        low_confidence = [
            mapping
            for mapping in mappings
            if (
                mapping.confidence < self.config.min_mapping_confidence
                and "expected_empty"
                not in structured_data.get(mapping.source_key, FieldValue("", 0.0, mapping.source_key)).review_reasons
            )
        ]
        if low_confidence:
            issues.append(
                ProcessingIssue(
                    code="data.mapping.review_required",
                    message=f"{len(low_confidence)} extracted value(s) need manual review.",
                    severity=IssueSeverity.WARNING,
                )
            )
        review_items = self._build_review_items(structured_data, mappings)
        confidence = average_confidence(
            [value.confidence for value in structured_data.values()]
            + [mapping.confidence for mapping in mappings],
            default=0.0,
        )
        return ExtractionResult(
            source_path=source_path,
            structured_data=structured_data,
            mappings=mappings,
            review_items=review_items,
            transcript=transcript,
            transcript_summary=transcript.summary() if transcript is not None else {},
            field_evidence=list(field_evidence),
            issues=issues,
            confidence=confidence,
        )

    def _resolve_structured_data(
        self,
        *,
        rendered_pages: Sequence[RenderedPage],
        expected_keys: Sequence[str],
        transcript: FilledDocumentTranscript | None,
    ) -> Dict[str, FieldValue]:
        if transcript is not None:
            try:
                evidence_graph = self.resolver_client.resolve_field_evidence(transcript, expected_keys)
            except (IntegrationUnavailable, RuntimeError, VisionProviderError):
                evidence_graph = None
            except Exception:
                evidence_graph = None
            structured_from_evidence = self._structured_data_from_evidence_graph(evidence_graph)
            if structured_from_evidence:
                return structured_from_evidence
        return self.resolver_client.resolve_structured_data(rendered_pages, expected_keys)

    def _structured_data_from_evidence_graph(self, evidence_graph) -> Dict[str, FieldValue]:
        if evidence_graph is None:
            return {}
        evidences = list(getattr(evidence_graph, "field_evidence", []) or [])
        structured: Dict[str, FieldValue] = {}
        for evidence in evidences:
            key = str(getattr(evidence, "field_key", "")).strip()
            if not key:
                continue
            resolved_value = str(getattr(evidence, "resolved_value", "") or "")
            breakdown = dict(getattr(evidence, "confidence_breakdown", {}) or {})
            confidence = float(
                breakdown.get(
                    "selected",
                    breakdown.get("field_confidence", breakdown.get("overall", 0.0)),
                )
                or 0.0
            )
            raw_text = resolved_value
            ocr_candidates = list(getattr(evidence, "ocr_candidates", []) or [])
            if ocr_candidates:
                first = ocr_candidates[0]
                raw_text = str(getattr(first, "raw_text", "") or getattr(first, "value", "") or first)
            structured[key] = FieldValue(
                value=resolved_value,
                confidence=confidence,
                source_key=key,
                raw_text=raw_text or resolved_value,
                source_kind=str(getattr(evidence, "resolution_reason", "") or "resolver_evidence"),
            )
        return structured

    def _build_transcript(
        self,
        rendered_pages: Sequence[RenderedPage],
    ) -> FilledDocumentTranscript | None:
        if not rendered_pages:
            return None
        try:
            transcript = self.perception_client.build_document_transcript(rendered_pages)
        except Exception:
            transcript = None
        if transcript is not None and (
            getattr(transcript, "spans", None)
            or any(
                " ".join(str(getattr(span, "text", "")).split()).strip()
                for span in getattr(transcript, "spans", []) or []
            )
        ):
            page_texts: Dict[int, str] = {}
            grouped_lines: Dict[int, list[str]] = {}
            for span in getattr(transcript, "spans", []) or []:
                text = " ".join(str(getattr(span, "text", "")).split()).strip()
                if not text:
                    continue
                page_number = int(getattr(span, "page_number", 1))
                page_texts[page_number] = " ".join(
                    part for part in [page_texts.get(page_number, ""), text] if part
                ).strip()
                grouped_lines.setdefault(page_number, []).append(text)
            return FilledDocumentTranscript(
                provider=str(getattr(transcript, "provider", "") or "provider_transcript"),
                page_count=len(rendered_pages),
                page_texts=page_texts,
                lines=[
                    TranscriptLine(
                        page_number=page_number,
                        text=line,
                        confidence=float(getattr(transcript, "confidence", 0.0) or 0.0),
                    )
                    for page_number, lines in grouped_lines.items()
                    for line in lines
                ],
                confidence_map={
                    "provider_confidence": float(getattr(transcript, "confidence", 0.0) or 0.0)
                },
            )

        if self.ocr_reader is None:
            return FilledDocumentTranscript(
                provider="none",
                page_count=len(rendered_pages),
            )

        page_texts: Dict[int, str] = {}
        lines: list[TranscriptLine] = []
        for page in rendered_pages:
            try:
                text = self.ocr_reader.extract_text(page, psm=6)
            except Exception:
                text = ""
            page_texts[page.page_number] = text
            for line in [segment.strip() for segment in text.splitlines() if segment.strip()]:
                lines.append(
                    TranscriptLine(
                        page_number=page.page_number,
                        text=line,
                        confidence=0.55 if line else 0.0,
                    )
                )
        return FilledDocumentTranscript(
            provider="aux_ocr",
            page_count=len(rendered_pages),
            page_texts=page_texts,
            lines=lines,
            confidence_map={"ocr_confidence": 0.55 if lines else 0.0},
        )

    def _build_field_evidence(
        self,
        *,
        target_fields: Sequence[AcroField],
        structured_data: Dict[str, FieldValue],
        transcript: FilledDocumentTranscript | None,
    ) -> List[FieldEvidence]:
        evidence_items: List[FieldEvidence] = []
        transcript_page_texts = transcript.page_texts if transcript is not None else {}
        by_key: Dict[str, AcroField] = {}
        for field in target_fields:
            logical_key = logical_field_name(field.label or field.name)
            by_key.setdefault(logical_key, field)
            by_key.setdefault(field.name, field)

        for key, value in structured_data.items():
            field = by_key.get(key)
            candidate_regions = []
            page_number = 1
            if field is not None:
                page_number = field.page_number
                if field.box is not None:
                    candidate_regions.append(field.box)
            debug_entry = self.last_debug_trace.get(key, {})
            ocr_candidates: list[FieldEvidenceCandidate] = []
            raw_candidates = [
                (value.raw_text, value.source_kind, value.confidence),
                (str(debug_entry.get("page_value", "")), "page_candidate", 0.45),
                (str(debug_entry.get("page_precision_value", "")), "page_precision", 0.5),
                (str(debug_entry.get("crop_value", "")), "crop_candidate", 0.55),
                (str(debug_entry.get("crop_precision_value", "")), "crop_precision", 0.6),
            ]
            seen = set()
            for raw_text, source, confidence in raw_candidates:
                normalized = raw_text.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                ocr_candidates.append(
                    FieldEvidenceCandidate(
                        value=normalized,
                        source=source,
                        confidence=float(confidence),
                        region=field.box if field is not None else None,
                        raw_text=normalized,
                    )
                )
            page_text = transcript_page_texts.get(page_number, "").strip()
            resolution_reason = value.source_kind
            if page_text:
                resolution_reason = f"{value.source_kind}+transcript"
            evidence_items.append(
                FieldEvidence(
                    field_key=key,
                    page_number=page_number,
                    anchor_ref=field.name if field is not None else key,
                    candidate_regions=candidate_regions,
                    ocr_candidates=ocr_candidates,
                    resolved_value=value.value,
                    resolution_reason=resolution_reason,
                    confidence_breakdown={
                        "selected": value.confidence,
                        "candidate_count": float(len(ocr_candidates)),
                        "transcript_available": 1.0 if page_text else 0.0,
                    },
                )
            )
        return evidence_items

    def _refine_with_field_crops(
        self,
        rendered_pages: Sequence[RenderedPage],
        target_fields: Sequence[AcroField],
        structured_data: Dict[str, FieldValue],
        debug_trace: Dict[str, dict] | None = None,
        profile: str | None = None,
    ) -> Dict[str, FieldValue]:
        if not rendered_pages:
            return structured_data

        page_map = {page.page_number: page for page in rendered_pages}
        crop_targets = self._crop_targets_by_key(target_fields)
        if not crop_targets:
            return structured_data

        refined = apply_domain_postprocessing(structured_data, profile=profile)
        refined, segment_improved_keys = self._refine_multiline_with_segment_crops(
            rendered_pages,
            target_fields,
            refined,
            debug_trace=debug_trace,
        )
        value_counts = self._normalized_value_counts(refined)
        for key, field in crop_targets.items():
            if key in segment_improved_keys:
                continue
            current = refined.get(key) or refined.get(logical_field_name(field.name))
            current_value = current.value if current else ""
            if not self._should_try_field_crop(field, current_value, value_counts, profile=profile):
                continue
            page = page_map.get(field.page_number)
            if page is None or field.box is None:
                continue
            try:
                cropped_page = self._crop_page_for_field(page, field)
                ocr_hint = self._crop_ocr_hint(field, cropped_page)
                if ocr_hint:
                    cropped_values = self.llm_client.extract_structured_data_with_hint(
                        [cropped_page],
                        [key],
                        ocr_hint,
                    )
                else:
                    cropped_values = self.llm_client.extract_structured_data([cropped_page], [key])
            except (IntegrationUnavailable, RuntimeError, VisionProviderError):
                continue
            except Exception:
                continue

            self._record_llm_debug(debug_trace, key, stage="crop")

            candidate = cropped_values.get(key)
            if candidate is None:
                normalized_key = normalize_text(key)
                for candidate_key, candidate_value in cropped_values.items():
                    if normalize_text(candidate_key) == normalized_key:
                        candidate = candidate_value
                        break
            if candidate is None:
                continue
            candidate_value = self._normalize_profile_crop_candidate(
                key,
                candidate.value,
                ocr_hint,
                profile=profile,
            )
            if self._is_crop_value_better(field, current_value, candidate_value, profile=profile):
                target_key = key if key in refined or logical_field_name(field.name) not in refined else logical_field_name(field.name)
                refined[target_key] = self._mark_crop_candidate(
                    field,
                    replace(candidate, value=candidate_value, raw_text=candidate_value or candidate.raw_text),
                    ocr_hint=bool(ocr_hint),
                )
        return apply_domain_postprocessing(refined, profile=profile)

    def _refine_multiline_with_segment_crops(
        self,
        rendered_pages: Sequence[RenderedPage],
        target_fields: Sequence[AcroField],
        structured_data: Dict[str, FieldValue],
        debug_trace: Dict[str, dict] | None = None,
    ) -> tuple[Dict[str, FieldValue], set[str]]:
        page_map = {page.page_number: page for page in rendered_pages}
        refined = dict(structured_data)
        improved_keys: set[str] = set()

        for key, fields in self._multiline_segment_groups(target_fields).items():
            current = refined.get(key)
            current_value = current.value if current else ""
            if not self._should_try_multiline_segment_crops(key, current_value):
                continue
            segment_fields = [field for field in fields if is_continuation_field_name(field.name)]
            if not segment_fields:
                continue
            segment_limit = max(1, int(getattr(self.config, "max_multiline_segment_crops", 2) or 1))
            segment_fields = segment_fields[-segment_limit:]
            segment_values: List[str] = [current_value] if current_value.strip() else []
            used_ocr_hint = False
            for field in segment_fields:
                page = page_map.get(field.page_number)
                if page is None or field.box is None:
                    continue
                try:
                    cropped_page = self._crop_page_for_field(page, field)
                    ocr_hint = self._crop_ocr_hint(field, cropped_page)
                    if ocr_hint:
                        cropped_values = self.llm_client.extract_structured_data_with_hint(
                            [cropped_page],
                            [key],
                            ocr_hint,
                        )
                        used_ocr_hint = True
                    else:
                        cropped_values = self.llm_client.extract_structured_data([cropped_page], [key])
                except (IntegrationUnavailable, RuntimeError, VisionProviderError):
                    continue
                except Exception:
                    continue

                self._record_llm_debug(debug_trace, key, stage="crop")

                candidate = cropped_values.get(key)
                if candidate is None:
                    normalized_key = normalize_text(key)
                    for candidate_key, candidate_value in cropped_values.items():
                        if normalize_text(candidate_key) == normalized_key:
                            candidate = candidate_value
                            break
                if candidate is None or not candidate.value.strip():
                    continue
                segment_values.append(candidate.value)

            if len(segment_values) <= 1:
                continue
            combined_value = self._combine_multiline_segment_values(segment_values)
            if not self._is_multiline_crop_better(current_value, combined_value):
                continue
            if current is None:
                refined[key] = FieldValue(
                    value=combined_value,
                    confidence=derive_field_confidence(
                        "llm_crop_ocr_hint" if used_ocr_hint else "llm_crop",
                        combined_value,
                    ),
                    source_key=key,
                    raw_text=combined_value,
                    source_kind="llm_crop_ocr_hint" if used_ocr_hint else "llm_crop",
                )
            else:
                refined[key] = self._mark_crop_candidate(fields[0], replace(current, value=combined_value, raw_text=combined_value), ocr_hint=used_ocr_hint)
            improved_keys.add(key)
        return refined, improved_keys

    def _seed_debug_trace(self, structured_data: Dict[str, FieldValue]) -> Dict[str, dict]:
        trace: Dict[str, dict] = {}
        llm_trace = getattr(self.llm_client, "last_debug_trace", {}) or {}
        for key, value in structured_data.items():
            llm_entry = llm_trace.get(key, {})
            trace[key] = {
                "page_value": value.value,
                "page_precision_value": llm_entry.get("precision_value", ""),
                "crop_value": "",
                "crop_precision_value": "",
                "selected_value": value.value,
                "source_kind": value.source_kind,
            }
        return trace

    def _record_llm_debug(self, debug_trace: Dict[str, dict] | None, key: str, stage: str) -> None:
        if debug_trace is None:
            return
        llm_trace = getattr(self.llm_client, "last_debug_trace", {}) or {}
        entry = llm_trace.get(key, {})
        if key not in debug_trace:
            debug_trace[key] = {
                "page_value": "",
                "page_precision_value": "",
                "crop_value": "",
                "crop_precision_value": "",
                "selected_value": "",
                "source_kind": "",
            }
        if stage == "crop":
            debug_trace[key]["crop_value"] = entry.get("final_value", "")
            debug_trace[key]["crop_precision_value"] = entry.get("precision_value", "")

    def _update_selected_debug_values(self, structured_data: Dict[str, FieldValue]) -> None:
        for key, value in structured_data.items():
            entry = self.last_debug_trace.setdefault(
                key,
                {
                    "page_value": "",
                    "page_precision_value": "",
                    "crop_value": "",
                    "crop_precision_value": "",
                    "selected_value": "",
                    "source_kind": "",
                },
            )
            entry["selected_value"] = value.value
            entry["source_kind"] = value.source_kind

    def _crop_targets_by_key(self, target_fields: Sequence[AcroField]) -> Dict[str, AcroField]:
        targets: Dict[str, AcroField] = {}
        for field in target_fields:
            if field.box is None:
                continue
            if field.field_kind == FieldKind.CHECKBOX:
                key = field.label or field.name
            else:
                key = logical_field_name(field.label or field.name)
            if not key:
                continue
            existing = targets.get(key)
            if existing is None:
                targets[key] = field
                continue
            if existing.box is None:
                targets[key] = field
                continue
            targets[key] = AcroField(
                name=existing.name,
                field_kind=existing.field_kind,
                box=self._merge_boxes(existing.box, field.box),
                page_number=existing.page_number,
                value=existing.value,
                label=existing.label or field.label,
            )
        return targets

    def _multiline_segment_groups(self, target_fields: Sequence[AcroField]) -> Dict[str, List[AcroField]]:
        groups: Dict[str, List[AcroField]] = {}
        for field in target_fields:
            if field.box is None or field.field_kind == FieldKind.CHECKBOX:
                continue
            logical_name = logical_field_name(field.name)
            normalized = normalize_text(field.label or field.name)
            if not any(token in normalized for token in ("describe", "contact info")):
                continue
            if not is_continuation_field_name(field.name) and not any(
                other.name.startswith(f"{field.name}__body") for other in target_fields
            ):
                continue
            groups.setdefault(logical_name, []).append(field)

        for logical_name, fields in groups.items():
            groups[logical_name] = sorted(
                fields,
                key=lambda field: (
                    0 if field.name == logical_name else 1,
                    continuation_field_index(field.name),
                ),
            )
        return groups

    def _should_try_field_crop(
        self,
        field: AcroField,
        current_value: str,
        value_counts: Dict[str, int],
        profile: str | None = None,
    ) -> bool:
        if field.field_kind == FieldKind.CHECKBOX:
            return False
        normalized_label = normalize_text(field.label or field.name)
        logical_name = logical_field_name(field.name)
        if profile == STUDENT_PETITION_PROFILE and logical_name in STUDENT_PETITION_ALWAYS_CROP_KEYS:
            return True
        if not current_value.strip():
            return True
        if "date" in normalized_label:
            return value_counts.get(normalize_text(current_value), 0) > 1
        if normalized_label == "year":
            return True
        if "statutes" in normalized_label:
            return True
        if any(token in normalized_label for token in ("fax", "phone")):
            return True
        if "complainant name" in normalized_label:
            return True
        if any(token in normalized_label for token in ("police station", "station")):
            return True
        if any(token in normalized_label for token in ("address", "comments", "description", "copies", "approval", "termination")):
            return True
        if any(token in normalized_label for token in ("company", "supplier", "position")):
            return True
        return self._looks_like_short_code(current_value)

    def _is_crop_value_better(
        self,
        field: AcroField,
        current_value: str,
        candidate_value: str,
        profile: str | None = None,
    ) -> bool:
        if not candidate_value.strip():
            return False
        if not current_value.strip():
            return True
        if normalize_text(candidate_value) == normalize_text(current_value):
            return False

        normalized_label = normalize_text(field.label or field.name)
        logical_name = logical_field_name(field.name)
        if profile == STUDENT_PETITION_PROFILE and logical_name in STUDENT_PETITION_ALWAYS_CROP_KEYS:
            return self._is_better_student_petition_crop(
                logical_name=logical_name,
                current_value=current_value,
                candidate_value=candidate_value,
            )
        if "date" in normalized_label:
            return self._is_date_like(candidate_value)
        if normalized_label == "year":
            return bool(re.fullmatch(r"(?:19|20)\d{2}", " ".join(candidate_value.split()).strip()))
        if "statutes" in normalized_label:
            candidate_score = self._text_density_score(candidate_value)
            current_score = self._text_density_score(current_value)
            if "/" in candidate_value and "/" not in current_value:
                return True
            return candidate_score >= current_score
        if "termination" in normalized_label:
            return candidate_value.strip().lower() == "permanent"
        if "approval" in normalized_label:
            return not candidate_value.strip().isdigit()
        if "complainant name" in normalized_label:
            return self._is_better_name_crop(current_value, candidate_value)
        if "police station" in normalized_label or normalized_label.endswith("station"):
            return self._is_better_station_crop(current_value, candidate_value)
        if any(token in normalized_label for token in ("fax", "phone")):
            return self._digit_count(candidate_value) >= self._digit_count(current_value)
        if any(token in normalized_label for token in ("address", "comments", "description", "copies")):
            return self._text_density_score(candidate_value) > self._text_density_score(current_value)
        if any(token in normalized_label for token in ("company", "supplier", "position")):
            return self._looks_like_short_code(candidate_value)
        return False

    def _is_better_student_petition_crop(
        self,
        *,
        logical_name: str,
        current_value: str,
        candidate_value: str,
    ) -> bool:
        current_compact = " ".join((current_value or "").split())
        candidate_compact = " ".join((candidate_value or "").split())
        if not candidate_compact:
            return False
        if not current_compact:
            return True
        if logical_name == "ogrenci_no":
            return bool(re.fullmatch(r"\d{8,14}", candidate_compact))
        if logical_name in {"egitim_yili", "yariyil", "fakulte_birim"}:
            return True
        if logical_name == "ad_soyad":
            candidate_tokens = [token for token in candidate_compact.split() if any(ch.isalpha() for ch in token)]
            return 2 <= len(candidate_tokens) <= 4
        if logical_name in {"danisman_adi", "mali_onay_ad_soyad"}:
            return self._is_better_name_crop(current_compact, candidate_compact)
        if logical_name == "bolum_program":
            if "numara" in normalize_text(current_compact) or "yariyil" in normalize_text(current_compact):
                return True
            return len(candidate_compact) >= max(8, len(current_compact) - 4)
        if logical_name == "gno":
            current_match = re.search(r"\b\d\.\d{1,2}\b", current_compact.replace(",", "."))
            candidate_match = re.search(r"\b\d\.\d{1,2}\b", candidate_compact.replace(",", "."))
            if candidate_match and not current_match:
                return True
            if candidate_match and current_match:
                return len(candidate_match.group(0)) >= len(current_match.group(0))
            return False
        if logical_name in {"danisman_tarih_imza", "mali_onay_tarih_imza", "mali_onay_ders_akts"}:
            return len(candidate_compact) >= len(current_compact)
        return False

    def _normalize_profile_crop_candidate(
        self,
        key: str,
        candidate_value: str,
        ocr_hint: str,
        *,
        profile: str | None,
    ) -> str:
        if profile != STUDENT_PETITION_PROFILE:
            return candidate_value.strip()
        key = logical_field_name(key)
        sources = [candidate_value or "", ocr_hint or ""]
        if key == "ogrenci_no":
            for source in sources:
                match = re.search(r"\b\d{8,14}\b", source)
                if match:
                    return match.group(0)
        if key == "egitim_yili":
            for source in sources:
                match = TURKISH_YEAR_RANGE_RE.search(source)
                if match:
                    return re.sub(r"\s+", "", match.group(1)).replace(".", "-").replace("/", "-")
        if key == "yariyil":
            for source in sources:
                match = TURKISH_SEMESTER_RE.search(normalize_text(source))
                if match:
                    token = match.group(1).lower()
                    return "Güz" if token.startswith("g") else token.capitalize()
        if key in {"tarih", "danisman_tarih_imza", "mali_onay_tarih_imza"}:
            for source in sources:
                match = TURKISH_DATE_RE.search(source)
                if match:
                    date = match.group(1).replace("/", ".").replace("-", ".")
                    if key == "tarih":
                        return date
                    suffix = source[match.end() :].strip(" /|-")
                    return f"{date} / {suffix}".strip() if suffix else date
        if key in {"ad_soyad", "danisman_adi", "mali_onay_ad_soyad"}:
            cleaned = candidate_value.strip()
            cleaned = re.sub(r"^(?:adı ve soyadı|ad soyad|danışmanın adı|adi soyadi)\s*:?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = cleaned.strip(" .:-")
            if len(cleaned.split()) < 2 and ocr_hint:
                name_match = re.search(
                    r"([A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+){1,3})",
                    ocr_hint,
                )
                if name_match:
                    cleaned = name_match.group(1)
            if cleaned:
                return cleaned
        if key == "fakulte_birim":
            cleaned = candidate_value.strip().strip("- ")
            if "Fak" in cleaned or "fak" in cleaned:
                return cleaned.replace("Fakultesi", "Fakültesi")
        if key == "bolum_program":
            merged = ocr_hint or candidate_value
            merged = merged.strip().strip("- ")
            merged = re.sub(r"^[^\wçğıöşüÇĞİÖŞÜ]+", "", merged)
            match = re.search(
                r"([A-Za-zÇĞİÖŞÜçğıöşü]+\s+[A-Za-zÇĞİÖŞÜçğıöşü]+(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü]+)?)\s+B[öo]l[üu]m",
                merged,
                re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()
            merged = TURKISH_DEPARTMENT_TAIL_RE.sub("", merged).strip(" .,:;-")
            if merged:
                return merged.replace("Prmaramına", "").replace("Proaramına", "").strip()
        if key == "gno":
            compact = (candidate_value or ocr_hint).replace(",", ".")
            match = re.search(r"\b\d\.\d{1,2}\b", compact)
            if match:
                return match.group(0)
        if key == "mali_onay_ders_akts":
            compact = candidate_value or ocr_hint
            match = re.search(r"\b([A-ZÇĞİÖŞÜ]{2,5}\s*\d{2,4}\s*/\s*\d{1,2})\b", compact, re.IGNORECASE)
            if match:
                return match.group(1).replace("BIL", "BİL")
        return candidate_value.strip()

    def _text_density_score(self, value: str) -> tuple[int, int, int]:
        compact = " ".join((value or "").split())
        digits = sum(character.isdigit() for character in compact)
        return (len(compact.split()), digits, len(compact))

    def _combine_multiline_segment_values(self, values: Sequence[str]) -> str:
        combined = ""
        for value in values:
            cleaned = "\n".join(line.strip() for line in value.splitlines() if line.strip()).strip()
            if not cleaned:
                continue
            combined = self._merge_multiline_pair(combined, cleaned)
        return combined.strip()

    def _is_multiline_crop_better(self, current_value: str, candidate_value: str) -> bool:
        if not candidate_value.strip():
            return False
        if not current_value.strip():
            return True
        current_norm = normalize_text(current_value)
        candidate_norm = normalize_text(candidate_value)
        if not candidate_norm or candidate_norm == current_norm:
            return False
        if candidate_norm.startswith(current_norm) and len(candidate_norm) > len(current_norm):
            return True
        if self._contact_signal_count(candidate_value) > self._contact_signal_count(current_value):
            return True
        if self._normalized_word_growth(current_value, candidate_value) >= 4:
            return True
        current_lines = [line for line in current_value.splitlines() if line.strip()]
        candidate_lines = [line for line in candidate_value.splitlines() if line.strip()]
        if len(candidate_lines) > len(current_lines) and self._text_density_score(candidate_value) >= self._text_density_score(current_value):
            return True
        return False

    def _should_try_multiline_segment_crops(self, key: str, current_value: str) -> bool:
        normalized_key = normalize_text(key)
        if "describe" not in normalized_key and "contact info" not in normalized_key:
            return False
        if not current_value.strip():
            return "contact info" in normalized_key
        if "\n" in current_value:
            return True
        if "contact info" in normalized_key:
            return True
        return len(current_value.strip()) >= 140

    def _is_better_name_crop(self, current_value: str, candidate_value: str) -> bool:
        candidate_clean = strip_name_role_suffix(candidate_value)
        current_clean = strip_name_role_suffix(current_value)
        candidate_tokens = [token for token in candidate_clean.split() if any(char.isalpha() for char in token)]
        if not (2 <= len(candidate_tokens) <= 4):
            return False
        if any(char.isdigit() for char in candidate_clean):
            return False
        current_compact = " ".join((current_value or "").split())
        if HONORIFIC_NAME_TOKEN_RE.search(current_compact):
            return True
        similarity = text_similarity(candidate_clean, current_clean or current_value)
        current_has_role_suffix = normalize_text(current_value) != normalize_text(current_clean)
        if current_has_role_suffix and similarity >= 0.58 and len(candidate_clean) <= len(current_value):
            return True
        return similarity >= 0.82 and len(candidate_clean) <= len(current_value) + 4

    def _is_better_station_crop(self, current_value: str, candidate_value: str) -> bool:
        candidate_score = self._station_value_score(candidate_value)
        current_score = self._station_value_score(current_value)
        if candidate_score <= 0:
            return False
        if current_score <= 0:
            return True
        current_norm = normalize_text(current_value)
        if any(token in current_norm for token in ("form", "station", "police")) and candidate_score > current_score:
            return True
        return candidate_score >= current_score + 2

    def _station_value_score(self, value: str) -> int:
        compact = " ".join((value or "").split())
        normalized = normalize_text(compact)
        if not normalized:
            return 0
        tokens = normalized.split()
        noise_tokens = {"cr", "pc", "ipc", "ps", "gp", "pp", "form", "year", "police", "station"}
        score = sum(2 for token in tokens if token.isalpha() and len(token) >= 4 and token not in noise_tokens)
        score += sum(1 for token in tokens if token.isalpha() and len(token) == 3 and token not in noise_tokens)
        score -= sum(2 for token in tokens if token.isdigit())
        score -= sum(2 for token in tokens if len(token) == 1)
        score -= sum(2 for token in tokens if token in noise_tokens)
        if "." in compact and sum(part.isalpha() and len(part) <= 2 for part in compact.replace("/", " ").split(".")) >= 2:
            score -= 3
        if normalized.count("airport") >= 1:
            score += 2
        return score

    def _merge_multiline_pair(self, existing: str, candidate: str) -> str:
        if not existing.strip():
            return candidate
        existing_norm = normalize_text(existing)
        candidate_norm = normalize_text(candidate)
        if not candidate_norm:
            return existing
        if candidate_norm in existing_norm:
            return existing
        if existing_norm in candidate_norm:
            return candidate

        existing_lines = [line.strip() for line in existing.splitlines() if line.strip()]
        candidate_lines = [line.strip() for line in candidate.splitlines() if line.strip()]
        if not existing_lines:
            return candidate
        if not candidate_lines:
            return existing

        merged_lines = list(existing_lines)
        first_candidate = candidate_lines[0]
        overlap_words = self._overlap_suffix_prefix_words(merged_lines[-1], first_candidate)
        if overlap_words:
            existing_words = merged_lines[-1].split()
            candidate_words = first_candidate.split()
            merged_lines[-1] = " ".join(existing_words + candidate_words[overlap_words:])
            candidate_lines = candidate_lines[1:]

        seen_norms = {normalize_text(line) for line in merged_lines}
        for line in candidate_lines:
            line_norm = normalize_text(line)
            if not line_norm or line_norm in seen_norms:
                continue
            if (
                merged_lines
                and self._contact_signal_count(line) <= self._contact_signal_count(merged_lines[-1])
                and self._overlap_suffix_prefix_words(merged_lines[-1], line) == 0
                and text_similarity(merged_lines[-1], line) < 0.28
            ):
                continue
            seen_norms.add(line_norm)
            merged_lines.append(line)
        return "\n".join(merged_lines).strip()

    def _overlap_suffix_prefix_words(self, left: str, right: str) -> int:
        left_words = normalize_text(left).split()
        right_words = normalize_text(right).split()
        max_overlap = min(len(left_words), len(right_words), 8)
        for size in range(max_overlap, 2, -1):
            if left_words[-size:] == right_words[:size]:
                return size
        return 0

    def _contact_signal_count(self, value: str) -> int:
        compact = value or ""
        return len(re.findall(r"@", compact)) + len(re.findall(r"(?:\+?\d[\d()\-\s]{6,}\d)", compact))

    def _normalized_word_growth(self, current_value: str, candidate_value: str) -> int:
        current_words = set(normalize_text(current_value).split())
        candidate_words = set(normalize_text(candidate_value).split())
        return len(candidate_words - current_words)

    def _normalized_value_counts(self, values: Dict[str, FieldValue]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in values.values():
            normalized = normalize_text(item.value)
            if not normalized:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1
        return counts

    def _crop_ocr_hint(self, field: AcroField, cropped_page: RenderedPage) -> str:
        if self.ocr_reader is None:
            return ""
        try:
            psms = self._crop_ocr_psms(field)
            hints = []
            for psm in psms:
                text = self.ocr_reader.extract_text(cropped_page, psm=psm)
                cleaned = " ".join(text.split())
                if cleaned and cleaned not in hints:
                    hints.append(cleaned)
            return " | ".join(hints[:2])
        except Exception:
            return ""

    def _crop_ocr_psms(self, field: AcroField) -> list[int]:
        normalized_label = normalize_text(field.label or field.name)
        if "date" in normalized_label:
            return [7, 6]
        if normalized_label == "year":
            return [7, 13]
        if "statutes" in normalized_label:
            return [7, 6]
        if any(token in normalized_label for token in ("fax", "phone")):
            return [7, 13]
        if any(token in normalized_label for token in ("company", "supplier", "position")):
            return [11, 7]
        if "complainant name" in normalized_label:
            return [7, 6]
        return [6]

    def _looks_like_short_code(self, value: str) -> bool:
        compact = " ".join((value or "").split())
        if not compact or len(compact) > 16:
            return False
        if self._is_date_like(compact):
            return False
        return any(mark in compact for mark in ("/", ".", "-"))

    def _mark_crop_candidate(
        self,
        field: AcroField,
        candidate: FieldValue,
        ocr_hint: bool,
    ) -> FieldValue:
        review_reasons = list(candidate.review_reasons)
        normalized_label = normalize_text(field.label or field.name)
        if ocr_hint and "ocr_confusion_risk" not in review_reasons:
            review_reasons.append("ocr_confusion_risk")
        if "date" in normalized_label and "ambiguous_date_family" not in review_reasons:
            review_reasons.append("ambiguous_date_family")
        source_kind = "llm_crop_ocr_hint" if ocr_hint else "llm_crop"
        return FieldValue(
            value=candidate.value,
            confidence=derive_field_confidence(source_kind, candidate.value, review_reasons),
            source_key=candidate.source_key,
            raw_text=candidate.raw_text,
            source_kind=source_kind,
            review_reasons=review_reasons,
        )

    def _build_review_items(
        self,
        structured_data: Dict[str, FieldValue],
        mappings,
    ) -> List[ReviewItem]:
        review_items: List[ReviewItem] = []
        seen = set()

        for key, field_value in structured_data.items():
            raw_reasons = list(field_value.review_reasons)
            reasons = [reason for reason in raw_reasons if reason != "expected_empty"]
            if (
                not field_value.value.strip()
                and "expected_empty" not in raw_reasons
                and "missing_value" not in reasons
            ):
                reasons.append("missing_value")
            for reason_code in reasons:
                marker = (key, reason_code)
                if marker in seen:
                    continue
                seen.add(marker)
                review_items.append(
                    ReviewItem(
                        field_key=key,
                        predicted_value=field_value.value,
                        confidence=field_value.confidence,
                        reason_code=reason_code,
                        raw_text=field_value.raw_text,
                        source_kind=field_value.source_kind,
                    )
                )

        for mapping in mappings:
            if mapping.confidence >= self.config.min_mapping_confidence:
                continue
            field_value = structured_data.get(mapping.source_key)
            if field_value is None or "expected_empty" in field_value.review_reasons:
                continue
            marker = (mapping.source_key, "low_mapping_confidence")
            if marker in seen:
                continue
            seen.add(marker)
            review_items.append(
                ReviewItem(
                    field_key=mapping.source_key,
                    predicted_value=field_value.value,
                    confidence=mapping.confidence,
                    reason_code="low_mapping_confidence",
                    raw_text=field_value.raw_text,
                    source_kind=field_value.source_kind,
                )
            )

        return review_items

    def _is_date_like(self, value: str) -> bool:
        compact = " ".join((value or "").split())
        if not compact:
            return False
        if compact.lower() == "permanent":
            return True
        import re

        if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", compact):
            return True
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", compact):
            return True
        return False

    def _digit_count(self, value: str) -> int:
        return sum(character.isdigit() for character in value or "")

    def _crop_page_for_field(self, page: RenderedPage, field: AcroField) -> RenderedPage:
        normalized_label = normalize_text(field.label or field.name)
        if "police station" in normalized_label or normalized_label.endswith("station"):
            return crop_rendered_page(
                page,
                field.box,
                context_pixels=16,
                horizontal_pad_ratio=0.80,
                vertical_pad_ratio=0.25,
                extra_left_ratio=0.55,
            )
        if normalized_label == "year":
            return crop_rendered_page(
                page,
                field.box,
                context_pixels=4,
                horizontal_pad_ratio=0.01,
                vertical_pad_ratio=0.02,
                extra_left_ratio=0.0,
            )
        if "statutes" in normalized_label:
            return crop_rendered_page(
                page,
                field.box,
                context_pixels=4,
                horizontal_pad_ratio=0.01,
                vertical_pad_ratio=0.02,
                extra_left_ratio=0.0,
            )
        if "complainant name" in normalized_label:
            return crop_rendered_page(
                page,
                field.box,
                context_pixels=8,
                horizontal_pad_ratio=0.03,
                vertical_pad_ratio=0.10,
                extra_left_ratio=0.02,
            )
        if any(token in normalized_label for token in ("address", "description", "copies")):
            return crop_rendered_page(
                page,
                field.box,
                context_pixels=40,
                horizontal_pad_ratio=0.18,
                vertical_pad_ratio=0.35,
                extra_left_ratio=0.40,
            )
        if any(token in normalized_label for token in ("termination", "comments", "fax", "phone")):
            return crop_rendered_page(
                page,
                field.box,
                context_pixels=32,
                horizontal_pad_ratio=0.18,
                vertical_pad_ratio=0.30,
                extra_left_ratio=0.36,
            )
        return crop_rendered_page(page, field.box)

    def _refine_checkbox_fields(
        self,
        rendered_pages: Sequence[RenderedPage],
        target_fields: Sequence[AcroField],
        structured_data: Dict[str, FieldValue],
    ) -> Dict[str, FieldValue]:
        if not rendered_pages:
            return structured_data

        page_map = {page.page_number: page for page in rendered_pages}
        refined = dict(structured_data)
        for field in target_fields:
            if field.field_kind != FieldKind.CHECKBOX or field.box is None:
                continue
            page = page_map.get(field.page_number)
            if page is None:
                continue
            checked, confidence = self._detect_checkbox_state(page, field.box)
            if checked is None:
                continue
            key = field.label or field.name
            target_key = key if key in refined or field.name not in refined else field.name
            refined[target_key] = FieldValue(
                value="yes" if checked else "",
                confidence=confidence,
                source_key=target_key,
                raw_text="checked" if checked else "unchecked",
                source_kind="checkbox_pixel",
            )
        return refined

    def _suppress_low_ink_multiline_fields(
        self,
        rendered_pages: Sequence[RenderedPage],
        target_fields: Sequence[AcroField],
        structured_data: Dict[str, FieldValue],
    ) -> Dict[str, FieldValue]:
        if not rendered_pages:
            return structured_data

        page_map = {page.page_number: page for page in rendered_pages}
        crop_targets = self._crop_targets_by_key(target_fields)
        refined = dict(structured_data)
        for key, field in crop_targets.items():
            if field.field_kind not in {FieldKind.MULTILINE, FieldKind.TEXT}:
                continue
            normalized_label = normalize_text(field.label or field.name)
            if not any(token in normalized_label for token in ("describe", "contact info")):
                continue
            current = refined.get(key) or refined.get(logical_field_name(field.name))
            if current is None or not current.value.strip():
                continue
            page = page_map.get(field.page_number)
            if page is None or field.box is None:
                continue
            ink_ratio = self._field_ink_ratio(page, field.box)
            if ink_ratio >= 0.010:
                continue
            review_reasons = [reason for reason in current.review_reasons if reason != "ocr_confusion_risk"]
            if "missing_value" not in review_reasons:
                review_reasons.append("missing_value")
            target_key = key if key in refined else logical_field_name(field.name)
            refined[target_key] = FieldValue(
                value="",
                confidence=0.0,
                source_key=current.source_key,
                raw_text="",
                source_kind=current.source_kind,
                review_reasons=review_reasons,
            )
        return refined

    def _refine_checkbox_groups(
        self,
        rendered_pages: Sequence[RenderedPage],
        target_fields: Sequence[AcroField],
        structured_data: Dict[str, FieldValue],
    ) -> Dict[str, FieldValue]:
        if not rendered_pages:
            return structured_data

        page_map = {page.page_number: page for page in rendered_pages}
        refined = dict(structured_data)
        for _, group_fields in self._checkbox_groups(target_fields).items():
            if len(group_fields) < 2:
                continue
            keys = []
            for field in group_fields:
                key = (field.label or field.name)
                key = key if key in refined or field.name not in refined else field.name
                keys.append(key)
            page = page_map.get(group_fields[0].page_number)
            if page is None:
                continue
            blue_choice = self._resolve_checkbox_group_by_blue_score(page, group_fields, keys)
            if blue_choice:
                for key in keys:
                    checked = key == blue_choice
                    refined[key] = FieldValue(
                        value="yes" if checked else "",
                        confidence=0.84 if checked else 0.80,
                        source_key=key,
                        raw_text="blue_mark" if checked else "blue_unchecked",
                        source_kind="checkbox_blue_search",
                    )
                continue
            mark_choice = self._resolve_checkbox_group_by_mark_score(page, group_fields, keys)
            if mark_choice:
                for key in keys:
                    checked = key == mark_choice
                    refined[key] = FieldValue(
                        value="yes" if checked else "",
                        confidence=0.92 if checked else 0.86,
                        source_key=key,
                        raw_text="black_mark" if checked else "black_unchecked",
                        source_kind="checkbox_mark_group",
                    )
                continue
            selected = [key for key in keys if refined.get(key) and refined[key].value.strip()]
            if len(selected) == 1 and not any(key.endswith("_selected") for key in keys):
                continue
            first = group_fields[0]
            if first.box is None:
                continue
            merged_box = group_fields[0].box
            for field in group_fields[1:]:
                if field.box is not None:
                    merged_box = self._merge_boxes(merged_box, field.box)
            if merged_box is None:
                continue
            try:
                crop = crop_rendered_page(
                    page,
                    merged_box,
                    context_pixels=32,
                    horizontal_pad_ratio=0.30,
                    vertical_pad_ratio=0.42,
                    extra_left_ratio=1.40,
                )
                candidates = self.llm_client.extract_structured_data([crop], keys)
            except (IntegrationUnavailable, RuntimeError, VisionProviderError):
                continue
            except Exception:
                continue

            normalized = {}
            for key in keys:
                candidate = candidates.get(key)
                if candidate is None:
                    continue
                checked = self._coerce_checkbox_candidate(key, candidate.value)
                if checked is None:
                    continue
                normalized[key] = checked
            if sum(1 for checked in normalized.values() if checked) != 1:
                continue
            for key in keys:
                checked = normalized.get(key, False)
                refined[key] = FieldValue(
                    value="yes" if checked else "",
                    confidence=0.76 if checked else 0.72,
                    source_key=key,
                    raw_text=candidates.get(key).raw_text if candidates.get(key) is not None else "",
                    source_kind="llm_crop_checkbox",
                )
        return refined

    def _detect_checkbox_state(self, page: RenderedPage, box) -> tuple[bool | None, float]:
        try:
            from PIL import Image
        except ImportError:
            return None, 0.0

        scaled = self._scaled_box(box, page)
        width = max(1, int(round(scaled.right - scaled.left)))
        height = max(1, int(round(scaled.bottom - scaled.top)))
        if width < 6 or height < 6:
            return None, 0.0

        with Image.open(io.BytesIO(page.image_bytes)) as image:
            grayscale = image.convert("L")
            crop = grayscale.crop(
                (
                    max(0, int(round(scaled.left))),
                    max(0, int(round(scaled.top))),
                    min(page.width, int(round(scaled.right))),
                    min(page.height, int(round(scaled.bottom))),
                )
            )
            inset_x = max(1, int(round(crop.width * 0.18)))
            inset_y = max(1, int(round(crop.height * 0.18)))
            inner = crop.crop(
                (
                    inset_x,
                    inset_y,
                    max(inset_x + 1, crop.width - inset_x),
                    max(inset_y + 1, crop.height - inset_y),
                )
            )

        pixels = list(inner.getdata())
        if not pixels:
            return None, 0.0
        dark_ratio = sum(1 for pixel in pixels if pixel < 180) / len(pixels)
        if dark_ratio >= 0.060:
            return True, 0.90
        if dark_ratio <= 0.018:
            return False, 0.88
        return None, 0.0

    def _checkbox_groups(self, target_fields: Sequence[AcroField]) -> Dict[str, List[AcroField]]:
        groups: Dict[str, List[AcroField]] = {}
        for field in target_fields:
            if field.field_kind != FieldKind.CHECKBOX:
                continue
            group_key = self._checkbox_group_key(field.name)
            if not group_key:
                continue
            groups.setdefault(group_key, []).append(field)
        return groups

    def _checkbox_group_key(self, field_name: str) -> str:
        if field_name in {
            "driver_s_license_no_selected",
            "passport_no_selected",
            "other_selected",
        }:
            return "identification"
        for suffix in ("_yes", "_no", "_am", "_pm"):
            if field_name.endswith(suffix):
                return field_name[: -len(suffix)]
        return ""

    def _coerce_checkbox_candidate(self, key: str, value: str) -> bool | None:
        normalized = normalize_text(value)
        if not normalized:
            return False
        if normalized in {"yes", "true", "checked", "selected", "on", "x"}:
            return True
        if normalized in {"no", "false", "unchecked", "off"}:
            return False
        suffix = key.rsplit("_", 1)[-1]
        if suffix in normalized.split():
            return True
        if key.endswith("_selected"):
            normalized_key = normalize_text(key[: -len("_selected")])
            if normalized == normalized_key or normalized in normalized_key or normalized_key in normalized:
                return True
        return None

    def _resolve_checkbox_group_by_mark_score(
        self,
        page: RenderedPage,
        group_fields: Sequence[AcroField],
        keys: Sequence[str],
    ) -> str:
        if len(group_fields) < 2:
            return ""
        if not all(field.box is not None for field in group_fields):
            return ""

        scores = {
            key: self._checkbox_mark_score(page, field.box)
            for key, field in zip(keys, group_fields)
        }
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_key, best_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else 0.0
        if best_score < 0.050:
            return ""
        if second_score > 0.036 and best_score - second_score < 0.020:
            return ""
        if best_score - second_score < 0.015:
            return ""
        return best_key

    def _resolve_checkbox_group_by_blue_score(
        self,
        page: RenderedPage,
        group_fields: Sequence[AcroField],
        keys: Sequence[str],
    ) -> str:
        if len(group_fields) != 2:
            return ""
        if not all(field.box is not None for field in group_fields):
            return ""

        scores = {
            key: self._checkbox_blue_neighborhood_score(page, field.box)
            for key, field in zip(keys, group_fields)
        }
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_key, best_score = ordered[0]
        second_score = ordered[1][1]
        if best_score < 0.05:
            return ""
        if best_score - second_score < 0.04:
            return ""
        return best_key

    def _checkbox_blue_neighborhood_score(self, page: RenderedPage, box) -> float:
        try:
            from PIL import Image
        except ImportError:
            return 0.0

        scaled = self._scaled_box(box, page)
        width = max(8, int(round(scaled.right - scaled.left)) + 12)
        height = max(8, int(round(scaled.bottom - scaled.top)) + 12)
        with Image.open(io.BytesIO(page.image_bytes)) as image:
            rgb = image.convert("RGB")
            best_score = 0.0
            for dx in range(-24, 25, 4):
                for dy in range(-96, 97, 8):
                    left = max(0, int(round(scaled.left)) + dx - 6)
                    top = max(0, int(round(scaled.top)) + dy - 6)
                    right = min(page.width, left + width)
                    bottom = min(page.height, top + height)
                    crop = rgb.crop((left, top, right, bottom))
                    pixels = list(crop.getdata())
                    if not pixels:
                        continue
                    score = sum(
                        1
                        for red, green, blue in pixels
                        if blue > red + 18 and blue > green + 12 and blue > 70
                    ) / len(pixels)
                    if score > best_score:
                        best_score = score
        return best_score

    def _checkbox_mark_score(self, page: RenderedPage, box) -> float:
        try:
            from PIL import Image
        except ImportError:
            return 0.0

        scaled = self._scaled_box(box, page)
        width = max(1, int(round(scaled.right - scaled.left)))
        height = max(1, int(round(scaled.bottom - scaled.top)))
        if width < 6 or height < 6:
            return 0.0

        with Image.open(io.BytesIO(page.image_bytes)) as image:
            grayscale = image.convert("L")
            best_score = 0.0
            pad_x = max(2, int(round(width * 0.20)))
            pad_y = max(2, int(round(height * 0.20)))
            for dx in range(-8, 9, 2):
                for dy in range(-8, 9, 2):
                    crop = grayscale.crop(
                        (
                            max(0, int(round(scaled.left)) - pad_x + dx),
                            max(0, int(round(scaled.top)) - pad_y + dy),
                            min(page.width, int(round(scaled.right)) + pad_x + dx),
                            min(page.height, int(round(scaled.bottom)) + pad_y + dy),
                        )
                    )
                    inset_x = max(1, int(round(crop.width * 0.18)))
                    inset_y = max(1, int(round(crop.height * 0.18)))
                    inner = crop.crop(
                        (
                            inset_x,
                            inset_y,
                            max(inset_x + 1, crop.width - inset_x),
                            max(inset_y + 1, crop.height - inset_y),
                        )
                    )
                    pixels = list(inner.getdata())
                    if not pixels:
                        continue
                    center = inner.crop(
                        (
                            max(0, int(round(inner.width * 0.25))),
                            max(0, int(round(inner.height * 0.25))),
                            max(1, int(round(inner.width * 0.75))),
                            max(1, int(round(inner.height * 0.75))),
                        )
                    )
                    center_pixels = list(center.getdata()) or pixels
                    inner_score = sum(1 for pixel in pixels if pixel < 180) / len(pixels)
                    center_score = sum(1 for pixel in center_pixels if pixel < 180) / len(center_pixels)
                    score = (center_score * 0.8) + (inner_score * 0.2)
                    if score > best_score:
                        best_score = score
        return best_score

    def _field_ink_ratio(self, page: RenderedPage, box) -> float:
        try:
            from PIL import Image
        except ImportError:
            return 1.0

        scaled = self._scaled_box(box, page)
        with Image.open(io.BytesIO(page.image_bytes)) as image:
            grayscale = image.convert("L")
            crop = grayscale.crop(
                (
                    max(0, int(round(scaled.left))),
                    max(0, int(round(scaled.top))),
                    min(page.width, int(round(scaled.right))),
                    min(page.height, int(round(scaled.bottom))),
                )
            )
        pixels = list(crop.getdata())
        if not pixels:
            return 0.0
        return sum(1 for pixel in pixels if pixel < 208) / len(pixels)

    def _scaled_box(self, box, page: RenderedPage):
        reference_width = box.reference_width or page.width
        reference_height = box.reference_height or page.height
        if reference_width <= 0 or reference_height <= 0:
            return box
        scale_x = page.width / reference_width
        scale_y = page.height / reference_height
        return type(box)(
            page_number=box.page_number,
            left=box.left * scale_x,
            top=box.top * scale_y,
            right=box.right * scale_x,
            bottom=box.bottom * scale_y,
            reference_width=page.width,
            reference_height=page.height,
        )

    def _merge_boxes(self, left, right):
        if left.page_number != right.page_number:
            return left
        return type(left)(
            page_number=left.page_number,
            left=min(left.left, right.left),
            top=min(left.top, right.top),
            right=max(left.right, right.right),
            bottom=max(left.bottom, right.bottom),
            reference_width=left.reference_width or right.reference_width,
            reference_height=left.reference_height or right.reference_height,
        )
