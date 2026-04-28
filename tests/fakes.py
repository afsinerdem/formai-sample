from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from formai.benchmarks.base import DatasetAdapter
from formai.benchmarks.models import BenchmarkSample
from formai.llm.base import VisionLLMClient
from formai.llm.contracts import DocumentTranscript
from formai.mapping import match_detected_fields_to_acro_fields
from formai.models import AcroField, DetectedField, FieldMapping, FieldValue, RenderedPage
from formai.pdf.inspector import inspect_pdf_fields, rename_pdf_fields
from formai.utils import average_confidence, ensure_unique_slug
from tests.fixture_factory import FixtureField, create_reportlab_acroform_pdf


class FakeVisionLLMClient(VisionLLMClient):
    def __init__(
        self,
        detected_fields: Sequence[DetectedField],
        extracted_values: Dict[str, FieldValue],
    ):
        self._detected_fields = list(detected_fields)
        self._extracted_values = dict(extracted_values)

    def detect_template_fields(self, pages: Sequence[RenderedPage]) -> Sequence[DetectedField]:
        return list(self._detected_fields)

    def extract_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        return dict(self._extracted_values)

    def resolve_structured_data(
        self, pages: Sequence[RenderedPage], expected_keys: Sequence[str]
    ) -> Dict[str, FieldValue]:
        return self.extract_structured_data(pages, expected_keys)

    def transcribe_document(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        return DocumentTranscript(
            pages=list(pages),
            spans=[],
            provider="fake",
            confidence=1.0,
            metadata={"source": "tests.fakes.FakeVisionLLMClient"},
        )

    def build_document_transcript(self, pages: Sequence[RenderedPage]) -> DocumentTranscript:
        return self.transcribe_document(pages)


class FakeCommonFormsAdapter:
    def __init__(self, fixture_fields: Iterable[FixtureField]):
        self.fixture_fields = list(fixture_fields)

    def prepare_fillable_pdf(
        self, input_path: Path, output_path: Path, detected_fields: List[DetectedField]
    ):
        create_reportlab_acroform_pdf(output_path, self.fixture_fields)
        generated_fields = inspect_pdf_fields(output_path)
        mappings = match_detected_fields_to_acro_fields(detected_fields, generated_fields)
        rename_map = self._build_rename_map(mappings)
        rename_pdf_fields(output_path, rename_map, output_path)
        renamed_fields = inspect_pdf_fields(output_path)
        confidence = average_confidence([mapping.confidence for mapping in mappings], default=0.0)
        return renamed_fields, mappings, rename_map, confidence

    def _build_rename_map(self, mappings: List[FieldMapping]) -> dict:
        rename_map = {}
        used_names = set()
        for mapping in mappings:
            if not mapping.target_field:
                continue
            rename_map[mapping.target_field] = ensure_unique_slug(mapping.source_key, used_names)
        return rename_map


class FakeDatasetAdapter(DatasetAdapter):
    def __init__(self, dataset_name: str, samples: Sequence[BenchmarkSample]):
        self.dataset_name = dataset_name
        self._samples = list(samples)

    def load_samples(self, split: str, max_samples: int | None = None) -> Sequence[BenchmarkSample]:
        matching = [sample for sample in self._samples if sample.split == split]
        if max_samples is not None:
            return matching[:max_samples]
        return matching
