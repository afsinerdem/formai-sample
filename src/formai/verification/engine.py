from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from formai.llm.base import VisionLLMClient
from formai.models import (
    AcroField,
    BoundingBox,
    RenderedPage,
    SelfCheckFieldResult,
    SelfCheckResult,
)
from formai.pdf.rasterizer import rasterize_pdf
from formai.utils import average_confidence, canonicalize_value_for_matching, text_similarity
from formai.verification.profiles import resolve_verification_profile


def run_verification_check(
    *,
    source_reference: Path,
    output_pdf_path: Path,
    template_fields: Iterable[AcroField],
    filled_values: Dict[str, str],
    min_source_similarity: float = 0.42,
    min_output_similarity: float = 0.58,
    raster_dpi: int = 180,
    profile_name: str | None = None,
    llm_client: VisionLLMClient | None = None,
    perception_client: VisionLLMClient | None = None,
) -> SelfCheckResult | None:
    active_fields = [
        field
        for field in template_fields
        if field.box is not None and (filled_values.get(field.name) or "").strip()
    ]
    if not active_fields:
        return None

    verification_profile = resolve_verification_profile(
        profile_name=profile_name,
        template_fields=active_fields,
        default_lang="tur+eng",
    )

    source_pages = _render_source(source_reference, raster_dpi=raster_dpi)
    output_pages = rasterize_pdf(output_pdf_path, dpi=raster_dpi)
    source_map = {page.page_number: page for page in source_pages}
    output_map = {page.page_number: page for page in output_pages}
    if not source_map or not output_map:
        return None

    geometry_score = _geometry_score(active_fields)
    layout_warnings = _layout_warning_codes(active_fields)
    field_results: List[SelfCheckFieldResult] = []
    if perception_client is not None:
        for field in active_fields:
            expected_value = filled_values.get(field.name, "")
            if not expected_value.strip() or field.box is None:
                continue
            source_page = source_map.get(field.page_number)
            output_page = output_map.get(field.page_number)
            if source_page is None or output_page is None:
                continue
            source_crop = _crop_exact(source_page, field.box)
            output_crop = _crop_exact(output_page, field.box)
            source_ocr = _safe_extract_text(perception_client, source_crop)
            output_ocr = _safe_extract_text(perception_client, output_crop)
            source_similarity = _match_score(
                expected_value,
                source_ocr,
                field_name=field.name,
                profile=verification_profile,
            )
            output_similarity = _match_score(
                expected_value,
                output_ocr,
                field_name=field.name,
                profile=verification_profile,
            )
            field_results.append(
                SelfCheckFieldResult(
                    field_name=field.name,
                    expected_value=expected_value,
                    source_ocr=source_ocr,
                    output_ocr=output_ocr,
                    source_similarity=source_similarity,
                    output_similarity=output_similarity,
                )
            )
    llm_score, llm_warnings = _llm_alignment_review(
        llm_client=llm_client,
        source_pages=list(source_map.values()),
        output_pages=list(output_map.values()),
        expected_values=filled_values,
        profile_name=verification_profile.name,
        prompt_hint=verification_profile.llm_prompt_hint,
    )
    if not field_results and llm_score:
        return SelfCheckResult(
            source_reference=str(source_reference),
            overall_score=average_confidence((geometry_score, llm_score)),
            source_score=llm_score,
            output_score=llm_score,
            passed=llm_score >= min_output_similarity and geometry_score >= 0.82,
            profile=verification_profile.name,
            geometry_score=geometry_score,
            evidence_score=llm_score,
            llm_score=llm_score,
            critical_layout_pass=geometry_score >= 0.82,
            critical_text_pass=llm_score >= min_output_similarity,
            review_required=llm_score < min_output_similarity,
            layout_warnings=layout_warnings + llm_warnings,
            field_results=[],
        )
    if not field_results:
        return None

    source_score = average_confidence(result.source_similarity for result in field_results)
    output_score = average_confidence(result.output_similarity for result in field_results)
    evidence_score = average_confidence((source_score, output_score))
    critical_failures = _critical_field_failures(
        field_results=field_results,
        critical_fields=verification_profile.critical_fields,
        min_source_similarity=min_source_similarity,
        min_output_similarity=min_output_similarity,
    )
    weak_field_count = sum(
        1
        for result in field_results
        if result.source_similarity < min_source_similarity or result.output_similarity < min_output_similarity
    )
    available_stage_scores = [geometry_score, evidence_score]
    if llm_score > 0:
        available_stage_scores.append(llm_score)
    overall_score = average_confidence(available_stage_scores) * (0.92 if llm_score <= 0 else 1.0)
    critical_layout_pass = geometry_score >= 0.82 and not any(
        warning.startswith("critical_layout:")
        for warning in layout_warnings
    )
    critical_text_pass = not critical_failures and output_score >= min_output_similarity
    review_required = not (
        critical_layout_pass
        and critical_text_pass
        and weak_field_count <= max(1, len(field_results) // 4)
    )
    passed = (
        source_score >= min_source_similarity
        and critical_layout_pass
        and critical_text_pass
        and weak_field_count <= max(1, len(field_results) // 4)
    )
    return SelfCheckResult(
        source_reference=str(source_reference),
        overall_score=overall_score,
        source_score=source_score,
        output_score=output_score,
        passed=passed,
        profile=verification_profile.name,
        geometry_score=geometry_score,
        evidence_score=evidence_score,
        llm_score=llm_score,
        critical_layout_pass=critical_layout_pass,
        critical_text_pass=critical_text_pass,
        review_required=review_required,
        layout_warnings=layout_warnings + llm_warnings + [f"critical:{name}" for name in critical_failures],
        field_results=field_results,
    )


def _geometry_score(active_fields: Sequence[AcroField]) -> float:
    if not active_fields:
        return 0.0
    if len(active_fields) == 1:
        field = active_fields[0]
        if field.box is None:
            return 0.0
        if field.box.width < 18.0 or field.box.height < 8.0:
            return 0.72
        return 1.0
    penalties: list[float] = []
    tiny_count = 0
    for index, field in enumerate(active_fields):
        if field.box is None:
            penalties.append(1.0)
            continue
        if field.box.width < 18.0 or field.box.height < 8.0:
            tiny_count += 1
        worst_overlap = 0.0
        for other in active_fields[index + 1 :]:
            if other.box is None:
                continue
            worst_overlap = max(worst_overlap, field.box.intersection_over_union(other.box))
        penalties.append(worst_overlap)
    overlap_score = max(0.0, 1.0 - average_confidence(penalties, default=0.0))
    tiny_penalty = min(0.35, tiny_count * 0.08)
    return max(0.0, overlap_score - tiny_penalty)


def _llm_alignment_review(
    *,
    llm_client: VisionLLMClient | None,
    source_pages: Sequence[RenderedPage],
    output_pages: Sequence[RenderedPage],
    expected_values: Dict[str, str],
    profile_name: str,
    prompt_hint: str,
) -> tuple[float, list[str]]:
    if llm_client is None:
        return 0.0, []
    try:
        review = llm_client.review_visual_alignment(
            source_pages=source_pages,
            output_pages=output_pages,
            expected_values=expected_values,
            profile_name=profile_name,
            prompt_hint=prompt_hint,
        )
    except Exception:
        return 0.0, []
    if not review:
        return 0.0, []
    try:
        score = float(review.get("overall_score", 0.0))
    except (TypeError, ValueError):
        return 0.0, []
    if score > 1.0 and score <= 10.0:
        score /= 10.0
    elif score > 10.0 and score <= 100.0:
        score /= 100.0
    warnings: list[str] = []
    raw_notes = str(review.get("notes", "") or "").strip()
    if raw_notes:
        warnings.append(f"llm_note:{raw_notes[:160]}")
    for key in ("warnings", "critical_issues"):
        for item in review.get(key, []) or []:
            text = " ".join(str(item).split()).strip()
            if text:
                warnings.append(f"llm_{key}:{text[:120]}")
    return max(0.0, min(score, 1.0)), warnings[:8]


def _render_source(source_reference: Path, *, raster_dpi: int) -> List[RenderedPage]:
    suffix = source_reference.suffix.lower()
    if suffix == ".pdf":
        return rasterize_pdf(source_reference, dpi=raster_dpi)
    return [_render_image(source_reference)]


def _render_image(image_path: Path) -> RenderedPage:
    from PIL import Image

    image = Image.open(image_path)
    width, height = image.size
    mime_type = "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return RenderedPage(
        page_number=1,
        mime_type=mime_type,
        image_bytes=image_path.read_bytes(),
        width=width,
        height=height,
    )


def _crop_exact(page: RenderedPage, box: BoundingBox, pad: int = 2) -> RenderedPage:
    from PIL import Image

    scaled = _scale_box_to_page(box, page)
    image = Image.open(io.BytesIO(page.image_bytes))
    left = max(0, int(round(scaled.left)) - pad)
    top = max(0, int(round(scaled.top)) - pad)
    right = min(page.width, int(round(scaled.right)) + pad)
    bottom = min(page.height, int(round(scaled.bottom)) + pad)
    if right <= left:
        right = min(page.width, left + 1)
    if bottom <= top:
        bottom = min(page.height, top + 1)
    cropped = image.crop((left, top, right, bottom))
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    width, height = cropped.size
    return RenderedPage(
        page_number=page.page_number,
        mime_type="image/png",
        image_bytes=buffer.getvalue(),
        width=width,
        height=height,
    )


def _scale_box_to_page(box: BoundingBox, page: RenderedPage) -> BoundingBox:
    reference_width = box.reference_width or page.width
    reference_height = box.reference_height or page.height
    if abs(reference_width - page.width) < 1 and abs(reference_height - page.height) < 1:
        return box
    scale_x = page.width / max(reference_width, 1.0)
    scale_y = page.height / max(reference_height, 1.0)
    return BoundingBox(
        page_number=box.page_number,
        left=box.left * scale_x,
        top=box.top * scale_y,
        right=box.right * scale_x,
        bottom=box.bottom * scale_y,
        reference_width=page.width,
        reference_height=page.height,
    )


def _safe_extract_text(perception_client: VisionLLMClient, page: RenderedPage) -> str:
    try:
        transcript = perception_client.build_document_transcript([page])
        lines = []
        for span in getattr(transcript, "spans", []) or []:
            text = " ".join(str(getattr(span, "text", "")).split()).strip()
            if text:
                lines.append(text)
        return " ".join(lines).strip()
    except Exception:
        return ""


def _match_score(expected_value: str, observed_value: str, *, field_name: str, profile) -> float:
    expected = canonicalize_value_for_matching(expected_value, field_name)
    observed = canonicalize_value_for_matching(observed_value, field_name)
    if not expected:
        return 1.0
    if not observed:
        return 0.0
    if expected == observed:
        return 1.0
    if expected in observed or observed in expected:
        return 0.92

    expected_digits = "".join(character for character in expected_value if character.isdigit())
    observed_digits = "".join(character for character in observed_value if character.isdigit())
    if field_name in profile.numeric_fields or field_name in profile.date_fields:
        if expected_digits and observed_digits:
            if expected_digits == observed_digits:
                return 1.0
            if expected_digits in observed_digits or observed_digits in expected_digits:
                return 0.88
    return text_similarity(expected, observed)


def _critical_field_failures(
    *,
    field_results: Sequence[SelfCheckFieldResult],
    critical_fields: frozenset[str],
    min_source_similarity: float,
    min_output_similarity: float,
) -> list[str]:
    failures: list[str] = []
    for result in field_results:
        if result.field_name not in critical_fields:
            continue
        if result.source_similarity < (min_source_similarity * 0.9):
            failures.append(result.field_name)
            continue
        if result.output_similarity < (min_output_similarity * 0.9):
            failures.append(result.field_name)
    return sorted(set(failures))


def _layout_warning_codes(active_fields: Sequence[AcroField]) -> list[str]:
    warnings: list[str] = []
    for field in active_fields:
        if field.box is None:
            warnings.append(f"missing_box:{field.name}")
            continue
        if field.box.width < 18.0 or field.box.height < 8.0:
            warnings.append(f"tiny:{field.name}")
    for index, field in enumerate(active_fields):
        if field.box is None:
            continue
        for other in active_fields[index + 1 :]:
            if other.box is None or field.page_number != other.page_number:
                continue
            if field.box.intersection_over_union(other.box) > 0.04:
                warnings.append(f"overlap:{field.name}:{other.name}")
    return warnings
