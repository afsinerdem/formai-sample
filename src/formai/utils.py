from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Sequence, Set


GENERIC_FIELD_NAME_RE = re.compile(
    r"^(field|text|textbox|checkbox|radio|button|choice|signature|untitled|page)[_\-\s]*\d*$",
    re.IGNORECASE,
)
ADDRESS_CONFUSION_MAP = {
    "illiwas": "illinois",
    "peit": "pe17",
}
COMMON_STATUTE_CODES = {
    "34",
    "107",
    "109",
    "114",
    "120b",
    "143",
    "147",
    "148",
    "149",
    "186",
    "279",
    "307",
    "323",
    "325",
    "338",
    "341",
    "354a",
    "376",
    "379",
    "399",
    "402",
    "420",
    "506",
    "509",
    "322",
}
NAME_ROLE_SUFFIX_RE = re.compile(
    r"(?:,\s*|\s+)(?:s\.?\s*i\.?|si|sub[- ]?inspector|inspector|constable|officer|informant|of police|police)\b.*$",
    re.IGNORECASE,
)
SOURCE_CONFIDENCE_BY_KIND = {
    "pdf_direct": 0.99,
    "api_input": 0.90,
    "checkbox_pixel": 0.90,
    "checkbox_blue_search": 0.84,
    "llm_crop_checkbox": 0.76,
    "llm_page": 0.82,
    "llm_retry_contact": 0.74,
    "llm_retry_choice": 0.72,
    "llm_retry_date": 0.70,
    "llm_retry_code": 0.70,
    "llm_retry_empty": 0.66,
    "llm_crop": 0.70,
    "llm_crop_ocr_hint": 0.62,
    "rule_family": 0.84,
    "rule_compound": 0.84,
}
REVIEW_REASON_PENALTIES = {
    "missing_value": 1.00,
    "expected_empty": 0.00,
    "borrowed_neighbor_risk": 0.18,
    "ocr_confusion_risk": 0.08,
    "low_mapping_confidence": 0.20,
    "ambiguous_date_family": 0.12,
    "field_family_conflict": 0.18,
}

TURKISH_ASCII_FOLD_MAP = str.maketrans(
    {
        "ı": "i",
        "İ": "I",
        "ğ": "g",
        "Ğ": "G",
        "ş": "s",
        "Ş": "S",
        "ç": "c",
        "Ç": "C",
        "ö": "o",
        "Ö": "O",
        "ü": "u",
        "Ü": "U",
    }
)


def clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def average_confidence(values: Iterable[float], default: float = 0.0) -> float:
    valid_values = [clamp_confidence(value) for value in values if value is not None]
    if not valid_values:
        return default
    return sum(valid_values) / len(valid_values)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", (value or "").translate(TURKISH_ASCII_FOLD_MAP))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    boundary_spaced = re.sub(r"(?<=[a-zA-Z])(?=\d)|(?<=\d)(?=[a-zA-Z])", " ", ascii_only)
    return re.sub(r"[^a-z0-9]+", " ", boundary_spaced.lower()).strip()


def canonicalize_value_for_matching(value: str, key: str = "") -> str:
    normalized = normalize_text(value)
    key_normalized = normalize_text(key)
    if not normalized:
        return normalized
    if "name" in key_normalized:
        return canonicalize_name_for_matching(value)
    if key_normalized == "year":
        return canonicalize_year_for_matching(value)
    if key_normalized == "statutes":
        return canonicalize_statutes_for_matching(value)
    if "address" in key_normalized:
        tokens = [ADDRESS_CONFUSION_MAP.get(token, token) for token in normalized.split()]
        normalized = " ".join(tokens)
    if "police station" in key_normalized or key_normalized.endswith("station"):
        tokens = []
        for token in normalized.split():
            if token in {"police", "station", "ps", "form", "no", "w", "b", "p", "s", "year", "at"}:
                continue
            if token.isdigit():
                continue
            tokens.append(token)
        deduped = []
        for token in tokens:
            if deduped and deduped[-1] == token:
                continue
            deduped.append(token)
        normalized = " ".join(deduped)
    return normalized


def strip_name_role_suffix(value: str) -> str:
    compact = " ".join((value or "").replace("\n", " ").split())
    if not compact:
        return ""
    return NAME_ROLE_SUFFIX_RE.sub("", compact).strip(" ,.-")


def canonicalize_name_for_matching(value: str) -> str:
    normalized = normalize_text(strip_name_role_suffix(value))
    raw_tokens = normalized.split()
    tokens: list[str] = []
    index = 0
    while index < len(raw_tokens):
        current = raw_tokens[index]
        if index + 1 < len(raw_tokens) and len(current) <= 2 and len(raw_tokens[index + 1]) >= 4:
            tokens.append(current + raw_tokens[index + 1])
            index += 2
            continue
        tokens.append(current)
        index += 1
    if len(tokens) >= 4 and len(tokens) % 2 == 0:
        half = len(tokens) // 2
        if tokens[:half] == tokens[half:]:
            tokens = tokens[:half]
    deduped: list[str] = []
    for token in tokens:
        if deduped and deduped[-1] == token:
            continue
        deduped.append(token)
    return " ".join(deduped)


def canonicalize_year_for_matching(value: str) -> str:
    compact = " ".join((value or "").split()).strip()
    if not compact:
        return ""
    if "/" in compact or "-" in compact or "." in compact:
        tail_two_digit = re.search(r"(?:[./-])(\d{2})\s*$", compact)
        if tail_two_digit:
            suffix = int(tail_two_digit.group(1))
            return f"{2000 + suffix if suffix < 40 else 1900 + suffix}"
    four_digit = re.findall(r"(?:19|20)\d{2}", compact)
    if four_digit:
        return four_digit[-1]
    two_digit = re.findall(r"(?<!\d)(\d{2})(?!\d)", compact)
    if two_digit:
        suffix = int(two_digit[-1])
        return f"{2000 + suffix if suffix < 40 else 1900 + suffix}"
    digits = re.findall(r"\d", compact)
    if len(digits) >= 4:
        candidate = "".join(digits[-4:])
        if candidate.startswith(("19", "20")):
            return candidate
    return normalize_text(compact)


