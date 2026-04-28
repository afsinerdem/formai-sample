from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import fitz

from formai.models import BoundingBox, DetectedField, FieldKind
from formai.utils import normalize_text, text_similarity


@dataclass(frozen=True)
class _AnchorFieldSpec:
    key: str
    terms: tuple[str, ...]
    field_kind: FieldKind
    strategy: str = "underline_right"
    min_width: float = 120.0
    height: float = 28.0


FIELD_SPECS: tuple[_AnchorFieldSpec, ...] = (
    _AnchorFieldSpec("tarih", ("Tarih", "Date"), FieldKind.DATE, "underline_above", 110.0, 28.0),
    _AnchorFieldSpec("ogrenci_no", ("Öğrenci No", "Student Number"), FieldKind.TEXT, "underline_below", 180.0, 30.0),
    _AnchorFieldSpec("tc_kimlik_no", ("T.C. Kimlik No", "TR Identity Number"), FieldKind.TEXT, "underline_right", 220.0, 30.0),
    _AnchorFieldSpec("fakulte_birim", ("Fakülte/Yüksekokul/", "Unit"), FieldKind.TEXT, "underline_below", 220.0, 30.0),
    _AnchorFieldSpec("ad_soyad", ("Ad Soyad", "First & Last Name"), FieldKind.TEXT, "underline_right", 220.0, 30.0),
    _AnchorFieldSpec("bolum_program", ("Bölüm/Program", "Department/Programme"), FieldKind.TEXT, "underline_right", 220.0, 30.0),
    _AnchorFieldSpec("telefon", ("Cep Telefon No", "GSMNumber"), FieldKind.TEXT, "underline_right", 220.0, 30.0),
    _AnchorFieldSpec("gano", ("GANO", "GPA"), FieldKind.NUMBER, "underline_right", 110.0, 30.0),
    _AnchorFieldSpec("e_posta", ("E-Posta Adresi", "E-mail Address"), FieldKind.TEXT, "underline_right", 260.0, 30.0),
    _AnchorFieldSpec("tamamlanan_kredi", ("Tamamlanan Kredi", "Credits Completed"), FieldKind.NUMBER, "underline_right", 130.0, 30.0),
)

TABLE_SPECS = (
    ("ders_kodu", ("Ders Kodu",), FieldKind.TEXT),
    ("ders_adi", ("Dersin Adı",), FieldKind.TEXT),
    ("ders_kredisi", ("Dersin Kredisi",), FieldKind.NUMBER),
    ("akts", ("AKTS",), FieldKind.NUMBER),
    ("ders_notu", ("Ders Notu",), FieldKind.TEXT),
)

SINGLE_COURSE_FIXED_SPECS = (
    ("fakulte_birim", FieldKind.TEXT, (186.0, 152.0, 322.0, 170.0)),
    ("ogrenci_no", FieldKind.TEXT, (46.0, 198.0, 138.0, 214.0)),
    ("egitim_yili", FieldKind.TEXT, (250.0, 197.0, 329.0, 214.0)),
    ("yariyil", FieldKind.TEXT, (344.0, 197.0, 389.0, 214.0)),
    ("bolum_program", FieldKind.TEXT, (332.0, 177.0, 519.0, 194.0)),
    ("ogrenci_imzasi", FieldKind.SIGNATURE, (409.0, 319.0, 503.0, 338.0)),
    ("ders_kodu", FieldKind.TEXT, (110.0, 385.0, 160.0, 419.0)),
    ("ders_adi", FieldKind.TEXT, (160.0, 385.0, 356.0, 419.0)),
    ("ders_kredisi", FieldKind.NUMBER, (356.0, 385.0, 430.0, 419.0)),
    ("akts", FieldKind.NUMBER, (438.0, 385.0, 482.0, 419.0)),
    ("ders_notu", FieldKind.TEXT, (492.0, 385.0, 533.0, 419.0)),
    ("danisman_gorusu", FieldKind.MULTILINE, (168.0, 454.0, 476.0, 491.0)),
    ("danisman_tarih_imza", FieldKind.TEXT, (94.0, 530.0, 340.0, 549.0)),
)

