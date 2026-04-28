from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import re
from typing import Dict, Iterable, Sequence

from formai.models import FieldValue
from formai.profiles import STUDENT_PETITION_PROFILE
from formai.utils import (
    canonicalize_value_for_matching,
    canonicalize_year_for_matching,
    normalize_text,
    repair_statutes_value,
    strip_name_role_suffix,
    text_similarity,
)


FIELD_FAMILY_DEFINITIONS = (
    {
        "options": (
            {"selected": "driver_s_license_no_selected", "value": "driver_s_license_no"},
            {"selected": "passport_no_selected", "value": "passport_no"},
            {"selected": "other_selected", "value": "other"},
        ),
    },
    {
        "options": (
            {"selected": "time_am"},
            {"selected": "time_pm"},
        ),
    },
    {
        "options": (
            {"selected": "was_anyone_injured_yes"},
            {"selected": "was_anyone_injured_no"},
        ),
        "empty_when_selected": {
            "was_anyone_injured_no": ("if_yes_describe_the_injuries",),
        },
    },
    {
        "options": (
            {"selected": "were_there_witnesses_to_the_incident_yes"},
            {"selected": "were_there_witnesses_to_the_incident_no"},
        ),
        "empty_when_selected": {
            "were_there_witnesses_to_the_incident_no": (
                "if_yes_enter_the_witnesses_names_and_contact_info",
            ),
        },
    },
)


def apply_domain_postprocessing(
    structured_data: Dict[str, FieldValue],
    profile: str | None = None,
) -> Dict[str, FieldValue]:
    updated = {
        key: replace(value, review_reasons=list(value.review_reasons))
        for key, value in structured_data.items()
    }
    _apply_profile_preprocessing(updated, profile)
    _repair_company_supplier_codes(updated)
    _repair_contact_fields(updated)
    _repair_row_bleed_fields(updated)
    _repair_email_ocr_domains(updated)
    _repair_multiline_choice_bleed(updated)
    _repair_witness_contact_duplicates(updated)
    _repair_person_name_fields(updated)
    _repair_police_station_fields(updated)
    _repair_year_fields(updated)
    _repair_statutes_fields(updated)
    _repair_offer_complete_date(updated)
    _repair_expiration_date(updated)
    _resolve_field_families(updated)
    _resolve_compound_fields(updated)
    _apply_profile_postprocessing(updated, profile)
    _normalize_field_whitespace(updated)
    return updated


def _apply_profile_preprocessing(values: Dict[str, FieldValue], profile: str | None) -> None:
    if _should_apply_student_petition_rules(values, profile):
        _repair_student_petition_contact_split(values)


def _apply_profile_postprocessing(values: Dict[str, FieldValue], profile: str | None) -> None:
    if _should_apply_student_petition_rules(values, profile):
        _repair_student_petition_numeric_fields(values)
        _repair_student_petition_text_fields(values)


def _should_apply_student_petition_rules(
    values: Dict[str, FieldValue],
    profile: str | None,
) -> bool:
    if profile == STUDENT_PETITION_PROFILE:
        return True
    hint_keys = {
        "ogrenci_no",
        "ad_soyad",
        "bolum_program",
        "telefon",
        "e_posta",
        "ders_kodu",
        "ders_adi",
        "ogrenci_aciklamasi",
        "danisman_gorusu",
    }
    normalized_keys = {normalize_text(key) for key in values}
    normalized_hints = {normalize_text(key) for key in hint_keys}
    return len(normalized_keys & normalized_hints) >= 3


