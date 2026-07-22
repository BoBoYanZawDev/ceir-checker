from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.models.calculation import TaxResult, TaxSettings
from app.utils.currency import parse_mmk


WHOLE_MMK = Decimal("1")


class TaxService:
    @staticmethod
    def calculate(base_price: str | int | Decimal, settings: TaxSettings | None = None) -> TaxResult:
        configured = settings or TaxSettings()
        price = parse_mmk(base_price)

        def percentage(amount: Decimal, rate: Decimal) -> int:
            return int((amount * rate / Decimal("100")).quantize(WHOLE_MMK, rounding=ROUND_HALF_UP))

        customs = percentage(price, configured.customs_duty_rate)
        commercial = percentage(price + Decimal(customs), configured.commercial_tax_rate)
        redemption = percentage(price, configured.redemption_fee_rate)
        income = percentage(price, configured.income_tax_rate) if configured.income_tax_enabled else 0
        total = customs + commercial + redemption + income
        rounded_price = int(price.quantize(WHOLE_MMK, rounding=ROUND_HALF_UP))
        effective = (Decimal(total) / price * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return TaxResult(
            base_price=rounded_price,
            customs_duty=customs,
            commercial_tax=commercial,
            redemption_fee=redemption,
            income_tax=income,
            total_tax=total,
            grand_total=rounded_price + total,
            effective_rate=effective,
        )
