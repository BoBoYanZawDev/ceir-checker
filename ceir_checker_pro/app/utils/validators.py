from __future__ import annotations

import re
from datetime import datetime


def normalize_birthday(value: str) -> str:
    """Accept common editable date formats and return CEIR's ISO date format."""
    clean = value.strip()
    for date_format in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(clean, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("Birthday must use DD-MM-YYYY (for example 14-04-1992).")


def parse_nrc(value: str) -> tuple[str, str, str, str]:
    """Split a CEIR NRC into region, township, document type, and number."""
    match = re.fullmatch(r"(\d{1,2})/([^()]+)\(([A-Za-z]+)\)(\d{6})", value.strip())
    if not match:
        return "", "", "", ""
    return match.group(1), match.group(2), match.group(3), match.group(4)


def build_nrc(region: str, township: str, document_type: str, number: str) -> str:
    """Build CEIR's NRC payload while allowing the user to type only its number."""
    clean_number = number.strip()
    if not region or not township or not document_type:
        raise ValueError("Select NRC region, township, and document type.")
    if not re.fullmatch(r"\d{6}", clean_number):
        raise ValueError("NRC number must contain exactly 6 digits.")
    return f"{region}/{township}({document_type}){clean_number}"


def sanitize_identifier_input(value: str) -> str:
    """Remove inline whitespace while preserving new lines as separators."""
    return "".join(character for character in value if character == "\n" or not character.isspace())


def validate_imei(value: str) -> str:
    clean = value.strip()
    if not re.fullmatch(r"\d{15}", clean):
        raise ValueError("IMEI must contain exactly 15 digits.")
    return clean


def validate_app_id(value: str) -> str:
    clean = value.strip()
    if not clean or not re.fullmatch(r"[A-Za-z0-9-]+", clean):
        raise ValueError("Application ID may contain only letters, numbers, and hyphens.")
    return clean


def validate_identifier(value: str, check_type: str) -> str:
    if check_type == "APP ID CHECK":
        return validate_app_id(value)
    if check_type == "SINGLE CHECK":
        return validate_imei(value)
    return value.strip()


def parse_imei_list(value: str) -> list[str]:
    """Parse unique IMEIs separated by commas, whitespace, or new lines."""
    imeis: list[str] = []
    invalid: list[str] = []
    for candidate in value.replace(",", " ").split():
        try:
            imei = validate_imei(candidate)
        except ValueError:
            invalid.append(candidate)
            continue
        if imei not in imeis:
            imeis.append(imei)
    if invalid:
        preview = ", ".join(invalid[:5])
        suffix = "…" if len(invalid) > 5 else ""
        raise ValueError(f"Invalid IMEI value(s): {preview}{suffix}. Every IMEI must be exactly 15 digits.")
    if not imeis:
        raise ValueError("Enter at least one 15-digit IMEI.")
    return imeis


def parse_app_id_list(value: str) -> list[str]:
    """Parse unique application IDs separated by commas or whitespace."""
    app_ids: list[str] = []
    invalid: list[str] = []
    for candidate in value.replace(",", " ").split():
        try:
            app_id = validate_app_id(candidate)
        except ValueError:
            invalid.append(candidate)
            continue
        if app_id not in app_ids:
            app_ids.append(app_id)
    if invalid:
        preview = ", ".join(invalid[:5])
        suffix = "…" if len(invalid) > 5 else ""
        raise ValueError(f"Invalid App ID value(s): {preview}{suffix}.")
    if not app_ids:
        raise ValueError("Enter at least one Application ID.")
    return app_ids
