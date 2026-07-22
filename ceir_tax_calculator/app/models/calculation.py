from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TaxSettings:
    customs_duty_rate: Decimal = Decimal("5")
    commercial_tax_rate: Decimal = Decimal("5")
    redemption_fee_rate: Decimal = Decimal("25")
    income_tax_rate: Decimal = Decimal("2")
    income_tax_enabled: bool = False


@dataclass(frozen=True, slots=True)
class TaxResult:
    base_price: int
    customs_duty: int
    commercial_tax: int
    redemption_fee: int
    income_tax: int
    total_tax: int
    grand_total: int
    effective_rate: Decimal


@dataclass(slots=True)
class CalculationRecord:
    check_type: str
    imei_or_app_id: str = ""
    brand: str = ""
    model: str = ""
    base_price: int | None = None
    customs_duty: int | None = None
    commercial_tax: int | None = None
    redemption_fee: int | None = None
    income_tax: int | None = None
    total_tax: int | None = None
    taxation_status: bool | None = None
    network_status: bool | None = None
    check_message: str = ""
    date_time: str = ""
    created_at: str = ""
    id: int | None = None

    def stamp(self) -> None:
        now = datetime.now().astimezone()
        self.date_time = self.date_time or now.strftime("%Y-%m-%d %H:%M:%S")
        self.created_at = self.created_at or now.isoformat(timespec="seconds")
