from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from formai.errors import IntegrationUnavailable
from formai.models import AcroField, BoundingBox, FieldKind
from formai.utils import normalize_text


def inspect_pdf_fields(pdf_path: Path) -> List[AcroField]:
    PdfReader, _, _, _, _, _, _ = _import_pypdf()
    reader = PdfReader(str(pdf_path))
    fields: List[AcroField] = []

    for page_number, page in enumerate(reader.pages, start=1):
        annotations = page.get("/Annots") or []
        for annotation_ref in annotations:
            annotation = annotation_ref.get_object()
            if annotation.get("/Subtype") != "/Widget":
                continue

            field_object = _resolve_field_object(annotation)
            name = _read_text_value(field_object.get("/T")) or _read_text_value(
                annotation.get("/T")
            )
            if not name:
                continue

            rect = annotation.get("/Rect") or field_object.get("/Rect")
            page_width = float(page.mediabox.right) - float(page.mediabox.left)
            page_height = float(page.mediabox.top) - float(page.mediabox.bottom)
            box = _rect_to_bounding_box(rect, page_number, page_width, page_height)
            field_type = _resolve_field_kind(
                _read_name_value(field_object.get("/FT")) or _read_name_value(annotation.get("/FT"))
            )
            value = _read_text_value(field_object.get("/V")) or _read_text_value(
                annotation.get("/V")
            )

            fields.append(
                AcroField(
                    name=name,
                    field_kind=field_type,
                    box=box,
                    page_number=page_number,
                    value=value,
                    label=name,
                )
            )

    return _deduplicate_fields(fields)


def extract_non_empty_field_values(pdf_path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for field in inspect_pdf_fields(pdf_path):
        if field.value not in (None, ""):
            values[field.name] = field.value
    return values


def prune_pdf_fields(input_path: Path, output_path: Path, allowed_names: List[str]) -> None:
    PdfReader, PdfWriter, _, NameObject, _, ArrayObject, _ = _import_pypdf()
    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    allowed = set(allowed_names)
    kept_refs = ArrayObject()
    seen_ref_ids = set()

    for page in writer.pages:
        annotations = page.get("/Annots") or []
        kept_annots = ArrayObject()
        for annotation_ref in annotations:
            annotation = annotation_ref.get_object()
            if annotation.get("/Subtype") != "/Widget":
                kept_annots.append(annotation_ref)
                continue

            field_object = _resolve_field_object(annotation)
            current_name = _read_text_value(field_object.get("/T")) or _read_text_value(
                annotation.get("/T")
            )
            if not current_name or current_name not in allowed:
                continue
            kept_annots.append(annotation_ref)
            ref = annotation.get("/Parent") or annotation_ref
            ref_id = getattr(ref, "idnum", None) or id(ref)
            if ref_id in seen_ref_ids:
                continue
            kept_refs.append(ref)
            seen_ref_ids.add(ref_id)

        page[NameObject("/Annots")] = kept_annots

    if "/AcroForm" in writer._root_object:
        writer._root_object["/AcroForm"][NameObject("/Fields")] = kept_refs

    with output_path.open("wb") as handle:
        writer.write(handle)


def rename_pdf_fields(input_path: Path, rename_map: Dict[str, str], output_path: Path) -> None:
    PdfReader, PdfWriter, _, NameObject, TextStringObject, _, _ = _import_pypdf()
    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    for page in writer.pages:
        annotations = page.get("/Annots") or []
        for annotation_ref in annotations:
            annotation = annotation_ref.get_object()
            if annotation.get("/Subtype") != "/Widget":
                continue
            field_object = _resolve_field_object(annotation)
            current_name = _read_text_value(field_object.get("/T")) or _read_text_value(
                annotation.get("/T")
            )
            if not current_name or current_name not in rename_map:
                continue
            new_name = rename_map[current_name]
            field_object[NameObject("/T")] = TextStringObject(new_name)
            annotation[NameObject("/T")] = TextStringObject(new_name)

    with output_path.open("wb") as handle:
        writer.write(handle)


def fill_pdf_fields(input_path: Path, values: Dict[str, str], output_path: Path) -> None:
    PdfReader, PdfWriter, BooleanObject, NameObject, TextStringObject, _, NumberObject = _import_pypdf()
    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    for page in writer.pages:
        page_text_values: Dict[str, str] = {}
        annotations = page.get("/Annots") or []
        for annotation_ref in annotations:
            annotation = annotation_ref.get_object()
            if annotation.get("/Subtype") != "/Widget":
                continue
            field_object = _resolve_field_object(annotation)
            field_name = _read_text_value(field_object.get("/T")) or _read_text_value(
                annotation.get("/T")
            )
            if not field_name or field_name not in values:
                continue
            field_type = _read_name_value(field_object.get("/FT")) or _read_name_value(
                annotation.get("/FT")
            )
            if field_type == "/Btn":
                _set_button_field_value(
                    field_object,
                    annotation,
                    values[field_name],
                    name_object=NameObject,
                    text_string_object=TextStringObject,
                )
                continue
            _set_text_field_appearance(
                field_name,
                field_object,
                annotation,
                values[field_name],
                name_object=NameObject,
                text_string_object=TextStringObject,
                number_object=NumberObject,
            )
            page_text_values[field_name] = values[field_name]
        if page_text_values:
            writer.update_page_form_field_values(
                page,
                page_text_values,
                auto_regenerate=False,
            )

    if "/AcroForm" in writer._root_object:
        writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)

    with output_path.open("wb") as handle:
        writer.write(handle)


