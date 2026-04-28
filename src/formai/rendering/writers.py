from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Sequence

from formai.models import BoundingBox, FieldKind
from formai.rendering.contracts import (
    RenderContentRun,
    RenderPolicy,
    RenderWriterKind,
)
CONTACT_SPLIT_RE = re.compile(r"\s*(?:/|;|\||\n)\s*")
PHONE_RE = re.compile(r"(?:\+?\d[\d()\-\s]{6,}\d)")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
DATE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")


@dataclass(frozen=True)
class RenderWriter:
    kind: RenderWriterKind
    line_policy: str = "single"
    split_policy: str = "none"
    wrap_mode: str = "truncate"
    max_lines: int | None = None

    def build_runs(self, field_name: str, value: str) -> List[RenderContentRun]:
        text = _normalize_value(value)
        if not text:
            return []
        return [RenderContentRun(text=text, role="body", field_name=field_name)]

    def build_policy(
        self,
        *,
        field_name: str,
        box: BoundingBox | None,
        font_size: float | None = None,
        multiline_font_size: float | None = None,
        horizontal_inset: float = 1.5,
        baseline_inset: float = 0.8,
        top_inset: float = 1.8,
        background_padding: float = 1.0,
        source: str = "heuristic",
    ) -> RenderPolicy:
        return RenderPolicy(
            writer_kind=self.kind,
            font_size=font_size,
            multiline_font_size=multiline_font_size,
            horizontal_inset=horizontal_inset,
            baseline_inset=baseline_inset,
            top_inset=top_inset,
            background_padding=background_padding,
            line_policy=self.line_policy,
            split_policy=self.split_policy,
            wrap_mode=self.wrap_mode,
            max_lines=self.max_lines,
            source=source,
        )


class InlineRunWriter(RenderWriter):
    def __init__(self) -> None:
        super().__init__(RenderWriterKind.INLINE, line_policy="single", split_policy="inline", wrap_mode="shrink")


class SingleLineFieldWriter(RenderWriter):
    def __init__(self) -> None:
        super().__init__(RenderWriterKind.SINGLE_LINE, line_policy="single", split_policy="none", wrap_mode="truncate")


class CompoundContactWriter(RenderWriter):
    def __init__(self) -> None:
        super().__init__(
            RenderWriterKind.COMPOUND_CONTACT,
            line_policy="single",
            split_policy="contact",
            wrap_mode="fit",
        )

    def build_runs(self, field_name: str, value: str) -> List[RenderContentRun]:
        text = _normalize_value(value)
        if not text:
            return []

        runs: list[RenderContentRun] = []
        for segment in CONTACT_SPLIT_RE.split(text):
            segment = segment.strip()
            if not segment:
                continue
            role = "body"
            if EMAIL_RE.search(segment):
                role = "email"
            elif PHONE_RE.search(segment):
                role = "phone"
            runs.append(RenderContentRun(text=segment, role=role, field_name=field_name))
        return runs or [RenderContentRun(text=text, role="body", field_name=field_name)]


class TableCellWriter(RenderWriter):
    def __init__(self) -> None:
        super().__init__(
            RenderWriterKind.TABLE_CELL,
            line_policy="single",
            split_policy="cell",
            wrap_mode="shrink",
        )


class DateSignatureWriter(RenderWriter):
    def __init__(self) -> None:
        super().__init__(
            RenderWriterKind.DATE_SIGNATURE,
            line_policy="single",
            split_policy="date_signature",
            wrap_mode="fit",
        )

    def build_runs(self, field_name: str, value: str) -> List[RenderContentRun]:
        text = _normalize_value(value)
        if not text:
            return []

        if "/" in text:
            left, right = [segment.strip() for segment in text.split("/", 1)]
            runs = []
            if left:
                runs.append(RenderContentRun(text=left, role="date", field_name=field_name))
            if right:
                runs.append(RenderContentRun(text=right, role="signature", field_name=field_name))
            if runs:
                return runs

        if DATE_RE.search(text):
            return [RenderContentRun(text=text, role="date", field_name=field_name)]
        return [RenderContentRun(text=text, role="body", field_name=field_name)]


class MultilineBlockWriter(RenderWriter):
    def __init__(self) -> None:
        super().__init__(
            RenderWriterKind.MULTILINE,
            line_policy="paragraph",
            split_policy="lines",
            wrap_mode="wrap",
            max_lines=None,
        )

    def build_runs(self, field_name: str, value: str) -> List[RenderContentRun]:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return []
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        return [
            RenderContentRun(text=line, role=f"line_{index + 1}", field_name=field_name)
            for index, line in enumerate(lines)
        ]


_WRITER_REGISTRY: dict[RenderWriterKind, RenderWriter] = {
    RenderWriterKind.INLINE: InlineRunWriter(),
    RenderWriterKind.SINGLE_LINE: SingleLineFieldWriter(),
    RenderWriterKind.COMPOUND_CONTACT: CompoundContactWriter(),
    RenderWriterKind.TABLE_CELL: TableCellWriter(),
    RenderWriterKind.DATE_SIGNATURE: DateSignatureWriter(),
    RenderWriterKind.MULTILINE: MultilineBlockWriter(),
}


def get_render_writer(kind: RenderWriterKind) -> RenderWriter:
    return _WRITER_REGISTRY[kind]


def normalize_render_value(value: str) -> str:
    return _normalize_value(value)


def split_contact_value(value: str) -> List[RenderContentRun]:
    return _WRITER_REGISTRY[RenderWriterKind.COMPOUND_CONTACT].build_runs("contact", value)


def split_date_signature_value(value: str) -> List[RenderContentRun]:
    return _WRITER_REGISTRY[RenderWriterKind.DATE_SIGNATURE].build_runs("date_signature", value)


def split_multiline_value(value: str) -> List[RenderContentRun]:
    return _WRITER_REGISTRY[RenderWriterKind.MULTILINE].build_runs("multiline", value)


def _normalize_value(value: str) -> str:
    return " ".join(str(value or "").split())
