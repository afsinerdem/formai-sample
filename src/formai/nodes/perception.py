from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Sequence

from formai.artifacts import (
    FilledLayoutArtifact,
    RasterArtifact,
    RasterPageRef,
    RegionPlanArtifact,
    RegionReadRequest,
    TranscriptArtifact,
)
from formai.models import AcroField, FieldValue, FilledDocumentTranscript, ProcessingIssue, RenderedPage
from formai.pdf.rasterizer import rasterize_pdf
from formai.segmentation import logical_field_name

CRITICAL_REGION_KEYS = {
    "ogrenci_aciklamasi",
    "danisman_gorusu",
}


def rasterize_document(*, pdf_path: Path, dpi: int, cache_dir: Path) -> tuple[RasterArtifact, list[RenderedPage]]:
    rendered_pages = rasterize_pdf(pdf_path, dpi=dpi)
    raster_dir = cache_dir / "raster" / f"{pdf_path.stem}_{dpi}"
    raster_dir.mkdir(parents=True, exist_ok=True)
    refs: list[RasterPageRef] = []
    for page in rendered_pages:
        digest = hashlib.sha256(page.image_bytes).hexdigest()[:16]
        suffix = ".png" if "png" in page.mime_type else ".jpg"
        output_path = raster_dir / f"page_{page.page_number}_{digest}{suffix}"
        output_path.write_bytes(page.image_bytes)
        refs.append(
            RasterPageRef(
                page_number=page.page_number,
                path=output_path,
                mime_type=page.mime_type,
                width=page.width,
                height=page.height,
            )
        )
    return RasterArtifact(source_path=pdf_path, dpi=dpi, pages=refs), rendered_pages


def transcribe_document(rendered_pages: Sequence[RenderedPage], perception_engine) -> TranscriptArtifact:
    transcript = perception_engine.transcribe_pages(rendered_pages)
    confidence = 0.0
    if transcript is not None and transcript.confidence_map:
        confidence = max(float(value) for value in transcript.confidence_map.values())
    elif transcript is not None and transcript.page_texts:
        confidence = 0.7
    return TranscriptArtifact(
        transcript=transcript,
        confidence=confidence,
    )


def plan_region_reads(
    *,
    target_fields: Sequence[AcroField],
    extracted_values: dict[str, FieldValue],
    filled_layout: FilledLayoutArtifact | None = None,
    max_requests: int = 24,
) -> RegionPlanArtifact:
    requests: list[RegionReadRequest] = []
    density_map = getattr(filled_layout, "region_density", {}) or {}
    for field in target_fields:
        if field.box is None:
            continue
        key = logical_field_name(field.label or field.name)
        canonical_names = {key, logical_field_name(field.name), field.name}
        current = extracted_values.get(key) or extracted_values.get(field.name)
        reason = ""
        priority = 0
        if current is None or not current.value.strip():
            reason = "missing_value"
            priority = 3
        elif current.confidence < 0.62:
            reason = "low_confidence"
            priority = 2
        elif field.field_kind.value in {"date", "multiline"}:
            reason = "critical_field"
            priority = 1
        if any(name in CRITICAL_REGION_KEYS for name in canonical_names):
            reason = reason or "critical_field"
            priority = max(priority, 3)
        density_score = float(
            density_map.get(f"page_{field.page_number}_text_density", 0.0)
            or density_map.get(str(field.page_number), 0.0)
            or 0.0
        )
        if density_score >= 0.55:
            priority += 1
            if not reason:
                reason = "dense_layout"
        if not reason:
            continue
        requests.append(
            RegionReadRequest(
                field_key=key or field.name,
                page_number=field.page_number,
                region=field.box,
                reason=reason,
                priority=priority,
            )
        )
    requests.sort(key=lambda item: (-item.priority, item.page_number, item.field_key))
    requests = requests[:max_requests]
    return RegionPlanArtifact(
        requests=requests,
        summary={
            "request_count": len(requests),
            "max_requests": max_requests,
        },
    )
