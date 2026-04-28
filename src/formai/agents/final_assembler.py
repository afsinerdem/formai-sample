from __future__ import annotations

import io
from pathlib import Path
import textwrap
from typing import Dict
from typing import List

from formai.agents.base import BaseAgent
from formai.errors import IntegrationUnavailable
from formai.fonts import resolve_preferred_font_path
from formai.llm.base import VisionLLMClient
from formai.mapping import resolve_filled_values
from formai.models import AcroField, AssemblyResult, ExtractionResult, FieldKind, IssueSeverity, ProcessingIssue
from formai.pdf.inspector import inspect_pdf_fields
from formai.profiles import infer_profile_from_target_fields
from formai.rendering import compile_render_plan
from formai.segmentation import OverflowDetail, expand_values_for_template_fields
from formai.self_check import run_field_level_self_check
from formai.utils import average_confidence, ensure_parent_directory


class FinalAssemblerAgent(BaseAgent):
    def __init__(
        self,
        config,
        llm_client: VisionLLMClient | None = None,
        perception_client: VisionLLMClient | None = None,
    ):
        super().__init__(config)
        self.llm_client = llm_client
        self.perception_client = perception_client

    def assemble(
        self,
        fillable_pdf_path: Path,
        extraction: ExtractionResult,
        output_path: Path,
        source_reference: Path | None = None,
    ) -> AssemblyResult:
        ensure_parent_directory(output_path)
        issues: List[ProcessingIssue] = []
        filled_values, mapping_confidence = resolve_filled_values(
            extraction.structured_data, extraction.mappings
        )

        if not fillable_pdf_path.exists():
            issues.append(
                ProcessingIssue(
                    code="assembly.template_missing",
                    message=f"Fillable template not found: {fillable_pdf_path}",
                    severity=IssueSeverity.ERROR,
                )
            )
            return AssemblyResult(output_path=output_path, issues=issues, confidence=0.0)

        if not filled_values:
            issues.append(
                ProcessingIssue(
                    code="assembly.no_values",
                    message="No field values were resolved for PDF injection.",
                    severity=IssueSeverity.ERROR,
                )
            )
            return AssemblyResult(output_path=output_path, issues=issues, confidence=0.0)

        try:
            template_fields = inspect_pdf_fields(fillable_pdf_path)
        except IntegrationUnavailable as exc:
            issues.append(
                ProcessingIssue(
                    code="assembly.template_inspection_failed",
                    message=str(exc),
                    severity=IssueSeverity.ERROR,
                )
            )
            return AssemblyResult(
                output_path=output_path,
                filled_values=filled_values,
                issues=issues,
                confidence=0.0,
            )
        overflow_strategy = self._normalized_overflow_strategy()
        fitting_strategy = (
            "same_page_compact"
            if overflow_strategy in {"same_page_compact", "same_page_note"}
            else "readable_cut"
        )
        expanded_values = expand_values_for_template_fields(
            filled_values,
            template_fields,
            fitting_strategy=fitting_strategy,
        )
        filled_values = expanded_values.filled_values
        if expanded_values.overflow:
            for field_name, detail in expanded_values.overflow.items():
                issues.append(
                    ProcessingIssue(
                        code="assembly.visual_overflow",
                        message=f"Field value was truncated for readability: {field_name}",
                        severity=IssueSeverity.WARNING,
                        context={
                            "field_name": field_name,
                            "original_text": detail.original_text,
                            "written_text": detail.written_text,
                            "overflow_text": detail.overflow_text,
                        },
                    )
                )

        try:
            profile = infer_profile_from_target_fields(template_fields)
            render_plan = compile_render_plan(
                template_fields,
                filled_values=filled_values,
                profile=profile,
            )
            self._render_user_facing_pdf(
                fillable_pdf_path=fillable_pdf_path,
                template_fields=template_fields,
                filled_values=filled_values,
                render_plan=render_plan,
                output_path=output_path,
            )
        except IntegrationUnavailable as exc:
            issues.append(
                ProcessingIssue(
                    code="assembly.pdf_write_failed",
                    message=str(exc),
                    severity=IssueSeverity.ERROR,
                )
            )
            return AssemblyResult(
                output_path=output_path,
                filled_values=filled_values,
                issues=issues,
                confidence=0.0,
            )
        except Exception as exc:
            issues.append(
                ProcessingIssue(
                    code="assembly.unexpected_error",
                    message=f"Unexpected PDF assembly failure: {exc}",
                    severity=IssueSeverity.ERROR,
                )
            )
            return AssemblyResult(
                output_path=output_path,
                filled_values=filled_values,
                issues=issues,
                confidence=0.0,
            )
        if overflow_strategy == "same_page_note" and expanded_values.overflow:
            note_added = self._append_same_page_overflow_notes(
                output_path,
                template_fields,
                expanded_values.overflow,
            )
            if note_added:
                issues.append(
                    ProcessingIssue(
                        code="assembly.inline_overflow_note",
                        message=(
                            "Overflow text was appended into the remaining space on the same page."
                        ),
                        severity=IssueSeverity.INFO,
                        context={"field_count": str(len(expanded_values.overflow))},
                    )
                )
        elif overflow_strategy == "overflow_page" and expanded_values.overflow:
            appended_pages = self._append_overflow_pages(output_path, expanded_values.overflow)
            if appended_pages:
                issues.append(
                    ProcessingIssue(
                        code="assembly.overflow_continuation_page",
                        message=(
                            "Overflow text was appended to continuation page(s) for full readability."
                        ),
                        severity=IssueSeverity.INFO,
                        context={"page_count": str(appended_pages)},
                    )
                )
        overflow_penalty = 0.12 if expanded_values.overflow else 0.0
        confidence = max(
            0.0,
            average_confidence([mapping_confidence, extraction.confidence]) - overflow_penalty,
        )
        result = AssemblyResult(
            output_path=output_path,
            filled_values=filled_values,
            render_plan=list(render_plan.items) if 'render_plan' in locals() else [],
            render_plan_summary=render_plan.to_dict() if 'render_plan' in locals() else {},
            issues=issues,
            confidence=confidence,
        )
        if source_reference is not None and self.config.enable_output_self_check:
            self_check = run_field_level_self_check(
                source_reference=source_reference,
                output_pdf_path=output_path,
                template_fields=template_fields,
                filled_values=filled_values,
                min_source_similarity=self.config.self_check_min_source_similarity,
                min_output_similarity=self.config.self_check_min_output_similarity,
                raster_dpi=self.config.raster_dpi,
                llm_client=self.llm_client,
                perception_client=self.perception_client,
            )
            if self_check is not None:
                result.self_check = self_check
                if not self_check.passed:
                    issues.append(
                        ProcessingIssue(
                            code="assembly.self_check.review_required",
                            message=(
                                "Generated output is not sufficiently aligned with the source document."
                            ),
                            severity=IssueSeverity.WARNING,
                            context={
                                "overall_score": f"{self_check.overall_score:.3f}",
                                "source_score": f"{self_check.source_score:.3f}",
                                "output_score": f"{self_check.output_score:.3f}",
                                "layout_warnings": ", ".join(self_check.layout_warnings[:6]),
                            },
                        )
                    )
                    if self.config.strict_verification_gate:
                        issues.append(
                            ProcessingIssue(
                                code="assembly.self_check.blocking_review_required",
                                message="Strict verification gate rejected the generated output.",
                                severity=IssueSeverity.ERROR,
                                context={"overall_score": f"{self_check.overall_score:.3f}"},
                            )
                        )
        return result

    def _render_user_facing_pdf(
        self,
        *,
        fillable_pdf_path: Path,
        template_fields: List[AcroField],
        filled_values: Dict[str, str],
        render_plan,
        output_path: Path,
    ) -> None:
        try:
            from pypdf import PdfReader, PdfWriter
            from pypdf.generic import ArrayObject, NameObject
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise IntegrationUnavailable(
                "reportlab and pypdf are required for Unicode-safe final PDF rendering."
            ) from exc

        reader = PdfReader(str(fillable_pdf_path))
        writer = PdfWriter()
        font_name = self._register_overlay_font(pdfmetrics, TTFont)
        pages_by_number: Dict[int, List[AcroField]] = {}
        for field in template_fields:
            pages_by_number.setdefault(field.page_number, []).append(field)

        for page_number, page in enumerate(reader.pages, start=1):
            page_width = float(page.mediabox.right) - float(page.mediabox.left)
            page_height = float(page.mediabox.top) - float(page.mediabox.bottom)
            overlay_buffer = io.BytesIO()
            overlay = canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height))
            fields_by_name = {field.name: field for field in pages_by_number.get(page_number, [])}
            for item in render_plan.items_for_page(page_number):
                field = fields_by_name.get(item.field_name)
                if field is None or item.target_region is None or not item.value:
                    continue
                self._draw_render_plan_item(
                    overlay=overlay,
                    field=field,
                    plan_item=item,
                    page_height=page_height,
                    font_name=font_name,
                    measure_fn=pdfmetrics.stringWidth,
                )
            overlay.save()
            overlay_buffer.seek(0)
            overlay_reader = PdfReader(overlay_buffer)
            writer.add_page(page)
            writer.pages[-1].merge_page(overlay_reader.pages[0])
            writer.pages[-1][NameObject("/Annots")] = ArrayObject()

        if "/AcroForm" in writer._root_object:
            del writer._root_object["/AcroForm"]
        with output_path.open("wb") as handle:
            writer.write(handle)

    def _register_overlay_font(self, pdfmetrics, ttfont_cls) -> str:
        font_name = "FormAIUnicode"
        try:
            pdfmetrics.getFont(font_name)
            return font_name
        except KeyError:
            pass
        path = resolve_preferred_font_path(getattr(self.config, "font_family", "noto_sans"))
        if path is not None:
            pdfmetrics.registerFont(ttfont_cls(font_name, str(path)))
            return font_name
        return "Helvetica"

    def _draw_render_plan_item(
        self,
        *,
        overlay,
        field: AcroField,
        plan_item,
        page_height: float,
        font_name: str,
        measure_fn,
    ) -> None:
        box = plan_item.target_region
        if box is None:
            return
        policy = getattr(plan_item, "policy", None)
        width = max(10.0, box.width - 4.0)
        height = max(10.0, box.height - 3.0)
        horizontal_inset = getattr(policy, "horizontal_inset", 2.0)
        baseline_inset = getattr(policy, "baseline_inset", 2.0)
        top_inset = getattr(policy, "top_inset", 2.0)
        background_padding = getattr(policy, "background_padding", 1.0)
        left = box.left + horizontal_inset
        top_y = page_height - box.top - top_inset
        bottom_y = page_height - box.bottom + baseline_inset
        value = (plan_item.value or "").strip()
        if field.field_kind in {FieldKind.CHECKBOX, FieldKind.RADIO}:
            mark = "X" if value.strip().lower() not in {"", "0", "false", "no", "off"} else ""
            if not mark:
                return
            size = min(11.0, max(8.5, height - 1.0))
            overlay.setFont(font_name, size)
            overlay.drawString(left, bottom_y, mark)
            return

        run_texts = [run.text for run in getattr(plan_item, "content_runs", []) if getattr(run, "text", "").strip()]
        multiline = getattr(plan_item, "writer_kind", "") == "multiline" or field.field_kind == FieldKind.MULTILINE or "\n" in value or len(value) > 56
        font_size = self._resolve_plan_font_size(field, plan_item, value, width, height, multiline)
        overlay.setFillColorRGB(0, 0, 0)
        overlay.setFont(font_name, font_size)
        writer_kind = getattr(getattr(plan_item, "writer_kind", None), "value", getattr(plan_item, "writer_kind", ""))
        if writer_kind == "date_signature" and run_texts:
            self._draw_segmented_runs(
                overlay=overlay,
                left=left,
                bottom_y=bottom_y,
                width=width,
                box_width=box.width,
                runs=getattr(plan_item, "content_runs", []),
                font_name=font_name,
                font_size=font_size,
                measure_fn=measure_fn,
                background_padding=background_padding,
            )
            return
        if multiline:
            wrapped_lines = self._wrap_reportlab_text(
                "\n".join(run_texts) if run_texts else value,
                width,
                font_name=font_name,
                font_size=font_size,
                measure_fn=measure_fn,
            )
            cursor = top_y - font_size
            min_y = page_height - box.bottom + 1.0
            for line in wrapped_lines:
                if cursor < min_y:
                    break
                self._draw_text_background(
                    overlay=overlay,
                    left=left,
                    baseline_y=cursor,
                    text=line,
                    font_name=font_name,
                    font_size=font_size,
                    measure_fn=measure_fn,
                    max_width=box.width,
                    padding=background_padding,
                )
                overlay.drawString(left, cursor, line)
                cursor -= font_size * 1.18
            return
        if writer_kind == "compound_contact" and run_texts:
            text = " / ".join(run_texts)
        else:
            text = value
        self._draw_text_background(
            overlay=overlay,
            left=left,
            baseline_y=bottom_y,
            text=text,
            font_name=font_name,
            font_size=font_size,
            measure_fn=measure_fn,
            max_width=box.width,
            padding=background_padding,
        )
        overlay.drawString(left, bottom_y, text)

    def _resolve_plan_font_size(
        self,
        field: AcroField,
        plan_item,
        value: str,
        width: float,
        height: float,
        multiline: bool,
    ) -> float:
        preferred = 9.4
        minimum = 7.6
        policy = getattr(plan_item, "policy", None)
        if policy is not None and not multiline and getattr(policy, "font_size", None) is not None:
            preferred = float(policy.font_size)
            minimum = min(minimum, preferred)
        if policy is not None and multiline and getattr(policy, "multiline_font_size", None) is not None:
            preferred = float(policy.multiline_font_size)
            minimum = min(minimum, preferred)
        longest_line = max((len(line) for line in value.splitlines()), default=len(value) or 1)
        width_limit = width / max(1.0, longest_line * 0.52)
        height_limit = height / (1.25 if not multiline else 2.1)
        return round(max(minimum, min(preferred, width_limit, height_limit)), 1)

    def _draw_segmented_runs(
        self,
        *,
        overlay,
        left: float,
        bottom_y: float,
        width: float,
        box_width: float,
        runs,
        font_name: str,
        font_size: float,
        measure_fn,
        background_padding: float,
    ) -> None:
        if not runs:
            return
        if len(runs) == 1:
            text = runs[0].text
            self._draw_text_background(
                overlay=overlay,
                left=left,
                baseline_y=bottom_y,
                text=text,
                font_name=font_name,
                font_size=font_size,
                measure_fn=measure_fn,
                max_width=box_width,
                padding=background_padding,
            )
            overlay.drawString(left, bottom_y, text)
            return
        first = runs[0].text
        second = runs[1].text
        self._draw_text_background(
            overlay=overlay,
            left=left,
            baseline_y=bottom_y,
            text=first,
            font_name=font_name,
            font_size=font_size,
            measure_fn=measure_fn,
            max_width=width * 0.48,
            padding=background_padding,
        )
        overlay.drawString(left, bottom_y, first)
        second_width = measure_fn(second, font_name, font_size)
        second_left = max(left + (width * 0.52), left + width - second_width)
        self._draw_text_background(
            overlay=overlay,
            left=second_left,
            baseline_y=bottom_y,
            text=second,
            font_name=font_name,
            font_size=font_size,
            measure_fn=measure_fn,
            max_width=box_width,
            padding=background_padding,
        )
        overlay.drawString(second_left, bottom_y, second)

    def _draw_text_background(
        self,
        *,
        overlay,
        left: float,
        baseline_y: float,
        text: str,
        font_name: str,
        font_size: float,
        measure_fn,
        max_width: float,
        padding: float,
    ) -> None:
        if padding <= 0.0:
            return
        text_width = min(max_width, measure_fn(text, font_name, font_size) + (padding * 2.0))
        rect_height = max(font_size + (padding * 2.0), 6.0)
        overlay.setFillColorRGB(1, 1, 1)
        overlay.rect(
            left - padding,
            baseline_y - (font_size * 0.22) - padding,
            max(1.0, text_width),
            rect_height,
            stroke=0,
            fill=1,
        )
        overlay.setFillColorRGB(0, 0, 0)

    def _normalized_overflow_strategy(self) -> str:
        return (self.config.overflow_strategy or "readable_cut").strip().lower()

    def _append_overflow_pages(
        self,
        output_path: Path,
        overflow_details: Dict[str, OverflowDetail],
    ) -> int:
        if not overflow_details:
            return 0
        try:
            from pypdf import PdfReader, PdfWriter
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise IntegrationUnavailable(
                "reportlab and pypdf are required for overflow continuation pages."
            ) from exc

        reader = PdfReader(str(output_path))
        if reader.pages:
            page = reader.pages[0]
            page_size = (
                float(page.mediabox.right) - float(page.mediabox.left),
                float(page.mediabox.top) - float(page.mediabox.bottom),
            )
        else:
            page_size = letter

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=page_size)
        font_name = self._register_overlay_font(pdfmetrics, TTFont)
        width, height = page_size
        left = 54.0
        right = width - 54.0
        top = height - 54.0
        bottom = 54.0
        paragraph_spacing = 10.0
        title_size = 14.0
        heading_size = 10.0
        body_size = 9.5

        def start_page() -> float:
            pdf.setFont(font_name, title_size)
            pdf.drawString(left, top, "Form Continuation Notes")
            pdf.setFont(font_name, 9)
            pdf.drawString(
                left,
                top - 16,
                "Overflow text from the main form is continued below.",
            )
            return top - 38

        def ensure_space(cursor: float, needed_height: float) -> float:
            if cursor - needed_height >= bottom:
                return cursor
            pdf.showPage()
            return start_page()

        cursor = start_page()
        appended_pages = 1

        for field_name, detail in overflow_details.items():
            label = self._display_label(field_name)
            body_text = detail.overflow_text.strip() or detail.original_text.strip()
            wrapped_lines = self._wrap_reportlab_text(
                body_text,
                right - left,
                font_name=font_name,
                font_size=body_size,
                measure_fn=pdfmetrics.stringWidth,
            )
            needed_height = 18.0 + max(14.0, len(wrapped_lines) * 12.0) + paragraph_spacing
            new_cursor = ensure_space(cursor, needed_height)
            if new_cursor != cursor:
                appended_pages += 1
            cursor = new_cursor
            pdf.setFont(font_name, heading_size)
            pdf.drawString(left, cursor, label)
            cursor -= 14.0
            pdf.setFont(font_name, body_size)
            for line in wrapped_lines:
                pdf.drawString(left, cursor, line)
                cursor -= 12.0
            cursor -= paragraph_spacing

        pdf.save()
        buffer.seek(0)
        continuation_reader = PdfReader(buffer)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for page in continuation_reader.pages:
            writer.add_page(page)
        with output_path.open("wb") as handle:
            writer.write(handle)
        return appended_pages

    def _wrap_reportlab_text(
        self,
        text: str,
        width: float,
        *,
        font_name: str,
        font_size: float,
        measure_fn,
    ) -> List[str]:
        lines: List[str] = []
        paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for paragraph in paragraphs:
            clean = " ".join(paragraph.split())
            if not clean:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            words = clean.split(" ")
            current = ""
            for word in words:
                candidate = word if not current else f"{current} {word}"
                if measure_fn(candidate, font_name, font_size) <= width:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                    current = word
                    continue
                lines.extend(textwrap.wrap(word, width=max(8, int(width / 5.0))) or [word])
                current = ""
            if current:
                lines.append(current)
        return lines or [""]

    def _display_label(self, field_name: str) -> str:
        label = field_name.replace("__body", "").replace("_", " ").strip()
        if not label:
            return "Continued Field"
        return label.title()

    def _footnote_label(self, field_name: str) -> str:
        normalized = field_name.replace("__body", "").replace("_", " ").strip().lower()
        if "incident" in normalized:
            return "Incident"
        if "witness" in normalized:
            return "Witnesses"
        if "injur" in normalized:
            return "Injuries"
        if "address" in normalized:
            return "Address"
        words = [word for word in self._display_label(field_name).split() if word]
        return " ".join(words[:2]) if words else "Continued"

    def _append_same_page_overflow_notes(
        self,
        output_path: Path,
        template_fields,
        overflow_details: Dict[str, OverflowDetail],
    ) -> bool:
        if not overflow_details:
            return False
        try:
            from pypdf import PdfReader, PdfWriter
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise IntegrationUnavailable(
                "reportlab and pypdf are required for same-page overflow notes."
            ) from exc

        reader = PdfReader(str(output_path))
        if not reader.pages:
            return False
        first_page = reader.pages[0]
        page_width = float(first_page.mediabox.right) - float(first_page.mediabox.left)
        page_height = float(first_page.mediabox.top) - float(first_page.mediabox.bottom)
        note_top = self._same_page_note_top(template_fields, page_height)
        note_bottom_margin = 44.0
        note_height = page_height - note_top - note_bottom_margin
        if note_height < 28.0:
            return False

        left = 52.0
        right = page_width - 52.0
        body_size = 7.1
        line_height = 8.6

        content_lines: List[str] = []
        font_name = self._register_overlay_font(pdfmetrics, TTFont)
        for field_name, detail in overflow_details.items():
            label = f"{self._footnote_label(field_name)} cont.:"
            wrapped_body = self._wrap_reportlab_text(
                detail.overflow_text.strip() or detail.original_text.strip(),
                right - left,
                font_name=font_name,
                font_size=body_size,
                measure_fn=pdfmetrics.stringWidth,
            )
            combined_lines = self._wrap_reportlab_text(
                " ".join([label, wrapped_body[0] if wrapped_body else ""]).strip(),
                right - left,
                font_name=font_name,
                font_size=body_size,
                measure_fn=pdfmetrics.stringWidth,
            )
            continuation_lines = wrapped_body[1:] if len(wrapped_body) > 1 else []
            content_lines.extend(combined_lines)
            content_lines.extend([f"__INDENT__{line}" for line in continuation_lines])
            content_lines.append("")

        if content_lines and content_lines[-1] == "":
            content_lines.pop()

        max_lines = min(2, max(1, int(note_height // line_height)))
        if not content_lines or max_lines <= 0:
            return False
        if len(content_lines) > max_lines:
            content_lines = content_lines[:max_lines]
            if content_lines:
                last = content_lines[-1].replace("__INDENT__", "")
                if not last.endswith("..."):
                    prefix = "__INDENT__" if content_lines[-1].startswith("__INDENT__") else ""
                    content_lines[-1] = f"{prefix}{last.rstrip('.')}..."

        buffer = io.BytesIO()
        overlay = canvas.Canvas(buffer, pagesize=(page_width, page_height))
        font_name = self._register_overlay_font(pdfmetrics, TTFont)
        cursor = page_height - note_top
        for line in content_lines:
            if line.startswith("__INDENT__"):
                overlay.setFillGray(0.43)
                overlay.setFont(font_name, body_size)
                overlay.drawString(left + 18.0, cursor, line.replace("__INDENT__", "", 1))
            else:
                overlay.setFillGray(0.42)
                overlay.setFont(font_name, body_size)
                overlay.drawString(left, cursor, line)
            cursor -= line_height
        overlay.save()
        buffer.seek(0)

        overlay_reader = PdfReader(buffer)
        writer = PdfWriter()
        for index, page in enumerate(reader.pages):
            writer.add_page(page)
            if index == 0:
                writer.pages[index].merge_page(overlay_reader.pages[0])
        with output_path.open("wb") as handle:
            writer.write(handle)
        return True

    def _same_page_note_top(self, template_fields, page_height: float) -> float:
        max_bottom = 0.0
        for field in template_fields:
            if field.page_number != 1 or field.box is None:
                continue
            max_bottom = max(max_bottom, float(field.box.bottom))
        preferred_top = max_bottom + 8.0
        return min(max(preferred_top, page_height - 156.0), page_height - 92.0)
