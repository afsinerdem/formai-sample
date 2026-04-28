from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import fitz

from formai.models import BoundingBox, DetectedField, FieldKind


@dataclass
class _Span:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    font: str

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def clean_text(self) -> str:
        return " ".join(self.text.split()).strip()


@dataclass
class _Line:
    spans: List[_Span]
    left: float
    top: float
    right: float
    bottom: float

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)

    @property
    def clean_text(self) -> str:
        return " ".join(self.text.split()).strip()

    @property
    def non_empty_spans(self) -> List[_Span]:
        return [span for span in self.spans if span.clean_text]

    @property
    def checkbox_spans(self) -> List[_Span]:
        return [
            span
            for span in self.spans
            if not span.clean_text and "Times New Roman" in (span.font or "")
        ]

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass
class _Candidate:
    left: float
    top: float
    right: float
    bottom: float
    page_number: int

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0


def detect_fields_from_pdf_layout(pdf_path: Path) -> List[DetectedField]:
    document = fitz.open(str(pdf_path))
    detected_fields: List[DetectedField] = []
    emitted_keys = set()

    for page_index, page in enumerate(document, start=1):
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        lines = _extract_lines(page)
        candidates = _extract_candidates(page, page_index, lines)
        cursor = 0

        while cursor < len(lines):
            line = lines[cursor]
            text = line.clean_text
            if not text or _is_ignorable_line(line):
                cursor += 1
                continue

            row_candidates = _candidates_for_line(candidates, line)
            text_fields = _text_fields_for_line(page_index, line, row_candidates)
            checkbox_fields = _checkbox_fields_for_line(page_index, line, lines, cursor)

            if text_fields:
                text_fields = _extend_multiline_fields(
                    text_fields=text_fields,
                    lines=lines,
                    start_index=cursor,
                    candidates=candidates,
                )

            for field in text_fields + checkbox_fields:
                field.box.reference_width = page_width
                field.box.reference_height = page_height
                if field.continuation_box is not None:
                    field.continuation_box.reference_width = page_width
                    field.continuation_box.reference_height = page_height
                key = (
                    field.field_kind.value,
                    field.label,
                    field.box.page_number,
                    round(field.box.left),
                    round(field.box.top),
                    round(field.box.right),
                    round(field.box.bottom),
                )
                if key in emitted_keys:
                    continue
                emitted_keys.add(key)
                detected_fields.append(field)

            cursor += 1

    document.close()
    return detected_fields


def _extract_lines(page: fitz.Page) -> List[_Line]:
    raw = page.get_text("rawdict")
    lines: List[_Line] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans: List[_Span] = []
            for span in line.get("spans", []):
                text = "".join(char.get("c", "") for char in span.get("chars", []))
                spans.append(
                    _Span(
                        text=text,
                        left=float(span["bbox"][0]),
                        top=float(span["bbox"][1]),
                        right=float(span["bbox"][2]),
                        bottom=float(span["bbox"][3]),
                        font=str(span.get("font", "")),
                    )
                )
            if not spans:
                continue
            lines.append(
                _Line(
                    spans=spans,
                    left=float(line["bbox"][0]),
                    top=float(line["bbox"][1]),
                    right=float(line["bbox"][2]),
                    bottom=float(line["bbox"][3]),
                )
            )
    return lines


def _extract_candidates(
    page: fitz.Page, page_number: int, lines: Sequence[_Line]
) -> List[_Candidate]:
    candidates: List[_Candidate] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is None:
            continue
        x0, y0, x1, y1 = [float(value) for value in rect]
        width = abs(x1 - x0)
        height = abs(y1 - y0)

        if width >= 35 and height <= 3.5:
            candidates.append(
                _Candidate(
                    left=x0,
                    top=max(0.0, y0 - 18.0),
                    right=x1,
                    bottom=y0 + 4.0,
                    page_number=page_number,
                )
            )
            continue

        if width >= 120 and 12.0 <= height <= 30.0 and not _is_header_rect(x0, y0, x1, y1, lines):
            candidates.append(
                _Candidate(
                    left=x0,
                    top=y0,
                    right=x1,
                    bottom=y1,
                    page_number=page_number,
                )
            )

    return sorted(candidates, key=lambda candidate: (candidate.top, candidate.left))