def repair_statutes_value(value: str) -> str:
    compact = " ".join((value or "").replace("\n", " ").split())
    if not compact:
        return ""
    compact = compact.replace("%", "/").replace("|", "/").replace("\\", "/")
    compact = re.sub(r"[\[\](){}]", "", compact)
    compact = re.sub(r"\s*/\s*", "/", compact)
    compact = re.sub(r"(?<=\d)\s+(?=[A-Za-z])", "", compact)
    compact = re.sub(r"(?<=[A-Za-z])\s+(?=\d)", "", compact)

    has_ipc_suffix = bool(re.search(r"\b(?:ipc|aci|acl|act|apc)\b", compact, re.IGNORECASE))
    compact = re.sub(r"\b(?:ipc|aci|acl|act|apc)\b", "", compact, flags=re.IGNORECASE).strip(" /")

    tokens = [token for token in compact.split("/") if token.strip()]
    repaired_tokens = []
    for token in tokens:
        token_compact = re.sub(r"[^A-Za-z0-9]", "", token or "")
        suffix_match = re.search(r"(?i)(ipc|aci|acl|act|apc)$", token_compact)
        if suffix_match:
            has_ipc_suffix = True
            token_compact = token_compact[: -len(suffix_match.group(1))]
        repaired_tokens.append(_repair_single_statute_token(token_compact))
    repaired = "/".join(token for token in repaired_tokens if token)
    if not repaired:
        return ""
    if has_ipc_suffix or any(character.isalpha() for character in repaired):
        return f"{repaired} Ipc".strip()
    return repaired


def canonicalize_statutes_for_matching(value: str) -> str:
    repaired = repair_statutes_value(value)
    repaired = re.sub(r"\bipc\b", "", repaired, flags=re.IGNORECASE).strip(" /")
    return normalize_text(repaired)


def _repair_single_statute_token(token: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", token or "").upper()
    if not compact:
        return ""

    compact = compact.replace("O", "0")
    compact = compact.replace("I", "1") if compact.isdigit() else compact

    if len(compact) == 4 and compact.startswith("1") and compact[1:].lower() in COMMON_STATUTE_CODES:
        compact = compact[1:]
    elif len(compact) == 4 and compact.endswith("006") and "506" in COMMON_STATUTE_CODES:
        compact = "506"
    if len(compact) == 2 and compact.startswith("0") and f"3{compact}".lower() in COMMON_STATUTE_CODES:
        compact = f"3{compact}"
    elif len(compact) == 2 and compact.startswith("0"):
        prefixed = _nearest_statute_code(f"30{compact[1]}")
        if prefixed:
            compact = prefixed.upper()
    if compact.endswith("N") and compact[:-1].isdigit():
        candidate = f"{compact[:-1]}A".lower()
        if candidate in COMMON_STATUTE_CODES:
            compact = candidate.upper()

    lowered = compact.lower()
    if lowered in COMMON_STATUTE_CODES:
        return _format_statute_code(lowered)

    nearest = _nearest_statute_code(lowered)
    if nearest:
        return _format_statute_code(nearest)
    return compact


def _nearest_statute_code(token: str) -> str:
    best_code = ""
    best_prefix_score = -1
    best_score = 0.0
    for code in sorted(COMMON_STATUTE_CODES):
        if abs(len(code) - len(token)) > 1:
            continue
        if any(character.isalpha() for character in code) != any(character.isalpha() for character in token):
            continue
        score = text_similarity(code, token)
        prefix_score = 0
        if len(code) >= 2 and len(token) >= 2 and code[:2] == token[:2]:
            prefix_score = 2
        elif code[:1] == token[:1]:
            prefix_score = 1
        if (prefix_score, score) > (best_prefix_score, best_score):
            best_code = code
            best_prefix_score = prefix_score
            best_score = score
    return best_code if best_score >= 0.66 else ""


def _format_statute_code(value: str) -> str:
    if value.lower().endswith("a"):
        return value[:-1] + "A"
    return value


def slugify(value: str, fallback: str = "field") -> str:
    normalized = normalize_text(value)
    if not normalized:
        return fallback
    slug = re.sub(r"\s+", "_", normalized)
    return slug.strip("_") or fallback


def ensure_unique_slug(base: str, used_names: Set[str]) -> str:
    candidate = slugify(base)
    if candidate not in used_names:
        used_names.add(candidate)
        return candidate
    index = 2
    while True:
        suffixed = f"{candidate}_{index}"
        if suffixed not in used_names:
            used_names.add(suffixed)
            return suffixed
        index += 1


def is_semantic_field_name(name: str) -> bool:
    if not name:
        return False
    normalized = slugify(name)
    if normalized != name:
        return False
    return GENERIC_FIELD_NAME_RE.match(name) is None


def text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def derive_field_confidence(
    source_kind: str,
    value: str,
    review_reasons: Sequence[str] | None = None,
) -> float:
    if not (value or "").strip():
        return 0.0
    base = SOURCE_CONFIDENCE_BY_KIND.get(source_kind or "llm_page", 0.78)
    penalty = 0.0
    for reason in review_reasons or ():
        penalty += REVIEW_REASON_PENALTIES.get(reason, 0.0)
    return clamp_confidence(base - penalty)


def ensure_parent_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
