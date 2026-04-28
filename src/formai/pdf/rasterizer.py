from __future__ import annotations

from pathlib import Path
from typing import List

from formai.models import RenderedPage


def rasterize_pdf(pdf_path: Path, dpi: int = 180) -> List[RenderedPage]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - optional dependency present in runtime
        raise RuntimeError(
            "PyMuPDF is required for PDF rasterization. Install project dependencies first."
        ) from exc

    rendered_pages: List[RenderedPage] = []
    scale = dpi / 72.0
    with fitz.open(str(pdf_path)) as document:
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            rendered_pages.append(
                RenderedPage(
                    page_number=index,
                    mime_type="image/png",
                    image_bytes=pixmap.tobytes("png"),
                    width=pixmap.width,
                    height=pixmap.height,
                )
            )
    return rendered_pages