SINGLE_COURSE_ANCHOR_SPECS = (
    _AnchorFieldSpec("tarih", ("Tarih",), FieldKind.DATE, "underline_above", 96.0, 18.0),
    _AnchorFieldSpec("ad_soyad", ("Adı ve Soyadı", "Ad Soyad"), FieldKind.TEXT, "underline_right", 280.0, 16.0),
    _AnchorFieldSpec("adres", ("Adres",), FieldKind.MULTILINE, "underline_right", 320.0, 16.0),
    _AnchorFieldSpec("danisman_adi", ("Danışmanın Adı",), FieldKind.TEXT, "underline_right", 210.0, 16.0),
    _AnchorFieldSpec("gno", ("GNO",), FieldKind.NUMBER, "underline_right", 58.0, 14.0),
    _AnchorFieldSpec("donem_sayisi", ("Öğrencinin dönem sayısı",), FieldKind.NUMBER, "underline_right", 44.0, 14.0),
    _AnchorFieldSpec(
        "mali_onay_ders_akts",
        ("Ödenen Ders ve Kredi/AKTS Sayısı",),
        FieldKind.TEXT,
        "underline_right",
        96.0,
        16.0,
    ),
    _AnchorFieldSpec("mali_onay_ad_soyad", ("Adı Soyadı",), FieldKind.TEXT, "underline_right", 150.0, 16.0),
    _AnchorFieldSpec("mali_onay_tarih_imza", ("Tarih ve İmza",), FieldKind.TEXT, "underline_right", 176.0, 16.0),
)


def detect_student_petition_fields(pdf_path: Path) -> List[DetectedField]:
    document = fitz.open(str(pdf_path))
    emitted = set()
    fields: List[DetectedField] = []
    try:
        for page_index, page in enumerate(document, start=1):
            variant = _detect_layout_variant(page)
            if variant == "single_course_application":
                for field in _detect_single_course_application_fields(page, page_index):
                    _append_unique(fields, emitted, field)
                continue
            underline_candidates = _extract_underline_candidates(page, page_index)
            for spec in FIELD_SPECS:
                anchor = _find_anchor(page, spec.terms)
                if anchor is None:
                    continue
                candidate = _choose_candidate(page, spec, anchor, underline_candidates)
                if candidate is None:
                    continue
                field = DetectedField(
                    label=spec.key,
                    field_kind=spec.field_kind,
                    box=candidate,
                    confidence=0.88,
                    page_hint_text=" / ".join(spec.terms),
                )
                _append_unique(fields, emitted, field)

            for field in _detect_course_table_fields(page, page_index):
                _append_unique(fields, emitted, field)

            explanation = _detect_section_block(
                page,
                page_index,
                header_terms=("Öğrencinin Açıklaması", "Student's Explanation"),
                next_terms=("Ekler", "Attachments"),
                key="ogrenci_aciklamasi",
            )
            if explanation is not None:
                _append_unique(fields, emitted, explanation)

            advisor = _detect_section_block(
                page,
                page_index,
                header_terms=("Öğretim Üyesi/Danışman Görüşü",),
                next_terms=("İlgili Yönetim",),
                key="danisman_gorusu",
            )
            if advisor is not None:
                _append_unique(fields, emitted, advisor)

            signature = _detect_signature_line(page, page_index)
            if signature is not None:
                _append_unique(fields, emitted, signature)
    finally:
        document.close()
    return fields


def _detect_layout_variant(page: fitz.Page) -> str:
    text = page.get_text("text") or ""
    normalized = normalize_text(text)
    if "tek ders basvuru formu" in normalized:
        return "single_course_application"
    if "tek ders sinavina girecegi ders bilgileri" in normalized:
        return "single_course_application"
    if "tek ders" in normalized and "formu" in normalized and "ders kodu" in normalized:
        return "single_course_application"
    return "generic_student_petition"


def _detect_single_course_application_fields(page: fitz.Page, page_number: int) -> List[DetectedField]:
    width = float(page.rect.width or 595.0)
    height = float(page.rect.height or 842.0)
    detected: List[DetectedField] = []
    emitted: set[tuple] = set()
    underline_candidates = _extract_underline_candidates(page, page_number)

    for spec in SINGLE_COURSE_ANCHOR_SPECS:
        if spec.key == "tarih":
            anchor = _find_anchor_in_region(page, spec.terms, max_y=220.0)
        else:
            anchor = _find_anchor(page, spec.terms)
        if anchor is None:
            continue
        candidate = _choose_candidate(page, spec, anchor, underline_candidates)
        if candidate is None:
            continue
        _append_unique(
            detected,
            emitted,
            DetectedField(
                label=spec.key,
                field_kind=spec.field_kind,
                box=candidate,
                confidence=0.9,
                page_hint_text=" / ".join(spec.terms),
            ),
        )

    for field in _detect_single_course_contact_fields(page, page_number, underline_candidates):
        _append_unique(detected, emitted, field)

    for key, field_kind, (left, top, right, bottom) in SINGLE_COURSE_FIXED_SPECS:
        if top >= height or left >= width or any(existing.label == key for existing in detected):
            continue
        _append_unique(
            detected,
            emitted,
            DetectedField(
                label=key,
                field_kind=field_kind,
                box=BoundingBox(
                    page_number=page_number,
                    left=max(0.0, left),
                    top=max(0.0, top),
                    right=min(width - 4.0, right),
                    bottom=min(height - 4.0, bottom),
                ),
                confidence=0.9,
                page_hint_text=key,
            )
        )
    return detected


