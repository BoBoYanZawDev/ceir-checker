import json
import io
import urllib.parse
import urllib.error
import urllib.request

from app.services.ceir_service import CEIRService, build_demo_registration_quote


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


def test_multiple_imeis_are_each_sent_as_their_own_altcha_request(monkeypatch) -> None:
    service = CEIRService()
    challenge_calls = {"count": 0}

    def fake_challenge():
        challenge_calls["count"] += 1
        return {"challenge": f"c{challenge_calls['count']}", "salt": "x", "signature": "x"}

    monkeypatch.setattr(service, "_challenge", fake_challenge)
    monkeypatch.setattr(service, "_solve", lambda challenge: f"token-for-{challenge['challenge']}")
    submitted: list[list[str]] = []
    tokens_used: list[str] = []

    def fake_request(request):
        payload = json.loads(request.data.decode())
        submitted.append(payload)
        tokens_used.append(urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["altcha"][0])
        return {
            "IMEI_CHECK_LIST": [
                {"IMEI": imei, "paymentState": "ACCUMULATION", "blockState": "UNBLOCKED"}
                for imei in payload
            ]
        }

    monkeypatch.setattr(service, "_json_request", fake_request)
    imeis = ["123456789012345", "543210987654321"]
    results = service.check_imeis(imeis)
    assert submitted == [[imeis[0]], [imeis[1]]]
    assert len(set(tokens_used)) == 2
    assert [result.imei for result in results] == imeis
    assert all(result.network_status is True for result in results)


