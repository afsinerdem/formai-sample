from __future__ import annotations

from collections import Counter
from pathlib import Path

import fitz

from formai.models import (
    DocumentFamily,
    DocumentIdentity,
    DocumentKind,
    DocumentLanguage,
    DomainHint,
    LayoutStyle,
    ScriptStyle,
)
from formai.utils import normalize_text


TURKISH_KEYWORDS = {
    "ogrenci",
    "dilekce",
    "basvuru",
    "ad",
    "soyad",
    "adres",
    "tarih",
    "danisman",
    "fakulte",
    "bolum",
    "program",
    "gano",
    "kredi",
    "e posta",
    "eposta",
}
ENGLISH_KEYWORDS = {
    "student",
    "request",
    "application",
    "address",
    "date",
    "advisor",
    "incident",
    "witness",
    "claim",
    "consent",
    "email",
    "phone",
}
STUDENT_PETITION_HINTS = (
    "ogrenci",
    "student",
    "dilekce",
    "petition",
    "tek ders",
    "tek ders basvuru formu",
    "tek ders sinavina girecegi ders bilgileri",
    "ogrenci dilekce formu",
    "student number",
    "ogrenci no",
    "adi ve soyadi",
    "tel no e posta",
    "ad soyad",
    "ders kodu",
    "dersin adi",
    "department programme",
    "bolum program",
    "danisman",
    "gano",
)
INSURANCE_HINTS = (
    "incident",
    "witness",
    "injured",
    "driver",
    "passport",
    "date of report",
    "describe the incident",
)
HR_HINTS = (
    "employee",
    "department",
    "manager",
    "start date",
    "leave of absence",
)


def infer_document_identity(pdf_path: Path, document_kind: DocumentKind) -> DocumentIdentity:
    text, signal_counts = _extract_pdf_text_signals(pdf_path)
    language = _infer_language(text, signal_counts)
    layout_style = _infer_layout_style(pdf_path)
    script_style = _infer_script_style(document_kind, text)
    document_family = _infer_document_family(text)
    domain_hint = _infer_domain_hint(document_family, text)
    profile = _select_profile(language, script_style, document_family)
    confidence = _identity_confidence(
        language=language,
        layout_style=layout_style,
        document_family=document_family,
    )
    return DocumentIdentity(
        document_kind=document_kind,
        language=language,
        script_style=script_style,
        layout_style=layout_style,
        document_family=document_family,
        domain_hint=domain_hint,
        profile=profile,
        confidence=confidence,
        signals={key: str(value) for key, value in signal_counts.items()},
    )


def _extract_pdf_text_signals(pdf_path: Path) -> tuple[str, Counter]:
    document = fitz.open(str(pdf_path))
    chunks: list[str] = []
    counter: Counter = Counter()
    try:
        for page in document:
            text = page.get_text("text") or ""
            normalized = normalize_text(text)
            if normalized:
                chunks.append(normalized)
                counter["turkish_keywords"] += sum(1 for token in TURKISH_KEYWORDS if token in normalized)
                counter["english_keywords"] += sum(1 for token in ENGLISH_KEYWORDS if token in normalized)
                counter["student_petition_hints"] += sum(
                    1 for token in STUDENT_PETITION_HINTS if token in normalized
                )
                counter["insurance_hints"] += sum(1 for token in INSURANCE_HINTS if token in normalized)
                counter["hr_hints"] += sum(1 for token in HR_HINTS if token in normalized)
                counter["turkish_chars"] += sum(1 for char in text if char in "çğıöşüÇĞİÖŞÜ")
    finally:
        document.close()
    return "\n".join(chunks), counter


def _infer_language(text: str, counter: Counter) -> DocumentLanguage:
    turkish_score = counter.get("turkish_keywords", 0) + min(counter.get("turkish_chars", 0), 8)
    english_score = counter.get("english_keywords", 0)
    if turkish_score >= 4 and english_score >= 4:
        return DocumentLanguage.MIXED
    if turkish_score > english_score and turkish_score >= 2:
        return DocumentLanguage.TR
    if english_score > turkish_score and english_score >= 2:
        return DocumentLanguage.EN
    if text:
        return DocumentLanguage.MIXED if "/" in text and turkish_score and english_score else DocumentLanguage.UNKNOWN
    return DocumentLanguage.UNKNOWN


