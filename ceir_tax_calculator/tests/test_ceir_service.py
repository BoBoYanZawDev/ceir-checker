import json
import io
import urllib.parse
import urllib.error
import urllib.request

from app.services.ceir_service import CEIRService


def test_http_error_displays_ceir_message() -> None:
    service = CEIRService()
    body = json.dumps({
        "status": 400,
        "message": "Request to white list with DeclarationID=MM-CR-ODHURUO not found",
        "error": "",
    }).encode()

    class FailingOpener:
        def open(self, _request, timeout):
            raise urllib.error.HTTPError("https://ceir.test", 400, "Bad Request", {}, io.BytesIO(body))

    service.opener = FailingOpener()  # type: ignore[assignment]
    try:
        service._json_request(urllib.request.Request("https://ceir.test"))
    except RuntimeError as exc:
        assert str(exc) == "Not Found"
    else:
        raise AssertionError("Expected CEIR error")


def test_multiple_imeis_are_sent_as_separate_requests(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_challenge", lambda: {"challenge": "x", "salt": "x", "signature": "x"})
    monkeypatch.setattr(service, "_solve", lambda _challenge: "token")
    captured: list[list[str]] = []

    def fake_request(request):
        submitted = json.loads(request.data.decode())
        captured.append(submitted)
        return {
            "IMEI_CHECK_LIST": [
                {"IMEI": imei, "paymentState": "ACCUMULATION", "blockState": "UNBLOCKED"}
                for imei in submitted
            ]
        }

    monkeypatch.setattr(service, "_json_request", fake_request)
    imeis = ["123456789012345", "543210987654321"]
    results = service.check_imeis(imeis)
    assert captured == [[imeis[0]], [imeis[1]]]
    assert [result.imei for result in results] == imeis
    assert all(result.network_status is True for result in results)


def test_device_info_maps_gsma_fields(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_challenge", lambda: {"challenge": "x", "salt": "x", "signature": "x"})
    monkeypatch.setattr(service, "_solve", lambda _challenge: "device-token")
    requested_url = ""

    def fake_request(request):
        nonlocal requested_url
        requested_url = request.full_url
        return {
            "tac": "35078228", "shortIMEI": "7836844", "gsmaModelName": "iPhone 17 Pro Max A3526",
            "gsmaImeiQuantitySupport": 2, "gsmaDeviceType": "Smartphone", "gsmaManufacturer": "Apple",
            "gsmaBrandName": "Apple", "gsmaAllocationDate": "11-Mar-2026", "gsmaOperatingSystem": "iOS",
        }

    monkeypatch.setattr(service, "_json_request", fake_request)
    info = service.get_device_info("350782287836844")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(requested_url).query)
    assert query == {"altcha": ["device-token"], "imei": ["350782287836844"]}
    assert info.brand == "Apple"
    assert info.model == "iPhone 17 Pro Max A3526"
    assert info.imei_quantity_support == 2


def test_registration_status_maps_tax_and_device_fields(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_challenge", lambda: {"challenge": "x", "salt": "x", "signature": "x"})
    monkeypatch.setattr(service, "_solve", lambda _challenge: "registration-token")

    def fake_request(_request):
        return {"RequestStatus": {
            "devices": [{"brand": "Poco", "model": "Poco C85", "imeis": ["860534072504571", "860534072504563"]}],
            "orderCalculation": {"amount": 88830, "collectingCalculations": [
                {"collectingType": "CUSTOMS_DUTY", "amount": 12600},
                {"collectingType": "COMMERCIAL_TAX", "amount": 13230},
                {"collectingType": "REDEMPTION_FINE", "amount": 63000},
            ]},
            "declarationId": "MM-CR-51PX4FJ", "declarationHash": "hash", "basePriceSum": 252000,
            "createdDt": "2026-07-16", "confirmedDt": "2026-07-16", "ExpirationDate": "2026-09-14",
            "BusinessState": "PAID",
        }}

    monkeypatch.setattr(service, "_json_request", fake_request)
    status = service.get_registration_status("MM-CR-51PX4FJ")
    assert status.brand == "Poco"
    assert status.model == "Poco C85"
    assert status.base_price == 252000
    assert status.customs_duty == 12600
    assert status.commercial_tax == 13230
    assert status.redemption_fee == 63000
    assert status.total_tax == 88830
    assert status.taxation_status is True