def _set_button_field_value(
    field_object,
    annotation,
    raw_value: str,
    *,
    name_object,
    text_string_object,
) -> None:
    on_state = _checkbox_on_state(field_object, annotation)
    selected = _is_truthy_checkbox_value(raw_value)
    value_name = name_object(on_state if selected else "/Off")
    field_object[name_object("/V")] = value_name
    annotation[name_object("/V")] = value_name
    annotation[name_object("/AS")] = value_name
    if "/T" not in annotation and "/T" in field_object:
        annotation[name_object("/T")] = text_string_object(str(field_object["/T"]))


def _set_text_field_appearance(
    field_name: str,
    field_object,
    annotation,
    raw_value: str,
    *,
    name_object,
    text_string_object,
    number_object,
) -> None:
    font_size = _recommended_font_size(field_name, field_object, annotation, raw_value)
    da = text_string_object(f"/Helv {font_size:.1f} Tf 0 g")
    field_object[name_object("/DA")] = da
    annotation[name_object("/DA")] = da
    field_object[name_object("/Q")] = number_object(0)
    annotation[name_object("/Q")] = number_object(0)


def _checkbox_on_state(field_object, annotation) -> str:
    for candidate in (annotation, field_object):
        ap = candidate.get("/AP")
        if ap is None:
            continue
        normal = ap.get("/N")
        if normal is None:
            continue
        for key in normal.keys():
            raw_key = str(key)
            if raw_key != "/Off":
                return raw_key
    return "/Yes"


def _recommended_font_size(field_name: str, field_object, annotation, raw_value: str) -> float:
    rect = annotation.get("/Rect") or field_object.get("/Rect")
    if rect is None or len(rect) != 4:
        return 10.8
    left, bottom, right, top = [float(value) for value in rect]
    width = max(24.0, abs(right - left) - 6.0)
    height = max(12.0, abs(top - bottom) - 4.0)
    lines = [line.strip() for line in str(raw_value or "").splitlines() if line.strip()] or [""]
    longest_line = max((len(line) for line in lines), default=1)
    multiline = _is_multiline_text_field(field_object, annotation)
    preferred, minimum = _font_bucket(field_name, multiline)
    width_limit = width / max(1.0, longest_line * 0.50)
    height_limit = height / max(1.2, len(lines) * 1.18)
    return round(max(minimum, min(preferred, width_limit, height_limit)), 1)


