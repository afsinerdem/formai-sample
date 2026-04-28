from __future__ import annotations

from dataclasses import dataclass

from formai.models import BoundingBox


COLON_GAP = 2.0
DOT_TOP_OFFSET = 2.0
BOX_PADDING = 3.0
TABLE_CELL_PADDING = 3.0
UNDERLINE_GAP = 1.0
CHECKBOX_SIZE = 10.0
MIN_FIELD_HEIGHT = 8.0
MIN_FIELD_WIDTH = 15.0


@dataclass(frozen=True)
class PdfRect:
    left: float
    bottom: float
    right: float
    top: float


def pdf_y(top_based_y: float, page_height: float) -> float:
    return float(page_height) - float(top_based_y)


def image_to_pdf(
    ix: float,
    iy: float,
    image_width: float,
    image_height: float,
    pdf_width: float,
    pdf_height: float,
) -> tuple[float, float]:
    px = float(ix) * (float(pdf_width) / max(float(image_width), 1.0))
    py = float(pdf_height) - (float(iy) * (float(pdf_height) / max(float(image_height), 1.0)))
    return px, py


def canonical_box(
    *,
    page_number: int,
    left: float,
    top: float,
    right: float,
    bottom: float,
    reference_width: float | None = None,
    reference_height: float | None = None,
) -> BoundingBox:
    normalized_left = max(0.0, min(float(left), float(right)))
    normalized_top = max(0.0, min(float(top), float(bottom)))
    normalized_right = max(normalized_left, max(float(left), float(right)))
    normalized_bottom = max(normalized_top, max(float(top), float(bottom)))
    if normalized_right - normalized_left < MIN_FIELD_WIDTH:
        normalized_right = normalized_left + MIN_FIELD_WIDTH
    if normalized_bottom - normalized_top < MIN_FIELD_HEIGHT:
        normalized_bottom = normalized_top + MIN_FIELD_HEIGHT
    return BoundingBox(
        page_number=page_number,
        left=normalized_left,
        top=normalized_top,
        right=normalized_right,
        bottom=normalized_bottom,
        reference_width=reference_width,
        reference_height=reference_height,
    )


def bounding_box_to_pdf_rect(box: BoundingBox, page_height: float) -> PdfRect:
    return PdfRect(
        left=float(box.left),
        bottom=pdf_y(box.bottom, page_height),
        right=float(box.right),
        top=pdf_y(box.top, page_height),
    )


def optimal_font_size(field_height_pt: float, *, multiline: bool = False) -> float:
    scale = 0.68 if multiline else 0.75
    size = float(field_height_pt) * scale
    return max(6.0, min(12.0, round(size, 1)))