def _infer_script_style(document_kind: DocumentKind, text: str) -> ScriptStyle:
    if document_kind == DocumentKind.ACROFORM:
        return ScriptStyle.PRINTED
    if text:
        return ScriptStyle.PRINTED
    return ScriptStyle.UNKNOWN


def _infer_layout_style(pdf_path: Path) -> LayoutStyle:
    document = fitz.open(str(pdf_path))
    underline_count = 0
    rect_count = 0
    try:
        for page in document:
            for drawing in page.get_drawings():
                rect = drawing.get("rect")
                if rect is None:
                    continue
                x0, y0, x1, y1 = [float(value) for value in rect]
                width = abs(x1 - x0)
                height = abs(y1 - y0)
                if width >= 50 and height <= 3.5:
                    underline_count += 1
                elif width >= 40 and height >= 12:
                    rect_count += 1
    finally:
        document.close()
    if underline_count >= 6 and rect_count >= 4:
        return LayoutStyle.MIXED
    if underline_count >= 6:
        return LayoutStyle.UNDERLINE_FORM
    if rect_count >= 6:
        return LayoutStyle.BOXED_FORM
    if rect_count >= 2:
        return LayoutStyle.TABLE_FORM
    return LayoutStyle.UNKNOWN


def _infer_document_family(text: str) -> DocumentFamily:
    if not text:
        return DocumentFamily.UNKNOWN
    if sum(1 for token in STUDENT_PETITION_HINTS if token in text) >= 3:
        return DocumentFamily.STUDENT_PETITION
    if sum(1 for token in INSURANCE_HINTS if token in text) >= 3:
        return DocumentFamily.INSURANCE_INCIDENT
    if "consent" in text or "acik riza" in text or "onay formu" in text:
        return DocumentFamily.CONSENT_FORM
    if "claim" in text or "basvuru" in text or "application" in text:
        return DocumentFamily.APPLICATION_FORM
    return DocumentFamily.GENERIC_FORM if text else DocumentFamily.UNKNOWN


def _infer_domain_hint(document_family: DocumentFamily, text: str) -> DomainHint:
    if document_family == DocumentFamily.STUDENT_PETITION or any(
        token in text for token in ("universite", "faculty", "fakulte", "student affairs")
    ):
        return DomainHint.EDUCATION
    if document_family == DocumentFamily.INSURANCE_INCIDENT:
        return DomainHint.INSURANCE
    if document_family == DocumentFamily.CONSENT_FORM or "employee" in text:
        return DomainHint.HR
    if document_family == DocumentFamily.APPLICATION_FORM:
        return DomainHint.OPERATIONS
    return DomainHint.UNKNOWN


def _select_profile(
    language: DocumentLanguage,
    script_style: ScriptStyle,
    document_family: DocumentFamily,
) -> str:
    if document_family == DocumentFamily.STUDENT_PETITION and language in {
        DocumentLanguage.TR,
        DocumentLanguage.MIXED,
    }:
        return "student_petition_tr"
    if document_family == DocumentFamily.INSURANCE_INCIDENT and language in {
        DocumentLanguage.EN,
        DocumentLanguage.MIXED,
    }:
        return "insurance_incident_en"
    if script_style == ScriptStyle.HANDWRITTEN:
        return "generic_handwritten_form"
    return "generic_printed_form"


def _identity_confidence(
    *,
    language: DocumentLanguage,
    layout_style: LayoutStyle,
    document_family: DocumentFamily,
) -> float:
    score = 0.25
    if language != DocumentLanguage.UNKNOWN:
        score += 0.2
    if layout_style != LayoutStyle.UNKNOWN:
        score += 0.2
    if document_family not in {DocumentFamily.UNKNOWN, DocumentFamily.GENERIC_FORM}:
        score += 0.35
    elif document_family == DocumentFamily.GENERIC_FORM:
        score += 0.15
    return min(score, 0.95)