def _is_header_rect(
    left: float, top: float, right: float, bottom: float, lines: Sequence[_Line]
) -> bool:
    for line in lines:
        text = line.clean_text
        if not text:
            continue
        if line.top < top - 6 or line.bottom > bottom + 6:
            continue
        if line.left < left - 8 or line.right > right + 8:
            continue
        if text == text.upper() and ":" not in text and "?" not in text:
            return True
    return False


def _candidates_for_line(candidates: Sequence[_Candidate], line: _Line) -> List[_Candidate]:
    horizontal_padding = 160.0 if _secondary_label_for_line(line) else 80.0
    matches = []
    for candidate in candidates:
        vertical_match = candidate.bottom >= line.top - 2.0 and candidate.top <= line.bottom + 0.5
        horizontal_match = candidate.right >= line.left - 6.0 and candidate.left <= line.right + horizontal_padding
        if vertical_match and horizontal_match:
            matches.append(candidate)
    return matches


def _text_fields_for_line(
    page_number: int, line: _Line, row_candidates: Sequence[_Candidate]
) -> List[DetectedField]:
    non_empty = line.non_empty_spans
    if not non_empty or not row_candidates:
        return []

    labels = [span for span in non_empty if _is_label_span(span.clean_text)]
    if not labels and _secondary_only_label(line.clean_text):
        candidate = _nearest_candidate_to_text(row_candidates, line.right)
        if candidate is None:
            return []
        return [
            DetectedField(
                label="Report Year",
                field_kind=FieldKind.TEXT,
                box=BoundingBox(
                    page_number=page_number,
                    left=candidate.left,
                    top=candidate.top,
                    right=candidate.right,
                    bottom=candidate.bottom,
                ),
                confidence=0.72,
                page_hint_text=line.clean_text,
            )
        ]
    if not labels:
        labels = _infer_plain_text_labels(line, row_candidates)
    if not labels:
        return []

    controls = sorted(
        [span for span in non_empty if _is_control_span(span.clean_text)] + line.checkbox_spans,
        key=lambda span: span.left,
    )

    detected: List[DetectedField] = []
    used_candidates = set()

    for index, label in enumerate(labels):
        next_control_left = min(
            (
                span.left
                for span in controls
                if span.left > label.right + 6.0
            ),
            default=float("inf"),
        )

        best_candidate: Optional[_Candidate] = None
        for candidate in row_candidates:
            if id(candidate) in used_candidates:
                continue
            if candidate.right <= label.right + 8.0:
                continue
            if candidate.left >= next_control_left:
                continue
            best_candidate = candidate
            break

        if best_candidate is None:
            continue

        field_left = max(best_candidate.left, label.right + 4.0)
        field_right = min(best_candidate.right, next_control_left - 6.0)
        if field_right - field_left < 22.0:
            continue

        used_candidates.add(id(best_candidate))
        detected.append(
            DetectedField(
                label=_clean_label(label.clean_text),
                field_kind=FieldKind.TEXT,
                box=BoundingBox(
                    page_number=page_number,
                    left=field_left,
                    top=best_candidate.top,
                    right=field_right,
                    bottom=best_candidate.bottom,
                ),
                confidence=0.80,
                page_hint_text=line.clean_text,
            )
        )

    if not detected and len(row_candidates) == 1 and len(labels) == 1:
        candidate = row_candidates[0]
        label = labels[0]
        field_left = max(candidate.left, label.right + 4.0)
        if candidate.right - field_left >= 22.0:
            detected.append(
                DetectedField(
                    label=_clean_label(label.clean_text),
                    field_kind=FieldKind.TEXT,
                    box=BoundingBox(
                        page_number=page_number,
                        left=field_left,
                        top=candidate.top,
                        right=candidate.right,
                        bottom=candidate.bottom,
                    ),
                    confidence=0.76,
                    page_hint_text=line.clean_text,
                )
            )

    if len(labels) == 1:
        secondary_label = _secondary_label_for_line(line)
        if not secondary_label:
            return detected
        used_names = {field.label for field in detected}
        for candidate in row_candidates:
            if id(candidate) in used_candidates:
                continue
            if candidate.width < 28.0:
                continue
            label_text = secondary_label
            if label_text in used_names:
                label_text = f"{label_text} 2"
            detected.append(
                DetectedField(
                    label=label_text,
                    field_kind=FieldKind.TEXT,
                    box=BoundingBox(
                        page_number=page_number,
                        left=candidate.left,
                        top=candidate.top,
                        right=candidate.right,
                        bottom=candidate.bottom,
                    ),
                    confidence=0.66,
                    page_hint_text=line.clean_text,
                )
            )
            used_names.add(label_text)

    return detected


