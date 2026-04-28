from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from formai.models import FieldKind
from formai.pdf.structure import CheckboxCandidate, RectElement, TableCell, TextSpan
from formai.utils import normalize_text


class AnchorPattern(str, Enum):
    COLON_DOTS = "colon_dots"
    COLON_UNDERLINE = "colon_underline"
    BARE_DOTS = "bare_dots"
    UNDERLINE = "underline"
    RECT_BOX = "rect_box"
    TABLE_CELL = "table_cell"
    PLACEHOLDER = "placeholder"
    CHECKBOX = "checkbox"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedAnchor:
    pattern: AnchorPattern
    field_kind: FieldKind
    confidence: float


def classify_placeholder(span: TextSpan) -> ClassifiedAnchor:
    text = span.text.strip()
    if ":" in text and "." in text:
        return ClassifiedAnchor(AnchorPattern.COLON_DOTS, FieldKind.TEXT, 0.74)
    if "." in text and len(text) >= 5:
        return ClassifiedAnchor(AnchorPattern.BARE_DOTS, FieldKind.TEXT, 0.7)
    if "_" in text and len(text) >= 5:
        return ClassifiedAnchor(AnchorPattern.UNDERLINE, FieldKind.TEXT, 0.7)
    if "/" in text and "20" in text:
        return ClassifiedAnchor(AnchorPattern.PLACEHOLDER, FieldKind.DATE, 0.72)
    return ClassifiedAnchor(AnchorPattern.UNKNOWN, FieldKind.UNKNOWN, 0.0)


def classify_rect(rect: RectElement) -> ClassifiedAnchor:
    width = abs(rect.x1 - rect.x0)
    height = abs(rect.bottom - rect.top)
    if width <= 15.0 and height <= 15.0 and abs(width - height) <= 4.0:
        return ClassifiedAnchor(AnchorPattern.CHECKBOX, FieldKind.CHECKBOX, 0.82)
    if width >= 45.0 and height <= 18.0:
        return ClassifiedAnchor(AnchorPattern.RECT_BOX, FieldKind.TEXT, 0.65)
    return ClassifiedAnchor(AnchorPattern.UNKNOWN, FieldKind.UNKNOWN, 0.0)


def classify_checkbox_candidate(_: CheckboxCandidate) -> ClassifiedAnchor:
    return ClassifiedAnchor(AnchorPattern.CHECKBOX, FieldKind.CHECKBOX, 0.85)


def classify_table_cell(cell: TableCell, header_text: str = "") -> ClassifiedAnchor:
    normalized = normalize_text(header_text)
    if any(token in normalized for token in ("date", "tarih")):
        kind = FieldKind.DATE
    elif any(token in normalized for token in ("no", "numara", "number", "akts", "kredi", "credit")):
        kind = FieldKind.NUMBER
    else:
        kind = FieldKind.TEXT
    width = abs(cell.x1 - cell.x0)
    confidence = 0.74 if width > 24.0 else 0.58
    return ClassifiedAnchor(AnchorPattern.TABLE_CELL, kind, confidence)