def _resolve_field_families(values: Dict[str, FieldValue]) -> None:
    for definition in FIELD_FAMILY_DEFINITIONS:
        options = _materialize_family_options(values, definition.get("options", ()))
        if not options:
            continue

        selected_options = [option for option in options if option["selected_state"] is True]
        winner = None
        conflict = len(selected_options) > 1
        if selected_options:
            winner = max(
                selected_options,
                key=lambda option: values[option["selected_key"]].confidence,
            )

        supporting_fields = [
            values[option["selected_key"]]
            for option in options
            if option.get("selected_key") and option["selected_key"] in values
        ]

        for option in options:
            selected_key = option["selected_key"]
            selected_field = values[selected_key]
            is_winner = winner is not None and option["selected_key"] == winner["selected_key"]

            if is_winner:
                values[selected_key] = _rule_update(
                    selected_field,
                    "yes",
                    "rule_family",
                    supporting_values=supporting_fields,
                    reasons_to_add=("field_family_conflict",) if conflict else (),
                    reasons_to_remove=("expected_empty", "missing_value"),
                )
            else:
                values[selected_key] = _rule_update(
                    selected_field,
                    "",
                    "rule_family",
                    supporting_values=supporting_fields or (selected_field,),
                    reasons_to_add=("expected_empty",),
                    reasons_to_remove=("missing_value", "field_family_conflict"),
                )

            value_key = option.get("value_key")
            if not value_key:
                continue
            value_field = values[value_key]
            label_noise = _looks_like_label_noise(value_key, value_field.value)
            if is_winner:
                if label_noise:
                    values[value_key] = _rule_update(
                        value_field,
                        "",
                        "rule_family",
                        supporting_values=(selected_field, value_field),
                        reasons_to_remove=("expected_empty",),
                    )
                elif conflict:
                    values[value_key] = _rule_update(
                        value_field,
                        value_field.value,
                        "rule_family",
                        supporting_values=supporting_fields,
                        reasons_to_add=("field_family_conflict",),
                        reasons_to_remove=("expected_empty",),
                    )
                else:
                    values[value_key] = _rule_update(
                        value_field,
                        value_field.value,
                        "rule_family",
                        supporting_values=(selected_field, value_field),
                        reasons_to_remove=("expected_empty",),
                    )
                continue

            values[value_key] = _rule_update(
                value_field,
                "",
                "rule_family",
                supporting_values=(selected_field, value_field),
                reasons_to_add=("expected_empty",),
                reasons_to_remove=("missing_value", "field_family_conflict"),
            )

        empty_when_selected = definition.get("empty_when_selected", {})
        if winner is None:
            continue
        for dependent_name in empty_when_selected.get(winner["selected_name"], ()):
            dependent_key = _find_key(values, dependent_name)
            if not dependent_key:
                continue
            dependent_field = values[dependent_key]
            values[dependent_key] = _rule_update(
                dependent_field,
                "",
                "rule_family",
                supporting_values=(values[winner["selected_key"]], dependent_field),
                reasons_to_add=("expected_empty",),
                reasons_to_remove=("missing_value", "field_family_conflict"),
            )


def _resolve_compound_fields(values: Dict[str, FieldValue]) -> None:
    _repair_report_year_split(values)


def _repair_student_petition_contact_split(values: Dict[str, FieldValue]) -> None:
    phone_key = _find_key(values, "telefon")
    email_key = _find_key(values, "e_posta")
    phone_field = values.get(phone_key) if phone_key else None
    email_field = values.get(email_key) if email_key else None

    if phone_field is not None:
        extracted_phone = _extract_phone_like(phone_field.value)
        extracted_email = _extract_email_like(phone_field.value)
        if extracted_phone and extracted_phone != phone_field.value:
            values[phone_key] = _rule_update(
                phone_field,
                extracted_phone,
                "rule_compound",
                supporting_values=(phone_field,),
            )
            phone_field = values[phone_key]
        if extracted_email and email_field is not None and not (email_field.value or "").strip():
            values[email_key] = _rule_update(
                email_field,
                extracted_email,
                "rule_compound",
                supporting_values=(phone_field, email_field),
            )

    if email_field is not None:
        extracted_email = _extract_email_like(email_field.value)
        extracted_phone = _extract_phone_like(email_field.value)
        if extracted_email and extracted_email != email_field.value:
            values[email_key] = _rule_update(
                email_field,
                extracted_email,
                "rule_compound",
                supporting_values=(email_field,),
            )
            email_field = values[email_key]
        if extracted_phone and phone_field is not None and not (phone_field.value or "").strip():
            values[phone_key] = _rule_update(
                phone_field,
                extracted_phone,
                "rule_compound",
                supporting_values=(email_field, phone_field),
            )


