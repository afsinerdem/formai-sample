from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Dict, List, Sequence, Tuple

from formai.models import AcroField, BoundingBox, FieldKind


CONTINUATION_SUFFIX = "__body"
CONTINUATION_PATTERN = re.compile(r"^(?P<base>.+)__body(?:_(?P<index>\d+))?$")
DEFAULT_CHAR_WIDTH = 6.2
MIN_CHAR_WIDTH = 4.0
DEFAULT_LINE_HEIGHT = 20.0
DEFAULT_HORIZONTAL_PADDING = 4.0
ELLIPSIS = "..."


@dataclass(frozen=True)
class FittingProfile:
    char_width_candidates: Tuple[float, ...]
    single_line_font_size: float
    multiline_font_size: float
    horizontal_padding: float
    width_bias_floor: float = 0.90


FITTING_PROFILES: Dict[str, FittingProfile] = {
    "readable_cut": FittingProfile(
        char_width_candidates=(6.2, 5.8, 5.4, 5.0, 4.6),
        single_line_font_size=10.5,
        multiline_font_size=9.6,
        horizontal_padding=4.0,
        width_bias_floor=0.90,
    ),
    "same_page_compact": FittingProfile(
        char_width_candidates=(5.8, 5.4, 5.0, 4.6, 4.2, 3.9),
        single_line_font_size=10.2,
        multiline_font_size=9.2,
        horizontal_padding=1.0,
        width_bias_floor=0.88,
    ),
}


@dataclass
class OverflowDetail:
    original_text: str
    written_text: str
    overflow_text: str


@dataclass
class SegmentedExpansionResult:
    filled_values: Dict[str, str]
    overflow: Dict[str, OverflowDetail]


def resolve_fitting_profile(strategy: str | None) -> FittingProfile:
    normalized = (strategy or "readable_cut").strip().lower()
    return FITTING_PROFILES.get(normalized, FITTING_PROFILES["readable_cut"])


def continuation_field_name(base_name: str, index: int = 1) -> str:
    if index <= 1:
        return f"{base_name}{CONTINUATION_SUFFIX}"
    return f"{base_name}{CONTINUATION_SUFFIX}_{index}"


def is_continuation_field_name(field_name: str) -> bool:
    return CONTINUATION_PATTERN.match(field_name) is not None


def logical_field_name(field_name: str) -> str:
    match = CONTINUATION_PATTERN.match(field_name)
    if match:
        return match.group("base")
    return field_name


def continuation_field_index(field_name: str) -> int:
    match = CONTINUATION_PATTERN.match(field_name)
    if not match:
        return 0
    raw_index = match.group("index")
    return int(raw_index) if raw_index else 1


def coalesce_segmented_field_values(values: Dict[str, str]) -> Dict[str, str]:
    combined: Dict[str, str] = {}
    body_values: Dict[str, Dict[int, str]] = {}

    for field_name, value in values.items():
        if is_continuation_field_name(field_name):
            logical_name = logical_field_name(field_name)
            body_values.setdefault(logical_name, {})[continuation_field_index(field_name)] = value
            continue
        combined[field_name] = value

    for logical_name, indexed_values in body_values.items():
        ordered_body_values = [
            indexed_values[index]
            for index in sorted(indexed_values)
            if indexed_values[index]
        ]
        body_value = "\n".join(ordered_body_values).strip()
        lead_value = combined.get(logical_name, "")
        if lead_value and body_value:
            combined[logical_name] = f"{lead_value}\n{body_value}"
        elif body_value:
            combined[logical_name] = body_value

    return combined


def logical_expected_keys(fields: Sequence[AcroField]) -> List[str]:
    expected_keys: List[str] = []
    seen = set()
    for field in fields:
        if field.field_kind == FieldKind.CHECKBOX:
            key = field.label or field.name
        else:
            key = logical_field_name(field.label or field.name)
        if key in seen:
            continue
        seen.add(key)
        expected_keys.append(key)
    return expected_keys


def expand_values_for_template_fields(
    values: Dict[str, str],
    template_fields: Sequence[AcroField],
    fitting_strategy: str = "readable_cut",
) -> SegmentedExpansionResult:
    expanded = dict(values)
    overflow: Dict[str, OverflowDetail] = {}
    profile = resolve_fitting_profile(fitting_strategy)
    segmented_fields: Dict[str, List[AcroField]] = {}
    for field in template_fields:
        segmented_fields.setdefault(logical_field_name(field.name), []).append(field)

    for field in template_fields:
        if field.field_kind == FieldKind.CHECKBOX:
            continue
        if is_continuation_field_name(field.name):
            continue
        group_fields = sorted(
            segmented_fields.get(field.name, []),
            key=lambda candidate: (
                0 if candidate.name == field.name else 1,
                continuation_field_index(candidate.name),
            ),
        )
        if len(group_fields) <= 1:
            continue
        if field.name not in values:
            continue

        logical_value = values[field.name]
        fitted_values, extra = fit_text_to_boxes(
            logical_value,
            [candidate.box for candidate in group_fields],
            fitting_strategy=fitting_strategy,
        )
        for candidate, fitted_value in zip(group_fields, fitted_values):
            expanded[candidate.name] = fitted_value
        if extra:
            overflow[field.name] = OverflowDetail(
                original_text=logical_value,
                written_text=_join_segment_values(fitted_values),
                overflow_text=extra,
            )

    return SegmentedExpansionResult(filled_values=expanded, overflow=overflow)


