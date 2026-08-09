from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_mmk(value: str | int | Decimal) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Base price must be a valid number.") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Base price must be greater than zero.")
    return amount


def format_mmk(value: int | Decimal | None) -> str:
    if value is None:
        return ""
    return f"{int(value):,} MMK"


def format_number_input(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    return f"{int(digits):,}" if digits else ""
