"""LLM provider abstractions for FormAI."""

from formai.llm.base import NullVisionLLMClient, VisionLLMClient
from formai.llm.chandra_perception import ChandraPerceptionClient
from formai.llm.contracts import (
    DocumentPerceptionClient,
    DocumentTranscript,
    FieldEvidence,
    FieldEvidenceGraph,
    RenderPlan,
    RenderPlanItem,
    SchemaResolverClient,
    TemplateFieldDetector,
    TemplatePageSummary,
    TemplateStructureGraph,
    TranscriptSpan,
    VisualReviewClient,
)
from formai.llm.turkish_gemma_resolver import TurkishGemmaResolverClient

__all__ = [
    "ChandraPerceptionClient",
    "DocumentPerceptionClient",
    "DocumentTranscript",
    "FieldEvidence",
    "FieldEvidenceGraph",
    "NullVisionLLMClient",
    "RenderPlan",
    "RenderPlanItem",
    "SchemaResolverClient",
    "TemplateFieldDetector",
    "TemplatePageSummary",
    "TemplateStructureGraph",
    "TranscriptSpan",
    "TurkishGemmaResolverClient",
    "VisionLLMClient",
    "VisualReviewClient",
]
