from decimal import Decimal

import pytest

from app.models.calculation import TaxSettings
from app.services.tax_service import TaxService


@pytest.mark.parametrize(
    ("price", "customs", "commercial", "redemption", "total"),
    [
        (1_995_000, 99_750, 104_738, 498_750, 703_238),
        (693_000, 34_650, 36_383, 173_250, 244_283),
        (203_700, 10_185, 10_694, 50_925, 71_804),
    ],
)
def test_worked_examples(price: int, customs: int, commercial: int, redemption: int, total: int) -> None:
    result = TaxService.calculate(price)
    assert (result.customs_duty, result.commercial_tax, result.redemption_fee, result.total_tax) == (
        customs, commercial, redemption, total
    )


def test_rounds_each_component_half_up_not_bankers() -> None:
    settings = TaxSettings(
        customs_duty_rate=Decimal("50"), commercial_tax_rate=Decimal("0"),
        redemption_fee_rate=Decimal("0"), income_tax_rate=Decimal("0"),
    )
    assert TaxService.calculate(5, settings).customs_duty == 3


@pytest.mark.parametrize("price", [0, -1, "not a number"])
def test_rejects_invalid_base_price(price: object) -> None:
    with pytest.raises(ValueError):
        TaxService.calculate(price)  # type: ignore[arg-type]


def test_optional_income_tax() -> None:
    settings = TaxSettings(income_tax_enabled=True)
    result = TaxService.calculate(100_000, settings)
    assert result.income_tax == 2_000
    assert result.total_tax == 37_250
