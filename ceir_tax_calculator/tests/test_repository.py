from app.database import Database
from app.models.calculation import CalculationRecord
from app.repositories.calculation_repository import CalculationRepository


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