def fit_text_to_boxes(
    text: str,
    boxes: Sequence[BoundingBox | None],
    fitting_strategy: str = "readable_cut",
) -> Tuple[List[str], str]:
    if not text:
        return ["" for _ in boxes], ""
    if not boxes:
        return [], text

    profile = resolve_fitting_profile(fitting_strategy)
    best_segments = ["" for _ in boxes]
    best_overflow = text
    best_line_slots: List[Tuple[float, float]] = []
    for char_width in profile.char_width_candidates:
        line_slots: List[Tuple[float, float]] = []
        segment_line_counts: List[int] = []
        for box in boxes:
            if box is None:
                segment_line_counts.append(1)
                line_slots.append((60.0, profile.single_line_font_size))
                continue
            segment_lines = _estimated_line_count(box)
            segment_line_counts.append(segment_lines)
            font_size = _estimated_font_size(box, segment_lines, profile)
            usable_width = max(12.0, box.width - (profile.horizontal_padding * 2.0))
            width_bias = max(profile.width_bias_floor, min(1.0, 6.0 / max(char_width, 0.1)))
            slot_width = usable_width * width_bias
            line_slots.extend([(slot_width, font_size)] * segment_lines)
        consumed_lines, overflow = _flow_text_into_line_slots(text, line_slots)
        segment_values = _segment_lines(consumed_lines, segment_line_counts)
        best_segments = segment_values
        best_overflow = overflow
        best_line_slots = line_slots
        if not overflow:
            break
    if best_overflow:
        best_segments = _apply_overflow_ellipsis(best_segments, boxes, best_line_slots)
    return best_segments, best_overflow


def fit_text_to_box(
    text: str,
    box: BoundingBox | None,
    fitting_strategy: str = "readable_cut",
) -> Tuple[str, str]:
    if not text:
        return "", ""
    if box is None:
        return text, ""
    fitted, overflow = fit_text_to_boxes(text, [box], fitting_strategy=fitting_strategy)
    return fitted[0], overflow


def _estimated_chars_per_line(box: BoundingBox, char_width: float = DEFAULT_CHAR_WIDTH) -> int:
    usable_width = max(12.0, box.width - (DEFAULT_HORIZONTAL_PADDING * 2.0))
    return max(1, int(usable_width / char_width))


def _estimated_line_count(box: BoundingBox) -> int:
    if box.height <= 26.0:
        return 1
    if box.height <= 44.0:
        return 2
    return max(2, int(math.floor((box.height + 2.0) / DEFAULT_LINE_HEIGHT)))


def _estimated_font_size(
    box: BoundingBox | None,
    line_count: int,
    profile: FittingProfile,
) -> float:
    if box is None:
        return profile.single_line_font_size
    if line_count <= 1:
        return profile.single_line_font_size
    return profile.multiline_font_size


def _wrap_text(text: str, width: int) -> List[str]:
    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: List[str] = []

    for paragraph in paragraphs:
        clean = " ".join(paragraph.split())
        if not clean:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.extend(_wrap_paragraph(clean, width))

    return lines or [""]


def _wrap_paragraph(text: str, width: int) -> List[str]:
    words = text.split(" ")
    lines: List[str] = []
    current = ""

    for word in words:
        if not current:
            if len(word) <= width:
                current = word
                continue
            chunks = _split_long_token(word, width)
            lines.extend(chunks[:-1])
            current = chunks[-1]
            continue

        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
            continue

        lines.append(current)
        if len(word) <= width:
            current = word
            continue

        chunks = _split_long_token(word, width)
        lines.extend(chunks[:-1])
        current = chunks[-1]

    if current:
        lines.append(current)
    return lines


def _split_long_token(token: str, width: int) -> List[str]:
    return [token[index : index + width] for index in range(0, len(token), width)] or [token]


