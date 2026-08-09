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
class ApplicantProfile:
    taxpayer_type: str = "Individual"
    is_foreigner: bool = False
    tin: str = ""
    national_id: str = ""
    full_name: str = ""
    birthday: str = ""
    address: str = ""
    email: str = ""
    phone: str = ""
    tax_office_division: str = ""
    tax_office_code: str = ""
    region_code: str = ""
    township_code: str = ""
    uin: str = ""

    def is_complete(self) -> bool:
        return bool(self.national_id and self.full_name and self.birthday and self.address and self.phone)

    def to_api_payload(self) -> dict:
        return {
            "id": None,
            "requestId": None,
            "taxpayerType": self.taxpayer_type,
            "isForeigner": self.is_foreigner,
            "tin": self.tin or None,
            "nationalId": self.national_id,
            "fullName": self.full_name,
            "birthday": self.birthday,
            "address": self.address,
            "email": self.email or None,
            "phone": self.phone,
            "taxOfficeDivision": self.tax_office_division or None,
            "taxOfficeCode": self.tax_office_code or None,
            "regionCode": self.region_code or None,
            "townshipCode": self.township_code or None,
            "uin": self.uin or None,
        }


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
