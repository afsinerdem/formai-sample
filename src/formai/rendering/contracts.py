from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List

from formai.models import BoundingBox, FieldKind


class RenderWriterKind(str, Enum):
    INLINE = "inline"
    SINGLE_LINE = "single_line"
    COMPOUND_CONTACT = "compound_contact"
    TABLE_CELL = "table_cell"
    DATE_SIGNATURE = "date_signature"
    MULTILINE = "multiline"


@dataclass(frozen=True)
class RenderContentRun:
    text: str
    role: str = "body"
    emphasis: str = "normal"
    field_name: str = ""

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "role": self.role,
            "emphasis": self.emphasis,
            "field_name": self.field_name,
        }


@dataclass(frozen=True)
class RenderPolicy:
    writer_kind: RenderWriterKind
    font_size: float | None = None
    multiline_font_size: float | None = None
    horizontal_inset: float = 1.5
    baseline_inset: float = 0.8
    top_inset: float = 1.8
    background_padding: float = 1.0
    line_policy: str = "single"
    split_policy: str = "none"
    wrap_mode: str = "truncate"
    max_lines: int | None = None
    source: str = "heuristic"

    def to_dict(self) -> dict:
        return {
            "writer_kind": self.writer_kind.value,
            "font_size": self.font_size,
            "multiline_font_size": self.multiline_font_size,
            "horizontal_inset": self.horizontal_inset,
            "baseline_inset": self.baseline_inset,
            "top_inset": self.top_inset,
            "background_padding": self.background_padding,
            "line_policy": self.line_policy,
            "split_policy": self.split_policy,
            "wrap_mode": self.wrap_mode,
            "max_lines": self.max_lines,
            "source": self.source,
        }


@dataclass(frozen=True)
class RenderPlanItem:
    field_name: str
    page_number: int
    writer_kind: RenderWriterKind
    detected_region: BoundingBox | None
    target_region: BoundingBox | None
    value: str
    field_kind: FieldKind = FieldKind.UNKNOWN
    content_runs: List[RenderContentRun] = field(default_factory=list)
    policy: RenderPolicy | None = None
    anchor_ref: str = ""
    baseline_y: float | None = None
    container_type: str = "field"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "page_number": self.page_number,
            "writer_kind": self.writer_kind.value,
            "detected_region": _box_to_dict(self.detected_region),
            "target_region": _box_to_dict(self.target_region),
            "value": self.value,
            "field_kind": self.field_kind.value,
            "content_runs": [run.to_dict() for run in self.content_runs],
            "policy": self.policy.to_dict() if self.policy is not None else None,
            "anchor_ref": self.anchor_ref,
            "baseline_y": self.baseline_y,
            "container_type": self.container_type,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RenderPlan:
    profile: str
    items: List[RenderPlanItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
            "page_count": self.page_count,
            "writer_counts": self.writer_counts,
        }

    @property
    def page_count(self) -> int:
        pages = [item.page_number for item in self.items if item.page_number > 0]
        return max(pages) if pages else 0

    @property
    def writer_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            key = item.writer_kind.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def items_for_page(self, page_number: int) -> List[RenderPlanItem]:
        return [item for item in self.items if item.page_number == page_number]


def _box_to_dict(box: BoundingBox | None) -> dict | None:
    if box is None:
        return None
    return {
        "page_number": box.page_number,
        "left": box.left,
        "top": box.top,
        "right": box.right,
        "bottom": box.bottom,
        "reference_width": box.reference_width,
        "reference_height": box.reference_height,
    }