def _flow_text_into_line_slots(
    text: str, line_slots: Sequence[Tuple[float, float]]
) -> Tuple[List[str], str]:
    if not line_slots:
        return [], text

    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: List[str] = []
    slot_index = 0
    overflow_parts: List[str] = []

    for paragraph_index, paragraph in enumerate(paragraphs):
        words = [word for word in " ".join(paragraph.split()).split(" ") if word]
        if not words:
            continue
        current = ""
        word_index = 0

        while word_index < len(words):
            if slot_index >= len(line_slots):
                overflow_parts.extend(words[word_index:])
                overflow_parts.extend(
                    later
                    for later_paragraph in paragraphs[paragraph_index + 1 :]
                    for later in later_paragraph.split()
                    if later
                )
                if current:
                    overflow_parts.insert(0, current)
                return lines, " ".join(overflow_parts).strip()

            width, font_size = line_slots[slot_index]
            word = words[word_index]
            if not current:
                if _text_width(word, font_size) <= width:
                    current = word
                    word_index += 1
                    continue
                chunks = _split_long_token_to_width(word, width, font_size)
                current = chunks[0]
                word_index += 1
                if len(chunks) > 1:
                    words[word_index:word_index] = chunks[1:]
                continue

            candidate = f"{current} {word}"
            if _text_width(candidate, font_size) <= width:
                current = candidate
                word_index += 1
                continue

            lines.append(current)
            slot_index += 1
            current = ""

        if current:
            lines.append(current)
            slot_index += 1

    return lines, ""


def _segment_lines(lines: Sequence[str], segment_line_counts: Sequence[int]) -> List[str]:
    segmented: List[str] = []
    cursor = 0
    for line_count in segment_line_counts:
        chunk = list(lines[cursor : cursor + line_count])
        cursor += line_count
        segmented.append("\n".join(line for line in chunk if line).strip())
    return segmented


def _apply_overflow_ellipsis(
    segments: Sequence[str],
    boxes: Sequence[BoundingBox | None],
    line_slots: Sequence[Tuple[float, float]],
) -> List[str]:
    updated = list(segments)
    target_index = _ellipsis_target_index(updated)
    if target_index < 0:
        return updated

    box = boxes[target_index] if target_index < len(boxes) else None
    width, font_size = _segment_last_slot(line_slots, boxes, target_index)
    if width <= _text_width(ELLIPSIS, font_size):
        updated[target_index] = ELLIPSIS
        return updated

    lines = updated[target_index].splitlines() or [""]
    last_line = lines[-1].strip()
    reserved_width = width - _text_width(ELLIPSIS, font_size)
    truncated = _truncate_to_word_boundary(last_line, reserved_width, font_size)
    if not truncated:
        truncated = _fit_prefix_to_width(last_line, reserved_width, font_size).rstrip()
    lines[-1] = f"{truncated}{ELLIPSIS}".strip()
    updated[target_index] = "\n".join(line for line in lines if line).strip()
    return updated


def _ellipsis_target_index(segments: Sequence[str]) -> int:
    for index in range(len(segments) - 1, -1, -1):
        if segments[index].strip():
            return index
    return len(segments) - 1


def _truncate_to_word_boundary(text: str, max_width: float, font_size: float) -> str:
    compact = " ".join((text or "").split()).strip()
    if _text_width(compact, font_size) <= max_width:
        return compact
    window = _fit_prefix_to_width(compact, max_width, font_size).rstrip()
    if not window:
        return ""
    boundary = window.rfind(" ")
    if boundary >= max(1, len(window) // 2):
        return window[:boundary].rstrip()
    return window


def _join_segment_values(values: Sequence[str]) -> str:
    return "\n".join(value for value in values if value.strip()).strip()


def _split_long_token_to_width(token: str, max_width: float, font_size: float) -> List[str]:
    chunks: List[str] = []
    remaining = token
    while remaining:
        chunk = _fit_prefix_to_width(remaining, max_width, font_size)
        if not chunk:
            chunk = remaining[:1]
        chunks.append(chunk)
        remaining = remaining[len(chunk) :]
    return chunks or [token]


def _fit_prefix_to_width(text: str, max_width: float, font_size: float) -> str:
    if not text:
        return ""
    if _text_width(text, font_size) <= max_width:
        return text
    low = 1
    high = len(text)
    best = ""
    while low <= high:
        middle = (low + high) // 2
        candidate = text[:middle]
        if _text_width(candidate, font_size) <= max_width:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _text_width(text: str, font_size: float) -> float:
    if not text:
        return 0.0
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        return float(stringWidth(text, "Helvetica", font_size))
    except Exception:
        return len(text) * font_size * 0.5


def _segment_last_slot(
    line_slots: Sequence[Tuple[float, float]],
    boxes: Sequence[BoundingBox | None],
    segment_index: int,
) -> Tuple[float, float]:
    offset = 0
    for index, box in enumerate(boxes):
        line_count = 1 if box is None else _estimated_line_count(box)
        if index == segment_index:
            slot = line_slots[offset + max(0, line_count - 1)]
            return slot
        offset += line_count
    return (120.0, MULTILINE_FONT_SIZE)
