from __future__ import annotations

import io
from typing import Sequence

from formai.errors import IntegrationUnavailable
from formai.llm.base import VisionLLMClient
from formai.llm.contracts import DocumentTranscript, TranscriptSpan
from formai.models import DetectedField, FieldValue, RenderedPage


class ChandraPerceptionClient(VisionLLMClient):
    """Optional layout-aware transcript backend using Chandra OCR 2."""

    def __init__(self, model: str = "datalab-to/chandra-ocr-2", method: str = "hf"):
        self.model = model
        self.method = method
        self._manager = None

    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        raise IntegrationUnavailable(
            "Chandra perception backend does not implement template field detection. "
            "Use structure-first template analysis or a template detector provider."
        )

    def extract_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> dict[str, FieldValue]:
        raise IntegrationUnavailable(
            "Chandra is configured as a perception backend only. "
            "Use a resolver backend to map transcripts into structured fields."
        )

    def build_document_transcript(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        if not pages:
            return DocumentTranscript(provider="chandra", confidence=0.0)
        manager = self._ensure_manager()
        batch = [self._batch_item_for_page(page) for page in pages]
        results = manager.generate(batch)
        spans: list[TranscriptSpan] = []
        for page, result in zip(pages, results):
            markdown = str(
                getattr(result, "markdown", "")
                or getattr(result, "raw", "")
                or getattr(result, "text", "")
            ).strip()
            if not markdown:
                continue
            for line in [segment.strip() for segment in markdown.splitlines() if segment.strip()]:
                spans.append(
                    TranscriptSpan(
                        text=line,
                        page_number=page.page_number,
                        kind="layout_line",
                        confidence=0.82,
                        region_tag="chandra_markdown",
                    )
                )
        confidence = 0.82 if spans else 0.0
        return DocumentTranscript(
            pages=list(pages),
            spans=spans,
            provider="chandra",
            confidence=confidence,
            metadata={"model": self.model, "method": self.method},
        )

    def transcribe_document(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        return self.build_document_transcript(pages)

    def _ensure_manager(self):
        if self._manager is not None:
            return self._manager
        try:
            from chandra.model import InferenceManager
        except ImportError as exc:
            raise IntegrationUnavailable(
                "Chandra backend requires the `chandra-ocr` package. "
                "Install with `pip install chandra-ocr[hf]` or start `chandra_vllm` and set FORMAI_CHANDRA_METHOD=vllm."
            ) from exc
        self._manager = InferenceManager(method=self.method)
        return self._manager

    def _batch_item_for_page(self, page: RenderedPage):
        try:
            from chandra.model.schema import BatchInputItem
            from PIL import Image
        except ImportError as exc:
            raise IntegrationUnavailable(
                "Chandra perception backend requires `chandra-ocr` and `Pillow`."
            ) from exc
        image = Image.open(io.BytesIO(page.image_bytes))
        return BatchInputItem(image=image, prompt_type="ocr_layout")