def _detect_single_course_contact_fields(
    page: fitz.Page,
    page_number: int,
    underline_candidates: Sequence[BoundingBox],
) -> List[DetectedField]:
    anchor = _find_anchor(page, ("Tel No / E-posta",))
    if anchor is None:
        return []
    spec = _AnchorFieldSpec("telefon", ("Tel No / E-posta",), FieldKind.TEXT, "underline_right", 280.0, 22.0)
    candidate = _choose_candidate(page, spec, anchor, underline_candidates)
    if candidate is None:
        return []
    split_x = candidate.left + (candidate.width * 0.46)
    row_height = 16.0
    top = candidate.top
    phone_box = BoundingBox(
        page_number=page_number,
        left=candidate.left,
        top=top,
        right=max(candidate.left + 70.0, split_x - 4.0),
        bottom=top + row_height,
    )
    email_box = BoundingBox(
        page_number=page_number,
        left=min(candidate.right - 110.0, split_x + 4.0),
        top=top,
        right=candidate.right,
        bottom=top + row_height,
    )
    return [
        DetectedField(
            label="telefon",
            field_kind=FieldKind.TEXT,
            box=phone_box,
            confidence=0.9,
            page_hint_text="Tel No / E-posta",
        ),
        DetectedField(
            label="e_posta",
            field_kind=FieldKind.TEXT,
            box=email_box,
            confidence=0.88,
            page_hint_text="Tel No / E-posta",
        ),
    ]


def _detect_course_table_fields(page: fitz.Page, page_number: int) -> List[DetectedField]:
    detected: List[DetectedField] = []
    for key, terms, field_kind in TABLE_SPECS:
        anchor = _find_anchor(page, terms)
        if anchor is None:
            continue
        box = BoundingBox(
            page_number=page_number,
            left=max(anchor.x0 - 18.0, 0.0),
            top=anchor.y1 + 8.0,
            right=anchor.x1 + 18.0,
            bottom=anchor.y1 + 44.0,
        )
        detected.append(
            DetectedField(
                label=key,
                field_kind=field_kind,
                box=box,
                confidence=0.84,
                page_hint_text=terms[0],
            )
        )
    return detected


def _detect_section_block(
    page: fitz.Page,
    page_number: int,
    *,
    header_terms: Sequence[str],
    next_terms: Sequence[str],
    key: str,
) -> DetectedField | None:
    header = _find_anchor(page, header_terms)
    if header is None:
        return None
    next_anchor = _find_anchor(page, next_terms)
    bottom = next_anchor.y0 - 12.0 if next_anchor is not None else min(page.rect.height - 40.0, header.y1 + 180.0)
    top = header.y1 + 12.0
    if bottom - top < 40.0:
        return None
    return DetectedField(
        label=key,
        field_kind=FieldKind.MULTILINE,
        box=BoundingBox(
            page_number=page_number,
            left=70.0,
            top=top,
            right=page.rect.width - 70.0,
            bottom=bottom,
        ),
        confidence=0.8,
        page_hint_text=header_terms[0],
    )


def _detect_signature_line(page: fitz.Page, page_number: int) -> DetectedField | None:
    anchor = _find_anchor(page, ("Öğrencinin İmzası", "Student's Signature"))
    if anchor is None:
        return None
    return DetectedField(
        label="ogrenci_imzasi",
        field_kind=FieldKind.SIGNATURE,
        box=BoundingBox(
            page_number=page_number,
            left=anchor.x1 + 6.0,
            top=anchor.y0 - 2.0,
            right=min(page.rect.width - 72.0, anchor.x1 + 260.0),
            bottom=anchor.y1 + 10.0,
        ),
        confidence=0.78,
        page_hint_text="Öğrencinin İmzası",
    )


def _extract_underline_candidates(page: fitz.Page, page_number: int) -> List[BoundingBox]:
    candidates: List[BoundingBox] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is None:
            continue
        x0, y0, x1, y1 = [float(value) for value in rect]
        width = abs(x1 - x0)
        height = abs(y1 - y0)
        if width >= 70.0 and height <= 3.5:
            candidates.append(
                BoundingBox(
                    page_number=page_number,
                    left=x0,
                    top=max(0.0, y0 - 18.0),
                    right=x1,
                    bottom=y0 + 6.0,
                )
            )
    return sorted(candidates, key=lambda item: (item.top, item.left))