def _checkbox_fields_for_line(
    page_number: int, line: _Line, lines: Sequence[_Line], line_index: int
) -> List[DetectedField]:
    if not line.checkbox_spans:
        return []

    non_empty = line.non_empty_spans
    detected: List[DetectedField] = []
    question = next((span.clean_text for span in non_empty if span.clean_text.endswith("?")), "")
    last_label = next(
        (span.clean_text for span in reversed(non_empty) if _is_label_span(span.clean_text)),
        "",
    )
    question = question or _nearest_context_text(lines, line_index, suffix="?")
    last_label = last_label or _nearest_context_text(lines, line_index, suffix=":")

    for checkbox in line.checkbox_spans:
        option = next(
            (span.clean_text for span in non_empty if span.left > checkbox.left + 1.0),
            "",
        )
        if not option:
            continue

        if option in {"Yes", "No"} and question:
            label = f"{_clean_label(question)} {option}"
        elif option in {"AM", "PM"} and last_label:
            label = f"{_clean_label(last_label)} {option}"
        else:
            label = f"{_clean_label(option)} Selected"

        detected.append(
            DetectedField(
                label=label,
                field_kind=FieldKind.CHECKBOX,
                box=BoundingBox(
                    page_number=page_number,
                    left=max(0.0, checkbox.left - 10.5),
                    top=line.top + 0.5,
                    right=checkbox.left + 1.0,
                    bottom=line.top + 11.5,
                ),
                confidence=0.78,
                page_hint_text=line.clean_text,
            )
        )

    return detected


def _extend_multiline_fields(
    text_fields: List[DetectedField],
    lines: Sequence[_Line],
    start_index: int,
    candidates: Sequence[_Candidate],
) -> List[DetectedField]:
    extended: List[DetectedField] = []
    for field in text_fields:
        label = field.label.lower()
        if not any(
            token in label
            for token in ("describe", "contact info")
        ):
            extended.append(field)
            continue

        next_candidates = [
            candidate
            for candidate in candidates
            if candidate.left <= field.box.left + 10.0
            and candidate.right >= field.box.right - 10.0
            and candidate.center_y > ((field.box.top + field.box.bottom) / 2.0) + 8.0
            and candidate.top - field.box.bottom <= 60.0
            and not _has_text_near_candidate(lines, candidate, start_index + 1)
        ]
        next_candidates = sorted(next_candidates, key=lambda candidate: candidate.top)[:2]
        if not next_candidates:
            extended.append(field)
            continue

        continuation_box = BoundingBox(
            page_number=field.box.page_number,
            left=min(candidate.left for candidate in next_candidates),
            top=min(candidate.top for candidate in next_candidates),
            right=max(candidate.right for candidate in next_candidates),
            bottom=max(candidate.bottom for candidate in next_candidates),
        )
        extended.append(
            DetectedField(
                label=field.label,
                field_kind=FieldKind.MULTILINE,
                box=field.box,
                confidence=field.confidence,
                page_hint_text=field.page_hint_text,
                continuation_box=continuation_box,
            )
        )
    return extended


