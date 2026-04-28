from __future__ import annotations

from pathlib import Path

import fitz

from formai.models import (
    TemplateAnchorCandidate,
    TemplateRule,
    TemplateStructureGraph,
    TemplateTableCell,
    TemplateTextSpan,
)


def build_template_structure_graph(pdf_path: Path) -> TemplateStructureGraph:
    document = fitz.open(str(pdf_path))
    page_sizes = []
    spans: list[TemplateTextSpan] = []
    rules: list[TemplateRule] = []
    table_cells: list[TemplateTableCell] = []
    anchor_candidates: list[TemplateAnchorCandidate] = []

    for page_number, page in enumerate(document, start=1):
        page_sizes.append(
            {
                "page_number": float(page_number),
                "width": float(page.rect.width),
                "height": float(page.rect.height),
            }
        )
        raw = page.get_text("rawdict")
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_text_parts: list[str] = []
                line_boxes = []
                for span in line.get("spans", []):
                    text = "".join(char.get("c", "") for char in span.get("chars", []))
                    bbox = span.get("bbox") or line.get("bbox")
                    if bbox is None:
                        continue
                    left, top, right, bottom = [float(value) for value in bbox]
                    spans.append(
                        TemplateTextSpan(
                            text=text,
                            page_number=page_number,
                            left=left,
                            top=top,
                            right=right,
                            bottom=bottom,
                            font_name=str(span.get("font", "")),
                        )
                    )
                    cleaned = " ".join(text.split()).strip()
                    if cleaned:
                        line_text_parts.append(cleaned)
                        line_boxes.append((left, top, right, bottom))
                if not line_text_parts or not line_boxes:
                    continue
                joined = " ".join(line_text_parts).strip()
                line_left = min(box[0] for box in line_boxes)
                line_top = min(box[1] for box in line_boxes)
                line_right = max(box[2] for box in line_boxes)
                line_bottom = max(box[3] for box in line_boxes)
                if ":" in joined:
                    label, _, _ = joined.partition(":")
                    anchor_candidates.append(
                        TemplateAnchorCandidate(
                            field_key=_anchor_key(label),
                            page_number=page_number,
                            anchor_type="colon",
                            label_text=label.strip(),
                            left=line_left,
                            top=line_top,
                            right=line_right,
                            bottom=line_bottom,
                        )
                    )
                if "..." in joined or "___" in joined:
                    anchor_candidates.append(
                        TemplateAnchorCandidate(
                            field_key=_anchor_key(joined),
                            page_number=page_number,
                            anchor_type="blank_run",
                            label_text=joined,
                            left=line_left,
                            top=line_top,
                            right=line_right,
                            bottom=line_bottom,
                        )
                    )

        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect is None:
                continue
            left, top, right, bottom = [float(value) for value in rect]
            width = abs(right - left)
            height = abs(bottom - top)
            if width >= 12.0 and height <= 3.5:
                rules.append(
                    TemplateRule(
                        kind="underline",
                        page_number=page_number,
                        left=left,
                        top=top,
                        right=right,
                        bottom=bottom,
                    )
                )
            elif width >= 12.0 and height >= 12.0:
                rules.append(
                    TemplateRule(
                        kind="box",
                        page_number=page_number,
                        left=left,
                        top=top,
                        right=right,
                        bottom=bottom,
                    )
                )

        try:
            tables = page.find_tables()
        except Exception:
            tables = []
        for table in tables:
            for row_index, row in enumerate(table.rows):
                for column_index, cell in enumerate(row.cells):
                    if not cell:
                        continue
                    left, top, right, bottom = [float(value) for value in cell]
                    table_cells.append(
                        TemplateTableCell(
                            page_number=page_number,
                            row_index=row_index,
                            column_index=column_index,
                            left=left,
                            top=top,
                            right=right,
                            bottom=bottom,
                        )
                    )

    document.close()
    return TemplateStructureGraph(
        page_count=len(page_sizes),
        page_sizes=page_sizes,
        spans=spans,
        rules=rules,
        table_cells=table_cells,
        anchor_candidates=anchor_candidates,
    )


def _anchor_key(text: str) -> str:
    normalized = "_".join(" ".join((text or "").split()).strip().lower().split())
    return normalized[:80]
