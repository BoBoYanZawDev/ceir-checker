from app.database import Database
from app.models.calculation import CalculationRecord
from app.repositories.calculation_repository import CalculationRepository
from app.views.main_window import is_payable_unpaid, registration_history_metadata


def test_add_filter_and_delete(tmp_path) -> None:
    repository = CalculationRepository(Database(tmp_path / "test.db"))
    record_id = repository.add(CalculationRecord(
        check_type="MANUAL CALCULATION", imei_or_app_id="APP-1", brand="Vivo", model="Y12A",
        base_price=203_700, total_tax=71_804,
    ))
    rows, total = repository.list_filtered("Vivo", "MANUAL CALCULATION")
    assert total == 1
    assert rows[0]["id"] == record_id
    repository.delete(record_id)
    assert repository.list_filtered()[1] == 0


def test_registration_history_recovers_and_searches_imeis(tmp_path) -> None:
    repository = CalculationRepository(Database(tmp_path / "registration.db"))
    record_id = repository.add(CalculationRecord(
        check_type="REGISTRATION REQUEST", imei_or_app_id="MM-CR-TEST1",
        check_message=(
            '{"imeis":["353173655744504","353173655744512"],'
            '"device_info":[{"gsmaBrandName":"Apple","gsmaModelName":"iPhone 13"}]}'
        ),
    ))
    rows, total = repository.list_filtered("353173655744504", "REGISTRATION REQUEST")
    assert total == 1
    assert rows[0]["id"] == record_id
    imeis, brand, model = registration_history_metadata(rows[0])
    assert imeis == ["353173655744504", "353173655744512"]
    assert brand == "Apple"
    assert model == "iPhone 13"


def test_only_real_unpaid_states_offer_paytax() -> None:
    assert is_payable_unpaid("UNPAID", False)
    assert is_payable_unpaid("UNPAID", False, True)
    assert not is_payable_unpaid("UNPAID", False, False)
    assert not is_payable_unpaid("ACCUMULATION", True)
    assert not is_payable_unpaid("PAYMENT_PENDING", None)
    assert not is_payable_unpaid("FAILED", False)
    assert not is_payable_unpaid("PAID", True)
