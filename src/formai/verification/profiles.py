from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from formai.models import AcroField
from formai.profiles import (
    GENERIC_HANDWRITTEN_PROFILE,
    GENERIC_PRINTED_PROFILE,
    INSURANCE_INCIDENT_PROFILE,
    STUDENT_PETITION_PROFILE,
    infer_profile_from_target_fields,
)


@dataclass(frozen=True)
class VerificationProfile:
    name: str
    ocr_lang: str
    critical_fields: frozenset[str]
    multiline_fields: frozenset[str]
    numeric_fields: frozenset[str]
    date_fields: frozenset[str]
    llm_prompt_hint: str


_PROFILE_REGISTRY: dict[str, VerificationProfile] = {
    GENERIC_PRINTED_PROFILE: VerificationProfile(
        name=GENERIC_PRINTED_PROFILE,
        ocr_lang="eng",
        critical_fields=frozenset(),
        multiline_fields=frozenset(),
        numeric_fields=frozenset(),
        date_fields=frozenset(),
        llm_prompt_hint="Printed form verification with mixed short fields and labels.",
    ),
    GENERIC_HANDWRITTEN_PROFILE: VerificationProfile(
        name=GENERIC_HANDWRITTEN_PROFILE,
        ocr_lang="eng",
        critical_fields=frozenset(),
        multiline_fields=frozenset(),
        numeric_fields=frozenset(),
        date_fields=frozenset(),
        llm_prompt_hint="Handwritten form verification with noisy OCR evidence.",
    ),
    STUDENT_PETITION_PROFILE: VerificationProfile(
        name=STUDENT_PETITION_PROFILE,
        ocr_lang="tur+eng",
        critical_fields=frozenset(
            {
                "ogrenci_no",
                "ad_soyad",
                "telefon",
                "e_posta",
                "ders_kodu",
                "ders_adi",
                "gano",
                "ogrenci_aciklamasi",
                "danisman_gorusu",
            }
        ),
        multiline_fields=frozenset({"adres", "ogrenci_aciklamasi", "danisman_gorusu"}),
        numeric_fields=frozenset(
            {
                "ogrenci_no",
                "tc_kimlik_no",
                "gano",
                "tamamlanan_kredi",
                "ders_kredisi",
                "akts",
                "donem_sayisi",
            }
        ),
        date_fields=frozenset({"tarih", "danisman_tarih_imza", "mali_onay_tarih_imza"}),
        llm_prompt_hint="Turkish university petition verification with table rows, dates, and multiline notes.",
    ),
    INSURANCE_INCIDENT_PROFILE: VerificationProfile(
        name=INSURANCE_INCIDENT_PROFILE,
        ocr_lang="eng",
        critical_fields=frozenset(
            {
                "date_of_report",
                "policy_number",
                "insured_name",
                "describe_the_incident",
                "police_station",
            }
        ),
        multiline_fields=frozenset(
            {
                "describe_the_incident",
                "describe_the_injuries",
                "if_yes_enter_the_witnesses_names_and_contact_info",
            }
        ),
        numeric_fields=frozenset({"report_year", "driver_s_license_number", "phone"}),
        date_fields=frozenset({"date_of_report", "incident_date"}),
        llm_prompt_hint="Insurance incident verification with witness/contact multiline fields.",
    ),
}


def resolve_verification_profile(
    *,
    profile_name: str | None,
    template_fields: Iterable[AcroField],
    default_lang: str = "eng",
) -> VerificationProfile:
    resolved_name = (profile_name or "").strip() or infer_profile_from_target_fields(list(template_fields))
    profile = _PROFILE_REGISTRY.get(resolved_name)
    if profile is not None:
        return profile
    fallback_lang = (default_lang or "eng").strip() or "eng"
    return VerificationProfile(
        name=resolved_name or GENERIC_PRINTED_PROFILE,
        ocr_lang=fallback_lang if "eng" in fallback_lang else f"{fallback_lang}+eng",
        critical_fields=frozenset(),
        multiline_fields=frozenset(),
        numeric_fields=frozenset(),
        date_fields=frozenset(),
        llm_prompt_hint="Generic form verification.",
    )