def test_check_imeis_reports_one_failure_without_aborting_others(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_challenge", lambda: {"challenge": "x", "salt": "x", "signature": "x"})
    monkeypatch.setattr(service, "_solve", lambda _challenge: "token")
    call_count = {"n": 0}

    def fake_request(request):
        call_count["n"] += 1
        payload = json.loads(request.data.decode())
        if call_count["n"] == 1:
            raise RuntimeError("CEIR returned HTTP 400: IMEIs do not belong to the same device")
        return {
            "IMEI_CHECK_LIST": [
                {"IMEI": imei, "paymentState": "PAID", "blockState": "UNBLOCKED"}
                for imei in payload
            ]
        }

    monkeypatch.setattr(service, "_json_request", fake_request)
    imeis = ["111111111111111", "222222222222222"]
    results = service.check_imeis(imeis)
    assert [result.imei for result in results] == imeis
    assert results[0].payment_state == "FAILED"
    assert "do not belong to the same device" in results[0].raw["error"]
    assert results[1].payment_state == "PAID"
    assert results[1].network_status is True


def test_device_info_maps_gsma_fields(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_ensure_session", lambda: None)
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
    assert query == {"altcha": ["null"], "imei": ["350782287836844"]}
    assert info.brand == "Apple"
    assert info.model == "iPhone 17 Pro Max A3526"
    assert info.imei_quantity_support == 2


def test_device_info_falls_back_to_fresh_altcha(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_ensure_session", lambda: None)
    monkeypatch.setattr(service, "_challenge", lambda: {"challenge": "x", "salt": "x", "signature": "x"})
    monkeypatch.setattr(service, "_solve", lambda _challenge: "device-token")
    requested_urls: list[str] = []

    def fake_request(request):
        requested_urls.append(request.full_url)
        if len(requested_urls) == 1:
            return {}
        return {"tac": "35078228", "gsmaBrandName": "Apple", "gsmaModelName": "iPhone"}

    monkeypatch.setattr(service, "_json_request", fake_request)
    service.get_device_info("350782287836844")
    queries = [urllib.parse.parse_qs(urllib.parse.urlsplit(url).query) for url in requested_urls]
    assert queries == [
        {"altcha": ["null"], "imei": ["350782287836844"]},
        {"altcha": ["device-token"], "imei": ["350782287836844"]},
    ]


def test_challenge_retries_incomplete_responses(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_ensure_session", lambda: None)
    monkeypatch.setattr("app.services.ceir_service.time.sleep", lambda _seconds: None)
    responses = iter([
        {},
        {"challenge": "digest", "salt": "salt", "signature": "signature", "maxnumber": 10},
    ])
    monkeypatch.setattr(service, "_json_request", lambda _request: next(responses))

    assert service._challenge()["challenge"] == "digest"


def test_challenge_allows_optional_signature(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_ensure_session", lambda: None)
    monkeypatch.setattr(service, "_json_request", lambda _request: {
        "algorithm": "SHA-256", "challenge": "digest", "salt": "salt", "maxnumber": 10,
    })
    challenge = service._challenge()
    assert challenge["challenge"] == "digest"


def test_build_demo_registration_quote_does_not_hit_network() -> None:
    quote = build_demo_registration_quote(["350782287836844"])
    assert quote.declaration_id == "MM-CR-DEMO6844"
    assert quote.customs_duty == 59745
    assert quote.commercial_tax == 62732
    assert quote.redemption_fee == 298725
    assert quote.total_tax == 421202
    assert quote.raw["demo"] is True


def test_create_registration_request_maps_tax_fields(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_challenge", lambda: {"challenge": "x", "salt": "x", "signature": "x"})
    monkeypatch.setattr(service, "_solve", lambda _challenge: "registration-token")
    captured: dict = {}

    def fake_request(request):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        return {
            "HasError": False,
            "Registry": {
                "DeclarationID": "MM-CR-NEW123",
                "amount": 421202,
                "orderCalculation": {"collectingCalculations": [
                    {"collectingType": "CUSTOMS_DUTY", "amount": 59745},
                    {"collectingType": "COMMERCIAL_TAX", "amount": 62732},
                    {"collectingType": "REDEMPTION_FINE", "amount": 298725},
                ]},
            },
        }

    monkeypatch.setattr(service, "_json_request", fake_request)
    applicant = {"nationalId": "12/ABC(N)123456", "fullName": "Example User"}
    quote = service.create_registration_request([["353456789012345"]], applicant)
    assert captured["body"] == {"imeisList": [{"imeis": ["353456789012345"]}], "applicant": applicant}
    assert "source=LEGAL_INDIVIDUAL" in captured["url"]
    assert quote.declaration_id == "MM-CR-NEW123"
    assert quote.customs_duty == 59745
    assert quote.commercial_tax == 62732
    assert quote.redemption_fee == 298725
    assert quote.total_tax == 421202


def test_create_registration_request_groups_dual_sim_imeis_into_one_device(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_challenge", lambda: {"challenge": "x", "salt": "x", "signature": "x"})
    monkeypatch.setattr(service, "_solve", lambda _challenge: "registration-token")
    captured: dict = {}

    def fake_request(request):
        captured["body"] = json.loads(request.data.decode())
        return {"HasError": False, "Registry": {"DeclarationID": "MM-CR-DUAL1", "amount": 0, "orderCalculation": {}}}

    monkeypatch.setattr(service, "_json_request", fake_request)
    # One dual-SIM phone (both IMEIs belong to the same device) plus one single-SIM phone.
    devices = [["353456789012345", "353456789012352"], ["111111111111111"]]
    service.create_registration_request(devices, {})
    assert captured["body"]["imeisList"] == [
        {"imeis": ["353456789012345", "353456789012352"]},
        {"imeis": ["111111111111111"]},
    ]


def test_create_registration_requests_loops_one_device_per_call(monkeypatch) -> None:
    service = CEIRService()
    challenge_calls = {"count": 0}

    def fake_challenge():
        challenge_calls["count"] += 1
        return {"challenge": f"c{challenge_calls['count']}", "salt": "x", "signature": "x"}

    monkeypatch.setattr(service, "_challenge", fake_challenge)
    monkeypatch.setattr(service, "_solve", lambda challenge: f"token-for-{challenge['challenge']}")
    submitted_bodies: list[dict] = []
    tokens_used: list[str] = []

    def fake_request(request):
        submitted_bodies.append(json.loads(request.data.decode()))
        tokens_used.append(urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["altcha"][0])
        declaration_id = f"MM-CR-{len(submitted_bodies)}"
        return {"HasError": False, "Registry": {"DeclarationID": declaration_id, "amount": 100, "orderCalculation": {}}}

    monkeypatch.setattr(service, "_json_request", fake_request)
    # Three devices in one batch - a dual-SIM phone and two single-SIM phones.
    devices = [["111111111111111", "111111111111122"], ["222222222222222"], ["333333333333333"]]
    quotes = service.create_registration_requests(devices, {})
    assert [body["imeisList"] for body in submitted_bodies] == [
        [{"imeis": ["111111111111111", "111111111111122"]}],
        [{"imeis": ["222222222222222"]}],
        [{"imeis": ["333333333333333"]}],
    ]
    assert len(set(tokens_used)) == 3
    assert [quote.declaration_id for quote in quotes] == ["MM-CR-1", "MM-CR-2", "MM-CR-3"]


def test_create_registration_request_raises_on_has_error(monkeypatch) -> None:
    service = CEIRService()
    monkeypatch.setattr(service, "_challenge", lambda: {"challenge": "x", "salt": "x", "signature": "x"})
    monkeypatch.setattr(service, "_solve", lambda _challenge: "registration-token")
    monkeypatch.setattr(service, "_json_request", lambda _request: {"HasError": True, "Message": "Invalid applicant"})

    try:
        service.create_registration_request([["353456789012345"]], {})
    except RuntimeError as exc:
        assert str(exc) == "Invalid applicant"
    else:
        raise AssertionError("Expected CEIR error")


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
            "createdDt": "2026-07-16", "confirmedDt": "2026-07-16", "paymentDt": "2026-07-17",
            "ExpirationDate": "2026-09-14", "BusinessState": "PAID",
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
    assert status.confirmed_at == "2026-07-16"
    assert status.payment_at == "2026-07-17"