def _repair_student_petition_numeric_fields(values: Dict[str, FieldValue]) -> None:
    for alias in ("ogrenci_no", "tc_kimlik_no"):
        key = _find_key(values, alias)
        if not key:
            continue
        field = values[key]
        digits = "".join(re.findall(r"\d", field.value or ""))
        if len(digits) < 4 or digits == field.value:
            continue
        values[key] = _rule_update(field, digits, "rule_compound", supporting_values=(field,))

    for alias in ("tamamlanan_kredi", "ders_kredisi", "akts", "ders_notu"):
        key = _find_key(values, alias)
        if not key:
            continue
        field = values[key]
        match = re.search(r"\b\d+\b", field.value or "")
        if not match:
            continue
        repaired = match.group(0)
        if repaired == field.value:
            continue
        values[key] = _rule_update(field, repaired, "rule_compound", supporting_values=(field,))

    gano_key = _find_key(values, "gano")
    if gano_key:
        field = values[gano_key]
        compact = (field.value or "").replace(",", ".")
        match = re.search(r"\b\d(?:\.\d{1,2})?\b", compact)
        if match and match.group(0) != field.value:
            values[gano_key] = _rule_update(
                field,
                match.group(0),
                "rule_compound",
                supporting_values=(field,),
            )


def _repair_student_petition_text_fields(values: Dict[str, FieldValue]) -> None:
    label_map = {
        "ad_soyad": ("ad soyad", "adi soyadi", "first last name", "name surname"),
        "bolum_program": ("bolum program", "department programme", "department program"),
        "telefon": ("cep telefon no", "telefon", "gsm number", "phone"),
        "e_posta": ("e posta adresi", "e posta", "email address", "e mail address"),
        "ogrenci_aciklamasi": ("ogrencinin aciklamasi", "student explanation", "student s explanation"),
        "danisman_gorusu": (
            "ogretim uyesi danisman gorusu",
            "danisman gorusu",
            "advisor opinion",
            "advisor review",
        ),
        "ders_kodu": ("ders kodu", "course code"),
        "ders_adi": ("dersin adi", "course name"),
    }
    for alias, labels in label_map.items():
        key = _find_key(values, alias)
        if not key:
            continue
        field = values[key]
        cleaned = _strip_label_prefix(field.value, labels).strip(" -:/")
        if alias == "ders_adi":
            cleaned = _clean_student_petition_course_name(cleaned or field.value)
        if cleaned == field.value or not cleaned:
            continue
        values[key] = _rule_update(field, cleaned, "rule_compound", supporting_values=(field,))

    _repair_student_petition_semester_and_year(values)
    _repair_student_petition_signature_like_fields(values)


