from __future__ import annotations

from typing import Dict, Protocol, Sequence

from formai.artifacts import FilledLayoutArtifact, RegionPlanArtifact, RegionReadArtifact, VerificationArtifact
from formai.models import FieldValue, FilledDocumentTranscript, RenderedPage


class DocumentPerceptionEngine(Protocol):
    def transcribe_pages(self, pages: Sequence[RenderedPage]) -> FilledDocumentTranscript:
        ...

    def read_regions(self, pages: Sequence[RenderedPage], region_plan: RegionPlanArtifact) -> RegionReadArtifact:
        ...


class LayoutEngine(Protocol):
    def analyze_template(self, pdf_path) -> object:
        ...

    def analyze_filled_pages(self, pages: Sequence[RenderedPage], transcript: FilledDocumentTranscript | None = None) -> FilledLayoutArtifact:
        ...


class RegionAdjudicator(Protocol):
    def adjudicate(
        self,
        *,
        candidate_values: Dict[str, FieldValue],
        expected_keys: Sequence[str],
    ) -> Dict[str, FieldValue]:
        ...


class OutputVerifier(Protocol):
    def verify(
        self,
        *,
        source_pages: Sequence[RenderedPage],
        output_pages: Sequence[RenderedPage],
        expected_values: Dict[str, str],
        profile_name: str,
    ) -> VerificationArtifact:
        ...
