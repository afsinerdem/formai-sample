from __future__ import annotations

from dataclasses import replace
from typing import Dict, Iterable, Sequence

from formai.models import AcroField, FieldValue
from formai.segmentation import logical_expected_keys, logical_field_name
from formai.utils import normalize_text


STUDENT_PETITION_PROFILE = "student_petition_tr"
INSURANCE_INCIDENT_PROFILE = "insurance_incident_en"
GENERIC_PRINTED_PROFILE = "generic_printed_form"
GENERIC_HANDWRITTEN_PROFILE = "generic_handwritten_form"

_PROFILE_PRIORITY_KEYS: Dict[str, Sequence[str]] = {
    STUDENT_PETITION_PROFILE: (
        "tarih",
        "ogrenci_no",
        "tc_kimlik_no",
        "fakulte_birim",
        "ad_soyad",
        "bolum_program",
        "telefon",
        "gano",
        "e_posta",
        "tamamlanan_kredi",
        "ders_kodu",
        "ders_adi",
        "ders_kredisi",
        "akts",
        "ders_notu",
        "ogrenci_aciklamasi",
        "danisman_gorusu",
        "ogrenci_imzasi",
    ),
}

_PROFILE_ALIASES: Dict[str, Dict[str, str]] = {
    STUDENT_PETITION_PROFILE: {
        "tarih": "tarih",
        "date": "tarih",
        "student number": "ogrenci_no",
        "ogrenci no": "ogrenci_no",
        "ogrenci numarasi": "ogrenci_no",
        "student no": "ogrenci_no",
        "tr identity number": "tc_kimlik_no",
        "identity number": "tc_kimlik_no",
        "tc kimlik no": "tc_kimlik_no",
        "tc no": "tc_kimlik_no",
        "unit": "fakulte_birim",
        "fakulte yuksekokul birim": "fakulte_birim",
        "faculty unit": "fakulte_birim",
        "ad soyad": "ad_soyad",
        "adi soyadi": "ad_soyad",
        "adi ve soyadi": "ad_soyad",
        "first last name": "ad_soyad",
        "name surname": "ad_soyad",
        "department programme": "bolum_program",
        "department program": "bolum_program",
        "bolum program": "bolum_program",
        "programme": "bolum_program",
        "gsm number": "telefon",
        "gsmnumber": "telefon",
        "cep telefon no": "telefon",
        "telefon": "telefon",
        "phone": "telefon",
        "mobile phone": "telefon",
        "gpa": "gano",
        "gano": "gano",
        "e posta adresi": "e_posta",
        "eposta adresi": "e_posta",
        "e posta": "e_posta",
        "email address": "e_posta",
        "e mail address": "e_posta",
        "credits completed": "tamamlanan_kredi",
        "tamamlanan kredi": "tamamlanan_kredi",
        "course code": "ders_kodu",
        "ders kodu": "ders_kodu",
        "course name": "ders_adi",
        "dersin adi": "ders_adi",
        "course credit": "ders_kredisi",
        "dersin kredisi": "ders_kredisi",
        "akts": "akts",
        "ects": "akts",
        "course grade": "ders_notu",
        "ders notu": "ders_notu",
        "student s explanation": "ogrenci_aciklamasi",
        "student explanation": "ogrenci_aciklamasi",
        "ogrencinin aciklamasi": "ogrenci_aciklamasi",
        "advisor opinion": "danisman_gorusu",
        "advisor review": "danisman_gorusu",
        "ogretim uyesi danisman gorusu": "danisman_gorusu",
        "student s signature": "ogrenci_imzasi",
        "ogrencinin imzasi": "ogrenci_imzasi",
    },
}

_STUDENT_PETITION_HINTS = {
    "ogrenci_no",
    "tc_kimlik_no",
    "ad_soyad",
    "bolum_program",
    "telefon",
    "gano",
    "e_posta",
    "tamamlanan_kredi",
    "ogrenci_aciklamasi",
    "danisman_gorusu",
}

_INSURANCE_INCIDENT_HINTS = {
    "date_of_report",
    "describe_the_incident",
    "if_yes_enter_the_witnesses_names_and_contact_info",
    "police_station",
    "complainant_name",
    "statutes",
}


def infer_profile_from_target_fields(target_fields: Sequence[AcroField]) -> str:
    keys = set()
    for field in target_fields:
        for candidate in {
            field.name,
            field.label or "",
            logical_field_name(field.name),
            logical_field_name(field.label or field.name),
        }:
            if not candidate:
                continue
            keys.add(canonicalize_profile_key(candidate, STUDENT_PETITION_PROFILE))
            keys.add(canonicalize_profile_key(candidate, INSURANCE_INCIDENT_PROFILE))
            keys.add(canonicalize_profile_key(candidate, GENERIC_PRINTED_PROFILE))
    if len(keys & _STUDENT_PETITION_HINTS) >= 4:
        return STUDENT_PETITION_PROFILE
    if len(keys & _INSURANCE_INCIDENT_HINTS) >= 3:
        return INSURANCE_INCIDENT_PROFILE
    return GENERIC_PRINTED_PROFILE


def profile_expected_keys(target_fields: Sequence[AcroField], profile: str) -> list[str]:
    existing = logical_expected_keys(target_fields)
    canonical_existing = {
        canonicalize_profile_key(key, profile): key for key in existing
    }
    if profile not in _PROFILE_PRIORITY_KEYS:
        return existing
    ordered: list[str] = []
    for key in _PROFILE_PRIORITY_KEYS[profile]:
        original = canonical_existing.get(key)
        if original:
            ordered.append(original)
    for key in existing:
        if key not in ordered:
            ordered.append(key)
    return ordered


def canonicalize_profile_key(key: str, profile: str | None = None) -> str:
    normalized = normalize_text(key)
    if not normalized:
        return ""
    alias_map = _PROFILE_ALIASES.get(profile or "", {})
    if normalized in alias_map:
        return alias_map[normalized]
    return normalized.replace(" ", "_")


def normalize_structured_data_for_profile(
    structured_data: Dict[str, FieldValue],
    profile: str | None = None,
) -> Dict[str, FieldValue]:
    normalized: Dict[str, FieldValue] = {}
    alias_map = _PROFILE_ALIASES.get(profile or "", {})
    for key, value in structured_data.items():
        normalized_key = normalize_text(key)
        canonical_key = alias_map.get(normalized_key, key)
        candidate = replace(value, source_key=canonical_key)
        existing = normalized.get(canonical_key)
        if existing is None or _prefer_field_value(candidate, existing):
            normalized[canonical_key] = candidate
    return normalized


def _prefer_field_value(candidate: FieldValue, current: FieldValue) -> bool:
    candidate_non_empty = bool((candidate.value or "").strip())
    current_non_empty = bool((current.value or "").strip())
    if candidate_non_empty != current_non_empty:
        return candidate_non_empty
    if abs(candidate.confidence - current.confidence) > 0.05:
        return candidate.confidence > current.confidence
    return len((candidate.value or "").strip()) >= len((current.value or "").strip())