def _font_bucket(field_name: str, multiline: bool) -> tuple[float, float]:
    normalized = normalize_text(field_name)
    if any(
        token in normalized
        for token in (
            "tarih",
            "ogrenci no",
            "egitim yili",
            "yariyil",
            "fakulte birim",
            "bolum program",
            "mali onay",
            "danisman tarih imza",
        )
    ):
        return 8.6, 8.0
    if any(
        token in normalized
        for token in (
            "ders kodu",
            "ders adi",
            "ders kredisi",
            "akts",
            "ders notu",
            "gno",
            "donem sayisi",
        )
    ):
        return 8.8, 8.2
    if any(
        token in normalized
        for token in (
            "ad soyad",
            "telefon",
            "e posta",
            "adres",
            "danisman adi",
            "ogrenci imzasi",
        )
    ):
        return 9.4, 8.8
    if multiline or "__body" in field_name or any(
        token in normalized
        for token in (
            "describe the incident",
            "describe the injuries",
            "contact info",
            "witnesses names",
        )
    ):
        return 9.2, 9.0
    if any(
        token in normalized
        for token in (
            "phone",
            "email",
            "e mail",
            "time",
            "report year",
            "identification",
            "driver s license",
            "passport",
            "other",
        )
    ):
        return 10.2, 9.8
    return 10.8, 10.2


def _is_multiline_text_field(field_object, annotation) -> bool:
    flags = field_object.get("/Ff")
    if flags is None:
        flags = annotation.get("/Ff")
    try:
        flag_value = int(flags or 0)
    except (TypeError, ValueError):
        flag_value = 0
    return bool(flag_value & 4096)


def _is_truthy_checkbox_value(value: str) -> bool:
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y", "on", "checked", "selected", "x"}


def _resolve_field_object(annotation):
    parent_ref = annotation.get("/Parent")
    if parent_ref is None:
        return annotation
    return parent_ref.get_object()


def _rect_to_bounding_box(
    rect,
    page_number: int,
    page_width: float | None = None,
    page_height: float | None = None,
) -> Optional[BoundingBox]:
    if rect is None or len(rect) != 4:
        return None
    left, pdf_bottom, right, pdf_top = [float(value) for value in rect]
    if page_height is None:
        top = min(pdf_bottom, pdf_top)
        bottom = max(pdf_bottom, pdf_top)
    else:
        top = page_height - pdf_top
        bottom = page_height - pdf_bottom
    return BoundingBox(
        page_number=page_number,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        reference_width=page_width,
        reference_height=page_height,
    )


def _resolve_field_kind(raw_kind: Optional[str]) -> FieldKind:
    if raw_kind == "/Btn":
        return FieldKind.CHECKBOX
    if raw_kind == "/Tx":
        return FieldKind.TEXT
    if raw_kind == "/Sig":
        return FieldKind.SIGNATURE
    if raw_kind == "/Ch":
        return FieldKind.TEXT
    return FieldKind.UNKNOWN


def _read_name_value(value) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _read_text_value(value) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _deduplicate_fields(fields: List[AcroField]) -> List[AcroField]:
    unique: Dict[str, AcroField] = {}
    for field in fields:
        if field.name not in unique:
            unique[field.name] = field
            continue
        existing = unique[field.name]
        if existing.box is None and field.box is not None:
            unique[field.name] = field
    return list(unique.values())


def deduplicate_fields_by_geometry(fields: List[AcroField]) -> List[AcroField]:
    unique: Dict[tuple, AcroField] = {}
    for field in fields:
        if field.box is None:
            key = (field.field_kind.value, field.page_number, field.name)
        else:
            key = (
                field.field_kind.value,
                field.page_number,
                round(field.box.left),
                round(field.box.top),
                round(field.box.right),
                round(field.box.bottom),
            )
        if key not in unique:
            unique[key] = field
    return list(unique.values())


def _import_pypdf():
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ArrayObject, BooleanObject, NameObject, NumberObject, TextStringObject
    except ImportError as exc:
        raise IntegrationUnavailable(
            "pypdf is not installed. Install project dependencies before processing PDFs."
        ) from exc
    return PdfReader, PdfWriter, BooleanObject, NameObject, TextStringObject, ArrayObject, NumberObject
