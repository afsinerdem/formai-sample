from __future__ import annotations

import io
from typing import Sequence

from formai.artifacts import RegionPlanArtifact, RegionReadArtifact
from formai.llm.base import VisionLLMClient
from formai.models import FieldValue, FilledDocumentTranscript, RenderedPage


class ChandraDocumentPerceptionEngine:
    def __init__(self, client: VisionLLMClient):
        self.client = client

    def transcribe_pages(self, pages: Sequence[RenderedPage]) -> FilledDocumentTranscript:
        transcript = self.client.build_document_transcript(pages)
        if isinstance(transcript, FilledDocumentTranscript):
            return transcript
        page_texts: dict[int, str] = {}
        lines = []
        for span in getattr(transcript, "spans", []) or []:
            text = " ".join(str(getattr(span, "text", "")).split()).strip()
            if not text:
                continue
            page_number = int(getattr(span, "page_number", 1))
            page_texts[page_number] = " ".join(
                part for part in [page_texts.get(page_number, ""), text] if part
            ).strip()
            lines.append(
                {
                    "page_number": page_number,
                    "text": text,
                    "confidence": float(getattr(span, "confidence", 0.0) or 0.0),
                }
            )
        return FilledDocumentTranscript(
            provider=str(getattr(transcript, "provider", "") or self.client.__class__.__name__),
            page_count=len(pages),
            page_texts=page_texts,
            lines=[],
            confidence_map={"provider_confidence": float(getattr(transcript, "confidence", 0.0) or 0.0)},
            region_tags=lines,
        )

    def read_regions(self, pages: Sequence[RenderedPage], region_plan: RegionPlanArtifact) -> RegionReadArtifact:
        from formai.pdf.cropper import crop_rendered_page

        page_map = {page.page_number: page for page in pages}
        values: dict[str, FieldValue] = {}
        for request in region_plan.requests:
            page = page_map.get(request.page_number)
            if page is None:
                continue
            cropped = crop_rendered_page(page, request.region, context_pixels=8)
            transcript = self.client.build_document_transcript([cropped])
            fragments = []
            for span in getattr(transcript, "spans", []) or []:
                text = " ".join(str(getattr(span, "text", "")).split()).strip()
                if text:
                    fragments.append(text)
            joined = " ".join(fragments).strip()
            if not joined:
                continue
            values[request.field_key] = FieldValue(
                value=joined,
                confidence=min(0.95, 0.55 + (len(joined) / 120.0)),
                source_key=request.field_key,
                raw_text=joined,
                source_kind="chandra_region",
            )
        return RegionReadArtifact(
            values=values,
            summary={
                "request_count": len(region_plan.requests),
                "resolved_count": len(values),
            },
        )