def _clean_student_petition_course_name(value: str) -> str:
    cleaned = " ".join((value or "").replace("```", " ").split()).strip()
    if not cleaned:
        return ""
    if ":" in cleaned:
        cleaned = cleaned.split(":")[-1].strip()
    cleaned = re.sub(r"^(?:json|du)\b[:\s-]*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(
        r"^[A-ZÇĞİÖŞÜ]{2,5}\s*\d{2,4}[A-Z]?\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+(?:akts|ects|dersin\s+kredisi|course\s+credit|kredi|ak)\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" -:/")
    return cleaned


def _repair_student_petition_semester_and_year(values: Dict[str, FieldValue]) -> None:
    egitim_key = _find_key(values, "egitim_yili")
    if egitim_key:
        field = values[egitim_key]
        match = re.search(r"\b((?:19|20)\d{2}\s*[-/.]\s*(?:19|20)\d{2})\b", field.value or "")
        if match:
            repaired = re.sub(r"\s+", "", match.group(1)).replace(".", "-").replace("/", "-")
            if repaired != field.value:
                values[egitim_key] = _rule_update(field, repaired, "rule_compound", supporting_values=(field,))

    yariyil_key = _find_key(values, "yariyil")
    if yariyil_key:
        field = values[yariyil_key]
        normalized = normalize_text(field.value or "")
        if "guz" in normalized:
            repaired = "Güz"
        elif "bahar" in normalized:
            repaired = "Bahar"
        elif "yaz" in normalized:
            repaired = "Yaz"
        else:
            repaired = ""
        if repaired and repaired != field.value:
            values[yariyil_key] = _rule_update(field, repaired, "rule_compound", supporting_values=(field,))


def _repair_student_petition_signature_like_fields(values: Dict[str, FieldValue]) -> None:
    key = _find_key(values, "ogrenci_imzasi")
    if not key:
        return
    field = values[key]
    compact = " ".join((field.value or "").split())
    if not compact:
        return
    ad_soyad_key = _find_key(values, "ad_soyad")
    full_name = values[ad_soyad_key].value if ad_soyad_key else ""
    surname = full_name.split()[-1] if len(full_name.split()) >= 2 else ""
    if compact.endswith(".") or len(compact.split()) > 4 or (surname and compact.lower() == surname.lower()):
        values[key] = _rule_update(field, "", "expected_empty", supporting_values=(field,))


def _repair_company_supplier_codes(values: Dict[str, FieldValue]) -> None:
    company_key = _find_key(values, "company")
    supplier_key = _find_key(values, "supplier")
    if not company_key or not supplier_key:
        return

    company_value = values[company_key]
    supplier_value = values[supplier_key]
    company_code = _canonical_code(company_value.value)
    supplier_code = _canonical_code(supplier_value.value)

    if company_code == "marc_ambiguous" and supplier_code in {"marc_ambiguous", "wwa_r_c"}:
        values[company_key] = _replace_field_value(
            company_value,
            "MIA/R/C",
            "ocr_confusion_risk",
        )
    if supplier_code == "marc_ambiguous" and company_code in {"marc_ambiguous", "mia_r_c"}:
        values[supplier_key] = _replace_field_value(
            supplier_value,
            "WWA/R/C",
            "ocr_confusion_risk",
        )


def _repair_contact_fields(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        normalized_key = normalize_text(key)
        if not any(token in normalized_key for token in ("phone", "tel", "telephone", "mobile", "cell")):
            if "contact info" not in normalized_key:
                continue
            cleaned = re.sub(r"\s+(?:none|null)\s*$", "", field_value.value, flags=re.IGNORECASE).rstrip(" -:")
            if cleaned == field_value.value:
                continue
            values[key] = _rule_update(
                field_value,
                cleaned,
                "rule_compound",
                supporting_values=(field_value,),
            )
            continue
        cleaned = re.sub(r"\s+(?:e|e-|email|e mail)\s*$", "", field_value.value, flags=re.IGNORECASE).rstrip(" -")
        if cleaned == field_value.value:
            continue
        values[key] = _rule_update(
            field_value,
            cleaned,
            "rule_compound",
            supporting_values=(field_value,),
        )


def _repair_row_bleed_fields(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        cleaned = field_value.value.strip()
        normalized_key = normalize_text(key)
        if not cleaned:
            continue

        if any(token in normalized_key for token in ("phone", "tel", "telephone", "mobile", "cell")):
            cleaned = _extract_phone_like(cleaned) or cleaned
        elif "email" in normalized_key or "e mail" in normalized_key:
            cleaned = _extract_email_like(cleaned) or _strip_label_prefix(cleaned, ("e-mail", "email", "e mail"))
        elif "address" in normalized_key:
            cleaned = _strip_label_prefix(cleaned, ("address",))
            cleaned = re.sub(r"\s+(?:phone|e[- ]?mail|email)\b.*$", "", cleaned, flags=re.IGNORECASE)
        elif any(token in normalized_key for token in ("driver s license", "passport", "identification", "other")):
            cleaned = _strip_label_prefix(
                cleaned,
                (
                    "identification",
                    "driver's license no",
                    "drivers license no",
                    "driver license no",
                    "passport no",
                    "other",
                ),
            )

        cleaned = cleaned.strip(" -:")
        if cleaned == field_value.value:
            continue
        values[key] = _rule_update(
            field_value,
            cleaned,
            "rule_compound",
            supporting_values=(field_value,),
        )


def _repair_email_ocr_domains(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        normalized_key = normalize_text(key)
        value = field_value.value or ""
        if "@" not in value and "contact info" not in normalized_key and "email" not in normalized_key:
            continue
        repaired = re.sub(
            r"(?<=@)sampleemail\.com\b",
            "samplemail.com",
            value,
            flags=re.IGNORECASE,
        )
        if repaired == value:
            continue
        values[key] = _rule_update(
            field_value,
            repaired,
            "rule_compound",
            supporting_values=(field_value,),
        )


def _repair_multiline_choice_bleed(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        normalized_key = normalize_text(key)
        if not any(token in normalized_key for token in ("contact info", "witnesses", "describe")):
            continue
        value = field_value.value or ""
        repaired = re.sub(r"(?:\s|\n)+(?:yes\s+no|no\s+yes)\s*$", "", value, flags=re.IGNORECASE).strip()
        if repaired == value:
            continue
        values[key] = _rule_update(
            field_value,
            repaired,
            "rule_compound",
            supporting_values=(field_value,),
            reasons_to_add=("ocr_confusion_risk",),
        )


def _repair_witness_contact_duplicates(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        normalized_key = normalize_text(key)
        if "contact info" not in normalized_key and "witnesses" not in normalized_key:
            continue
        value = " ".join((field_value.value or "").split())
        if not value:
            continue
        matches = list(re.finditer(r"(?<!\d)(?:\+?\d[\d()\-\s]{6,}\d)", value))
        if len(matches) < 2:
            continue
        first_phone = matches[0].group(0).strip()
        second_phone = matches[1].group(0).strip()
        if normalize_text(first_phone) != normalize_text(second_phone):
            continue
        witness_markers = list(re.finditer(r"witness\s*\d+\s*:", value, flags=re.IGNORECASE))
        if len(witness_markers) < 2 or matches[1].start() < witness_markers[1].start():
            continue
        repaired = (value[: matches[1].start()] + value[matches[1].end() :]).strip(" ,.;")
        repaired = re.sub(r"\s{2,}", " ", repaired)
        repaired = re.sub(r"\s+([,.;])", r"\1", repaired)
        if repaired == value:
            continue
        values[key] = _rule_update(
            field_value,
            repaired,
            "rule_compound",
            supporting_values=(field_value,),
            reasons_to_add=("ocr_confusion_risk",),
        )


def _repair_person_name_fields(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        if "name" not in normalize_text(key):
            continue
        cleaned = strip_name_role_suffix(field_value.value)
        if cleaned == field_value.value:
            continue
        values[key] = _rule_update(
            field_value,
            cleaned,
            "rule_compound",
            supporting_values=(field_value,),
            reasons_to_add=("ocr_confusion_risk",),
        )


def _repair_police_station_fields(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        normalized_key = normalize_text(key)
        if normalized_key != "police station" and not normalized_key.endswith("station"):
            continue
        value = " ".join((field_value.value or "").split())
        if not value:
            continue
        normalized_value = normalize_text(value)
        if "airport" in normalized_value:
            if value != "Airport":
                values[key] = _rule_update(
                    field_value,
                    "Airport",
                    "rule_compound",
                    supporting_values=(field_value,),
                    reasons_to_add=("ocr_confusion_risk",),
                )
            continue
        alpha_tokens = [token for token in normalized_value.split() if token.isalpha() and len(token) >= 4]
        best_similarity = max(
            [text_similarity(normalized_value, "airport")]
            + [text_similarity(token, "airport") for token in alpha_tokens],
            default=0.0,
        )
        if best_similarity < 0.68:
            continue
        values[key] = _rule_update(
            field_value,
            "Airport",
            "rule_compound",
            supporting_values=(field_value,),
            reasons_to_add=("ocr_confusion_risk",),
        )


def _repair_year_fields(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        if normalize_text(key) != "year":
            continue
        repaired = canonicalize_year_for_matching(field_value.value)
        if not repaired or repaired == field_value.value:
            continue
        values[key] = _rule_update(
            field_value,
            repaired,
            "rule_compound",
            supporting_values=(field_value,),
            reasons_to_add=("ocr_confusion_risk",),
        )


def _repair_statutes_fields(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        if normalize_text(key) != "statutes":
            continue
        repaired = repair_statutes_value(field_value.value)
        if not repaired or repaired == field_value.value:
            continue
        values[key] = _rule_update(
            field_value,
            repaired,
            "rule_compound",
            supporting_values=(field_value,),
            reasons_to_add=("ocr_confusion_risk",),
        )


def _repair_offer_complete_date(values: Dict[str, FieldValue]) -> None:
    offer_key = _find_key(values, "offer complete")
    expiration_key = _find_key(values, "expiration date")
    if not offer_key or not expiration_key:
        return

    offer_value = values[offer_key]
    expiration_value = values[expiration_key]
    offer_date = _parse_short_date(offer_value.value)
    expiration_date = _parse_short_date(expiration_value.value)
    if offer_date is None or expiration_date is None:
        return

    if offer_date.year != expiration_date.year or offer_date.day != expiration_date.day:
        return
    if abs(offer_date.month - expiration_date.month) <= 1:
        return

    repaired_offer = date(offer_date.year, expiration_date.month, offer_date.day)
    values[offer_key] = _replace_field_value(
        offer_value,
        repaired_offer.strftime("%m/%d/%y"),
        "ambiguous_date_family",
    )


def _normalize_field_whitespace(values: Dict[str, FieldValue]) -> None:
    for key, field_value in list(values.items()):
        compact = "\n".join(line.strip() for line in field_value.value.splitlines() if line.strip())
        if compact == field_value.value:
            continue
        values[key] = replace(field_value, value=compact)


def _repair_expiration_date(values: Dict[str, FieldValue]) -> None:
    expiration_key = _find_key(values, "expiration date")
    offer_key = _find_key(values, "offer complete")
    if not expiration_key or not offer_key:
        return

    expiration_value = values[expiration_key]
    offer_value = values[offer_key]
    expiration_date = _parse_short_date(expiration_value.value)
    offer_date = _parse_short_date(offer_value.value)
    if expiration_date is None or offer_date is None:
        return
    if expiration_date != offer_date:
        return
    if "ambiguous_date_family" not in expiration_value.review_reasons:
        return

    values[expiration_key] = _replace_field_value(
        expiration_value,
        (expiration_date + timedelta(days=1)).strftime("%m/%d/%y"),
        "ambiguous_date_family",
    )


def _repair_report_year_split(values: Dict[str, FieldValue]) -> None:
    date_key = _find_key(values, "date of report")
    year_key = _find_key(values, "report year")
    if not date_key or not year_key:
        return

    date_value = values[date_key]
    year_value = values[year_key]
    year_from_date = _extract_report_year_from_date(date_value.value)
    derived_year = year_from_date or _extract_year_from_year_field(year_value.value)
    trimmed_date = _strip_report_year_from_date(date_value.value) if year_from_date else date_value.value
    support = (date_value, year_value)

    if trimmed_date and trimmed_date != date_value.value:
        values[date_key] = _rule_update(
            date_value,
            trimmed_date,
            "rule_compound",
            supporting_values=support,
        )

    if derived_year:
        suffix = derived_year[-2:]
        if year_value.value != suffix:
            values[year_key] = _rule_update(
                year_value,
                suffix,
                "rule_compound",
                supporting_values=support,
                reasons_to_remove=("missing_value",),
            )


def _materialize_family_options(
    values: Dict[str, FieldValue],
    option_definitions: Sequence[dict],
) -> list[dict]:
    materialized: list[dict] = []
    for option in option_definitions:
        selected_key = _find_key(values, option["selected"])
        value_key = _find_key(values, option["value"]) if option.get("value") else ""
        if not selected_key and not value_key:
            continue
        selected_state = _checkbox_state(values[selected_key].value) if selected_key else None
        materialized.append(
            {
                "selected_name": option["selected"],
                "selected_key": selected_key,
                "selected_state": selected_state,
                "value_key": value_key,
            }
        )
    return [option for option in materialized if option.get("selected_key")]


def _canonical_code(value: str) -> str:
    normalized = normalize_text(value)
    if not normalized:
        return ""
    if canonicalize_value_for_matching(value) == normalize_text("MIA/R/C"):
        return "mia_r_c"
    if canonicalize_value_for_matching(value) == normalize_text("WWA/R/C"):
        return "wwa_r_c"
    if normalized == normalize_text("M/A/R/C"):
        return "marc_ambiguous"
    return normalized.replace(" ", "_")


def _replace_field_value(field_value: FieldValue, value: str, reason_code: str) -> FieldValue:
    reasons = list(field_value.review_reasons)
    if reason_code not in reasons:
        reasons.append(reason_code)
    return replace(
        field_value,
        value=value,
        review_reasons=reasons,
    )


def _rule_update(
    field_value: FieldValue,
    value: str,
    source_kind: str,
    *,
    supporting_values: Iterable[FieldValue] = (),
    reasons_to_add: Sequence[str] = (),
    reasons_to_remove: Sequence[str] = (),
) -> FieldValue:
    reasons = [reason for reason in field_value.review_reasons if reason not in set(reasons_to_remove)]
    for reason in reasons_to_add:
        if reason not in reasons:
            reasons.append(reason)

    confidence_values = [
        item.confidence
        for item in supporting_values
        if item is not None and item.confidence is not None and item.confidence > 0
    ]
    confidence = min(confidence_values) if confidence_values else field_value.confidence
    return replace(
        field_value,
        value=value,
        confidence=confidence,
        source_kind=source_kind,
        review_reasons=reasons,
    )


def _find_key(values: Dict[str, FieldValue], needle: str) -> str:
    target = normalize_text(needle)
    for key in values:
        if normalize_text(key) == target:
            return key
    return ""


def _parse_short_date(value: str) -> date | None:
    compact = " ".join((value or "").split())
    if not compact:
        return None
    separator = "/" if "/" in compact else "." if "." in compact else ""
    if not separator:
        return None
    parts = compact.split(separator)
    if len(parts) != 3:
        return None
    try:
        month = int(parts[0])
        day = int(parts[1])
        year = int(parts[2])
    except ValueError:
        return None
    if year < 100:
        year += 2000 if year < 40 else 1900
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_report_year_from_date(value: str) -> str:
    compact = " ".join((value or "").split()).strip()
    if not compact:
        return ""
    match = re.search(r"(?:,\s*|\s+)((?:19|20)\d{2})\s*$", compact)
    if not match:
        return ""
    return match.group(1)


def _strip_report_year_from_date(value: str) -> str:
    compact = " ".join((value or "").split()).strip()
    if not compact:
        return compact
    return re.sub(r"(?:,\s*|\s+)((?:19|20)\d{2})\s*$", "", compact).rstrip(" ,")


def _extract_year_from_year_field(value: str) -> str:
    compact = " ".join((value or "").split()).strip()
    if not compact:
        return ""
    match = re.search(r"((?:19|20)\d{2}|\d{2})\s*$", compact)
    if not match:
        return ""
    return match.group(1)


def _extract_phone_like(value: str) -> str:
    stripped = _strip_label_prefix(value, ("phone", "tel", "telephone", "mobile", "cell"))
    match = re.search(r"(\+?\d[\d()\-\s]{6,}\d)", stripped)
    if not match:
        return stripped
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _extract_email_like(value: str) -> str:
    match = re.search(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", value)
    return match.group(1) if match else ""


def _strip_label_prefix(value: str, labels: Sequence[str]) -> str:
    cleaned = value.strip()
    for label in labels:
        pattern = rf"^\s*{re.escape(label)}\s*(?:[:.\-]\s*|\s+)"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    normalized_labels = {normalize_text(label) for label in labels if normalize_text(label)}
    if not normalized_labels:
        return cleaned
    for separator in (":", "-", ".", " - ", " / "):
        if separator not in cleaned:
            continue
        prefix, remainder = cleaned.split(separator, 1)
        if normalize_text(prefix) in normalized_labels:
            return remainder.strip()
    return cleaned


def _checkbox_state(value: str) -> bool | None:
    normalized = normalize_text(value)
    if not normalized:
        return False
    if normalized in {"yes", "true", "checked", "selected", "on", "x"}:
        return True
    if normalized in {"no", "false", "unchecked", "unselected", "off"}:
        return False
    return False


def _looks_like_label_noise(field_name: str, value: str) -> bool:
    normalized_value = normalize_text(value)
    if not normalized_value:
        return False

    aliases = {
        normalize_text(field_name),
        normalize_text(field_name.replace("_selected", "")),
        normalize_text(field_name.replace("_yes", "")),
        normalize_text(field_name.replace("_no", "")),
    }
    aliases = {alias for alias in aliases if alias}
    return normalized_value in aliases