def _find_anchor(page: fitz.Page, terms: Iterable[str]) -> fitz.Rect | None:
    best = None
    for term in terms:
        results = page.search_for(term, quads=False)
        if results:
            rect = results[0]
            if best is None or (rect.y0, rect.x0) < (best.y0, best.x0):
                best = rect
    if best is not None:
        return best
    return _find_anchor_by_words(page, terms)


def _find_anchor_in_region(
    page: fitz.Page,
    terms: Iterable[str],
    *,
    min_y: float = 0.0,
    max_y: float | None = None,
) -> fitz.Rect | None:
    matches: list[fitz.Rect] = []
    for term in terms:
        for rect in page.search_for(term, quads=False):
            if rect.y0 < min_y:
                continue
            if max_y is not None and rect.y0 > max_y:
                continue
            matches.append(rect)
    if matches:
        matches.sort(key=lambda rect: (rect.y0, rect.x0))
        return matches[0]
    anchor = _find_anchor_by_words(page, terms)
    if anchor is None:
        return None
    if anchor.y0 < min_y:
        return None
    if max_y is not None and anchor.y0 > max_y:
        return None
    return anchor


def _find_anchor_by_words(page: fitz.Page, terms: Iterable[str]) -> fitz.Rect | None:
    words = page.get_text("words") or []
    if not words:
        return None
    best_rect = None
    best_score = 0.0
    normalized_terms = [normalize_text(term) for term in terms if normalize_text(term)]
    for normalized_term in normalized_terms:
        target_tokens = normalized_term.split()
        if not target_tokens:
            continue
        span = len(target_tokens)
        for index in range(0, len(words) - span + 1):
            chunk = words[index : index + span]
            phrase = " ".join(str(item[4]) for item in chunk)
            score = text_similarity(phrase, normalized_term)
            if score < 0.72:
                continue
            if best_rect is None or score > best_score:
                rect = fitz.Rect(chunk[0][0], chunk[0][1], chunk[-1][2], max(item[3] for item in chunk))
                best_rect = rect
                best_score = score
    return best_rect


def _choose_candidate(
    page: fitz.Page,
    spec: _AnchorFieldSpec,
    anchor: fitz.Rect,
    candidates: Sequence[BoundingBox],
) -> BoundingBox | None:
    matches = []
    for candidate in candidates:
        if candidate.width < spec.min_width:
            continue
        if spec.strategy == "underline_right":
            vertical_ok = candidate.bottom >= anchor.y0 - 8.0 and candidate.top <= anchor.y1 + 18.0
            horizontal_ok = candidate.left >= anchor.x1 - 10.0
        elif spec.strategy == "underline_below":
            vertical_ok = candidate.top >= anchor.y1 - 6.0 and candidate.top <= anchor.y1 + 38.0
            horizontal_ok = candidate.right >= anchor.x0 + 40.0
        elif spec.strategy == "underline_above":
            vertical_ok = candidate.bottom >= anchor.y0 - 28.0 and candidate.top <= anchor.y1 + 10.0
            horizontal_ok = candidate.left >= anchor.x0 - 10.0
        else:
            vertical_ok = True
            horizontal_ok = True
        if vertical_ok and horizontal_ok:
            matches.append(candidate)
    if matches:
        matches.sort(key=lambda item: (abs(item.top - anchor.y1), abs(item.left - anchor.x1)))
        best = matches[0]
        height = spec.height
        top = max(0.0, best.top + 1.0)
        return BoundingBox(
            page_number=best.page_number,
            left=best.left,
            top=top,
            right=best.right,
            bottom=min(page.rect.height - 1.0, top + height),
        )
    return _fixed_candidate_from_anchor(page, spec, anchor)


def _fixed_candidate_from_anchor(
    page: fitz.Page,
    spec: _AnchorFieldSpec,
    anchor: fitz.Rect,
) -> BoundingBox | None:
    height = spec.height
    if spec.strategy == "underline_below":
        left = anchor.x0
        top = anchor.y1 + 8.0
    elif spec.strategy == "underline_above":
        left = anchor.x1 + 8.0
        top = anchor.y0 - 4.0
    else:
        left = anchor.x1 + 10.0
        top = anchor.y0 - 2.0
    right = min(page.rect.width - 24.0, left + spec.min_width)
    bottom = min(page.rect.height - 24.0, top + height)
    if right - left < 40.0:
        return None
    return BoundingBox(
        page_number=page.number + 1,
        left=left,
        top=max(0.0, top),
        right=right,
        bottom=bottom,
    )


def _append_unique(fields: List[DetectedField], emitted: set[tuple], field: DetectedField) -> None:
    key = (
        field.label,
        field.field_kind.value,
        round(field.box.left),
        round(field.box.top),
        round(field.box.right),
        round(field.box.bottom),
    )
    if key in emitted:
        return
    emitted.add(key)
    fields.append(field)
