from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.database import Database
from app.models.calculation import ApplicantProfile, CalculationRecord, TaxSettings
from app.utils.constants import DEFAULT_APPLICANT, DEFAULT_SETTINGS


class CalculationRepository:
    COLUMNS = (
        "date_time", "check_type", "imei_or_app_id", "brand", "model", "base_price",
        "customs_duty", "commercial_tax", "redemption_fee", "income_tax", "total_tax",
        "taxation_status", "network_status", "check_message", "created_at",
    )

    def __init__(self, database: Database) -> None:
        self.database = database
        self._seed_settings()

    def _seed_settings(self) -> None:
        with self.database.connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                {**DEFAULT_SETTINGS, **DEFAULT_APPLICANT}.items(),
            )

    def add(self, record: CalculationRecord) -> int:
        record.stamp()
        values = [getattr(record, column) for column in self.COLUMNS]
        values[11] = None if record.taxation_status is None else int(record.taxation_status)
        values[12] = None if record.network_status is None else int(record.network_status)
        placeholders = ", ".join("?" for _ in self.COLUMNS)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO calculations ({', '.join(self.COLUMNS)}) VALUES ({placeholders})", values
            )
            return int(cursor.lastrowid)

    def get(self, record_id: int) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM calculations WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None

    def list_filtered(self, search: str = "", check_type: str = "ALL", page: int = 1, page_size: int = 15) -> tuple[list[dict], int]:
        conditions: list[str] = []
        parameters: list[object] = []
        if search.strip():
            term = f"%{search.strip()}%"
            conditions.append(
                "(imei_or_app_id LIKE ? OR brand LIKE ? OR model LIKE ? OR date_time LIKE ? OR check_message LIKE ?)"
            )
            parameters.extend([term] * 5)
        if check_type != "ALL":
            conditions.append("check_type = ?")
            parameters.append(check_type)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.database.connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM calculations{where}", parameters).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM calculations{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*parameters, page_size, (page - 1) * page_size],
            ).fetchall()
        return [dict(row) for row in rows], total

    def all_filtered(self, search: str = "", check_type: str = "ALL") -> list[dict]:
        rows, _ = self.list_filtered(search, check_type, 1, 1_000_000)
        return rows

    def delete(self, record_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM calculations WHERE id = ?", (record_id,))

    def clear(self) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM calculations")

    def get_settings(self) -> TaxSettings:
        with self.database.connect() as connection:
            stored = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM settings")}
        values = {**DEFAULT_SETTINGS, **stored}
        try:
            return TaxSettings(
                customs_duty_rate=Decimal(values["customs_duty_rate"]),
                commercial_tax_rate=Decimal(values["commercial_tax_rate"]),
                redemption_fee_rate=Decimal(values["redemption_fee_rate"]),
                income_tax_rate=Decimal(values["income_tax_rate"]),
                income_tax_enabled=values["income_tax_enabled"] == "1",
            )
        except InvalidOperation as exc:
            raise ValueError("Saved tax settings are invalid.") from exc

    def save_settings(self, settings: TaxSettings) -> None:
        values = {
            "customs_duty_rate": str(settings.customs_duty_rate),
            "commercial_tax_rate": str(settings.commercial_tax_rate),
            "redemption_fee_rate": str(settings.redemption_fee_rate),
            "income_tax_rate": str(settings.income_tax_rate),
            "income_tax_enabled": "1" if settings.income_tax_enabled else "0",
        }
        with self.database.connect() as connection:
            connection.executemany(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                values.items(),
            )

    def reset_settings(self) -> TaxSettings:
        with self.database.connect() as connection:
            connection.executemany(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                DEFAULT_SETTINGS.items(),
            )
        return self.get_settings()

    def get_applicant_profile(self) -> ApplicantProfile:
        with self.database.connect() as connection:
            stored = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM settings")}
        values = {**DEFAULT_APPLICANT, **stored}
        return ApplicantProfile(
            taxpayer_type=values["applicant_taxpayer_type"] or "Individual",
            is_foreigner=values["applicant_is_foreigner"] == "1",
            tin=values["applicant_tin"],
            national_id=values["applicant_national_id"],
            full_name=values["applicant_full_name"],
            birthday=values["applicant_birthday"],
            address=values["applicant_address"],
            email=values["applicant_email"],
            phone=values["applicant_phone"],
            tax_office_division=values["applicant_tax_office_division"],
            tax_office_code=values["applicant_tax_office_code"],
            region_code=values["applicant_region_code"],
            township_code=values["applicant_township_code"],
            uin=values["applicant_uin"],
        )

    def save_applicant_profile(self, profile: ApplicantProfile) -> None:
        values = {
            "applicant_taxpayer_type": profile.taxpayer_type,
            "applicant_is_foreigner": "1" if profile.is_foreigner else "0",
            "applicant_tin": profile.tin,
            "applicant_national_id": profile.national_id,
            "applicant_full_name": profile.full_name,
            "applicant_birthday": profile.birthday,
            "applicant_address": profile.address,
            "applicant_email": profile.email,
            "applicant_phone": profile.phone,
            "applicant_tax_office_division": profile.tax_office_division,
            "applicant_tax_office_code": profile.tax_office_code,
            "applicant_region_code": profile.region_code,
            "applicant_township_code": profile.township_code,
            "applicant_uin": profile.uin,
        }
        with self.database.connect() as connection:
            connection.executemany(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                values.items(),
            )
