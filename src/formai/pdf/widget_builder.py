from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from formai.errors import IntegrationUnavailable
from formai.models import BoundingBox, DetectedField, FieldKind
from formai.pdf.geometry import bounding_box_to_pdf_rect, optimal_font_size


@dataclass(frozen=True)
class WidgetDefinition:
    name: str
    field_kind: FieldKind
    page_index: int
    box: BoundingBox
    tooltip: str = ""
    multiline: bool = False
    max_len: int | None = None


def build_fillable_pdf(
    *,
    input_path: Path,
    output_path: Path,
    widgets: Iterable[WidgetDefinition],
) -> None:
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import (
            ArrayObject,
            BooleanObject,
            DictionaryObject,
            FloatObject,
            NameObject,
            NumberObject,
            TextStringObject,
        )
    except ImportError as exc:
        raise IntegrationUnavailable("pypdf is required for direct AcroForm creation.") from exc

    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    field_refs = ArrayObject()
    widgets_by_page: dict[int, List[DictionaryObject]] = {}

    for widget in widgets:
        widgets_by_page.setdefault(widget.page_index, []).append(
            _build_widget_dict(
                widget=widget,
                page_height=float(writer.pages[widget.page_index].mediabox.height),
                dict_cls=DictionaryObject,
                name_cls=NameObject,
                text_cls=TextStringObject,
                array_cls=ArrayObject,
                float_cls=FloatObject,
                number_cls=NumberObject,
            )
        )

    for page_index, page in enumerate(writer.pages):
        annot_refs = page.get("/Annots") or ArrayObject()
        if not isinstance(annot_refs, ArrayObject):
            annot_refs = ArrayObject(list(annot_refs))
        for widget_dict in widgets_by_page.get(page_index, []):
            widget_ref = writer._add_object(widget_dict)
            annot_refs.append(widget_ref)
            field_refs.append(widget_ref)
        page[NameObject("/Annots")] = annot_refs

    acroform = writer._root_object.get("/AcroForm")
    if acroform is None:
        acroform = DictionaryObject()
        writer._root_object[NameObject("/AcroForm")] = acroform

    acroform[NameObject("/Fields")] = field_refs
    acroform[NameObject("/NeedAppearances")] = BooleanObject(True)
    acroform[NameObject("/DA")] = TextStringObject("/Helv 9 Tf 0 0 0 rg")
    acroform[NameObject("/DR")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/Helv"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )

    with output_path.open("wb") as handle:
        writer.write(handle)


def widget_definitions_from_detected_fields(
    detected_fields: Iterable[DetectedField],
    rename_map: dict[str, str],
) -> List[WidgetDefinition]:
    widgets: List[WidgetDefinition] = []
    for field in detected_fields:
        target_name = rename_map.get(field.label, field.label)
        widgets.append(
            WidgetDefinition(
                name=target_name,
                field_kind=field.field_kind,
                page_index=max(0, field.box.page_number - 1),
                box=field.box,
                tooltip=field.label,
                multiline=field.field_kind == FieldKind.MULTILINE,
            )
        )
    return widgets


def _build_widget_dict(
    *,
    widget: WidgetDefinition,
    page_height: float,
    dict_cls,
    name_cls,
    text_cls,
    array_cls,
    float_cls,
    number_cls,
):
    pdf_rect = bounding_box_to_pdf_rect(widget.box, page_height)
    rect = array_cls(
        [
            float_cls(pdf_rect.left),
            float_cls(pdf_rect.bottom),
            float_cls(pdf_rect.right),
            float_cls(pdf_rect.top),
        ]
    )

    if widget.field_kind == FieldKind.CHECKBOX:
        return _checkbox_widget_dict(widget, rect, dict_cls, name_cls, text_cls, number_cls)
    if widget.field_kind == FieldKind.RADIO:
        return _radio_widget_dict(widget, rect, dict_cls, name_cls, text_cls, number_cls)
    if widget.field_kind == FieldKind.SIGNATURE:
        return _text_widget_dict(widget, rect, dict_cls, name_cls, text_cls, number_cls, multiline=False)
    return _text_widget_dict(
        widget,
        rect,
        dict_cls,
        name_cls,
        text_cls,
        number_cls,
        multiline=widget.multiline,
    )


def _text_widget_dict(
    widget: WidgetDefinition,
    rect,
    dict_cls,
    name_cls,
    text_cls,
    number_cls,
    *,
    multiline: bool,
):
    font_size = optimal_font_size(widget.box.height, multiline=multiline)
    flags = 0
    if multiline:
        flags |= 1 << 12
    field = dict_cls()
    field.update(
        {
            name_cls("/Type"): name_cls("/Annot"),
            name_cls("/Subtype"): name_cls("/Widget"),
            name_cls("/FT"): name_cls("/Tx"),
            name_cls("/T"): text_cls(widget.name),
            name_cls("/TU"): text_cls(widget.tooltip or widget.name),
            name_cls("/V"): text_cls(""),
            name_cls("/Rect"): rect,
            name_cls("/F"): number_cls(4),
            name_cls("/DA"): text_cls(f"/Helv {font_size:.1f} Tf 0 0 0 rg"),
            name_cls("/MK"): dict_cls(),
            name_cls("/BS"): dict_cls({name_cls("/W"): number_cls(0)}),
            name_cls("/Ff"): number_cls(flags),
            name_cls("/Q"): number_cls(0),
        }
    )
    if widget.max_len:
        field[name_cls("/MaxLen")] = number_cls(int(widget.max_len))
    return field


def _checkbox_widget_dict(widget: WidgetDefinition, rect, dict_cls, name_cls, text_cls, number_cls):
    field = dict_cls()
    field.update(
        {
            name_cls("/Type"): name_cls("/Annot"),
            name_cls("/Subtype"): name_cls("/Widget"),
            name_cls("/FT"): name_cls("/Btn"),
            name_cls("/T"): text_cls(widget.name),
            name_cls("/TU"): text_cls(widget.tooltip or widget.name),
            name_cls("/V"): name_cls("/Off"),
            name_cls("/AS"): name_cls("/Off"),
            name_cls("/Rect"): rect,
            name_cls("/F"): number_cls(4),
            name_cls("/MK"): dict_cls({name_cls("/CA"): text_cls("4")}),
        }
    )
    return field


def _radio_widget_dict(widget: WidgetDefinition, rect, dict_cls, name_cls, text_cls, number_cls):
    field = dict_cls()
    field.update(
        {
            name_cls("/Type"): name_cls("/Annot"),
            name_cls("/Subtype"): name_cls("/Widget"),
            name_cls("/FT"): name_cls("/Btn"),
            name_cls("/T"): text_cls(widget.name),
            name_cls("/TU"): text_cls(widget.tooltip or widget.name),
            name_cls("/V"): name_cls("/Off"),
            name_cls("/AS"): name_cls("/Off"),
            name_cls("/Rect"): rect,
            name_cls("/F"): number_cls(4),
            name_cls("/Ff"): number_cls(1 << 15),
        }
    )
    return field
