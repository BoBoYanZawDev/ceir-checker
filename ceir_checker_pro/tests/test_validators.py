import pytest

from app.utils.validators import (
    build_nrc,
    normalize_birthday,
    parse_app_id_list,
    parse_imei_list,
    parse_nrc,
    sanitize_identifier_input,
    validate_app_id,
    validate_imei,
)


def test_birthday_accepts_editable_and_picker_formats() -> None:
    assert normalize_birthday("1992-04-14") == "1992-04-14"
    assert normalize_birthday("14-Apr-1992") == "1992-04-14"
    assert normalize_birthday("14/04/1992") == "1992-04-14"
    assert normalize_birthday("14-04-1992") == "1992-04-14"


def test_nrc_is_built_from_api_selections_and_number_only() -> None:
    assert build_nrc("1", "ဗမန", "N", "444543") == "1/ဗမန(N)444543"
    assert parse_nrc("1/ဗမန(N)444543") == ("1", "ဗမန", "N", "444543")
    with pytest.raises(ValueError):
        build_nrc("1", "ဗမန", "N", "44454")


def test_valid_imei() -> None:
    assert validate_imei("123456789012345") == "123456789012345"


@pytest.mark.parametrize("value", ["", "123", "12345678901234x", "1234567890123456"])
def test_invalid_imei(value: str) -> None:
    with pytest.raises(ValueError):
        validate_imei(value)


def test_application_id_rules() -> None:
    assert validate_app_id("APP-2026-A1") == "APP-2026-A1"
    with pytest.raises(ValueError):
        validate_app_id("APP 2026")


def test_parse_comma_and_newline_separated_imeis() -> None:
    assert parse_imei_list("123456789012345, 543210987654321\n123456789012345") == [
        "123456789012345", "543210987654321"
    ]


def test_parse_comma_and_newline_separated_app_ids() -> None:
    assert parse_app_id_list("MM-CR-51PX4FJ, MM-CR-ABC123\nMM-CR-51PX4FJ") == [
        "MM-CR-51PX4FJ", "MM-CR-ABC123"
    ]


def test_sanitize_identifier_input_removes_spaces_but_keeps_separators() -> None:
    assert sanitize_identifier_input("3539 9510\t4166 297,\n MM-CR- 51PX4FJ") == (
        "353995104166297,\nMM-CR-51PX4FJ"
    )