def _has_text_near_candidate(lines: Sequence[_Line], candidate: _Candidate, start_index: int) -> bool:
    for line in lines[start_index:]:
        if line.top > candidate.bottom + 6.0:
            return False
        if line.bottom < candidate.top - 6.0:
            continue
        text = line.clean_text
        if text and not _is_ignorable_line(line):
            return True
    return False


def _is_ignorable_line(line: _Line) -> bool:
    text = line.clean_text
    if not text:
        return True
    if _secondary_only_label(text):
        return False
    if line.checkbox_spans and text in {"AM", "PM"}:
        return False
    if text.startswith("Page ") or text == text.upper() and ":" not in text and "?" not in text:
        return True
    if text.startswith("Use this form") or text.startswith("incidents, or student"):
        return True
    if text.startswith("24 hours of the event"):
        return True
    return False


def _is_label_span(text: str) -> bool:
    if not text:
        return False
    if text in {"Yes", "No", "AM", "PM"}:
        return False
    return text.endswith(":") or text.endswith("?") or "No." in text or "E-Mail" in text


def _is_control_span(text: str) -> bool:
    return text in {"Yes", "No", "AM", "PM"}


def _clean_label(text: str) -> str:
    cleaned = " ".join(text.replace("  ", " ").split()).strip()
    while cleaned.endswith((":", "?", ".", ",")):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def _secondary_label_for_line(line: _Line) -> str:
    text = line.clean_text
    if ", 20" in text:
        return "Report Year"
    return ""


def _secondary_only_label(text: str) -> bool:
    return "20" in text and "," in text


def _infer_plain_text_labels(line: _Line, row_candidates: Sequence[_Candidate]) -> List[_Span]:
    if line.checkbox_spans:
        return []
    if len(line.non_empty_spans) != 1:
        return []

    label = line.non_empty_spans[0]
    if not _looks_like_field_label(label.clean_text):
        return []

    has_candidate_to_right = any(
        candidate.left >= label.right + 12.0
        for candidate in row_candidates
    )
    if not has_candidate_to_right:
        return []

    return [label]


def _nearest_candidate_to_text(
    candidates: Sequence[_Candidate], text_right: float
) -> Optional[_Candidate]:
    if not candidates:
        return None

    right_side_candidates = [
        candidate
        for candidate in candidates
        if candidate.right >= text_right + 6.0
    ]
    if right_side_candidates:
        return min(
            right_side_candidates,
            key=lambda candidate: abs(candidate.left - text_right),
        )
    return min(candidates, key=lambda candidate: abs(candidate.left - text_right))


def _previous_context_line(lines: Sequence[_Line], line_index: int) -> Optional[_Line]:
    for index in range(line_index - 1, -1, -1):
        line = lines[index]
        if _is_ignorable_line(line):
            continue
        return line
    return None


def _nearest_context_text(lines: Sequence[_Line], line_index: int, suffix: str) -> str:
    origin = lines[line_index]
    for index in range(line_index - 1, -1, -1):
        line = lines[index]
        if origin.top - line.bottom > 35.0:
            break
        if _is_ignorable_line(line):
            continue
        text = line.clean_text
        if text.endswith(suffix):
            return text
    return ""


def _looks_like_field_label(text: str) -> bool:
    if not text:
        return False
    if text in {"Yes", "No", "AM", "PM"}:
        return False
    if text.startswith("Page "):
        return False
    if len(text) < 3:
        return False
    return any(character.isalpha() for character in text)
