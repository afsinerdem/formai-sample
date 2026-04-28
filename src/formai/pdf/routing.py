from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from formai.errors import IntegrationUnavailable


@dataclass
class PdfRoutingDiagnostics:
    page_sizes: list[tuple[float, float]] = field(default_factory=list)
    page_character_counts: list[int] = field(default_factory=list)
    has_embedded_text: bool = False
    routing_strategy: str = "vision_first"


def analyze_pdf_routing(pdf_path: Path) -> PdfRoutingDiagnostics:
    page_sizes = _page_sizes(pdf_path)
    page_character_counts = _page_character_counts(pdf_path)
    max_chars = max(page_character_counts or [0])
    min_chars = min(page_character_counts or [0])
    has_embedded_text = max_chars >= 50

    if max_chars >= 50 and min_chars >= 20:
        routing_strategy = "structure_first"
    elif max_chars < 20:
        routing_strategy = "vision_first"
    else:
        routing_strategy = "hybrid"

    return PdfRoutingDiagnostics(
        page_sizes=page_sizes,
        page_character_counts=page_character_counts,
        has_embedded_text=has_embedded_text,
        routing_strategy=routing_strategy,
    )


def _page_sizes(pdf_path: Path) -> list[tuple[float, float]]:
    try:
        import fitz
    except ImportError as exc:
        raise IntegrationUnavailable("PyMuPDF is required for PDF routing analysis.") from exc

    document = fitz.open(str(pdf_path))
    try:
        return [
            (float(page.rect.width or 0.0), float(page.rect.height or 0.0))
            for page in document
        ]
    finally:
        document.close()


def _page_character_counts(pdf_path: Path) -> list[int]:
    try:
        import pdfplumber
    except ImportError:
        return _page_character_counts_with_fitz(pdf_path)

    with pdfplumber.open(str(pdf_path)) as pdf:
        counts: list[int] = []
        for page in pdf.pages:
            text = (page.extract_text() or "").strip()
            counts.append(len(text))
        return counts


def _page_character_counts_with_fitz(pdf_path: Path) -> list[int]:
    try:
        import fitz
    except ImportError as exc:
        raise IntegrationUnavailable("PyMuPDF is required for PDF routing analysis fallback.") from exc

    document = fitz.open(str(pdf_path))
    try:
        counts: list[int] = []
        for page in document:
            text = (page.get_text("text") or "").strip()
            counts.append(len(text))
        return counts
    finally:
        document.close()
