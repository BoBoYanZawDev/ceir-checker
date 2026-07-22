from __future__ import annotations

import csv
from pathlib import Path


class ExportService:
    @staticmethod
    def export_history(rows: list[dict], destination: str | Path) -> None:
        columns = [
            "id", "date_time", "check_type", "imei_or_app_id", "brand", "model", "base_price",
            "customs_duty", "commercial_tax", "redemption_fee", "income_tax", "total_tax",
            "taxation_status", "network_status", "check_message", "created_at",
        ]
        with Path(destination).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
