from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import certifi

from app.utils.constants import (
    CEIR_CHALLENGE_URL,
    CEIR_DEVICE_INFO_URL,
    CEIR_REGISTRATION_STATUS_URL,
    CEIR_VERIFY_URL,
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    imei: str
    payment_state: str
    block_state: str
    taxation_status: bool | None
    network_status: bool | None
    raw: dict


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    imei: str
    tac: str
    brand: str
    manufacturer: str
    model: str
    device_type: str
    operating_system: str
    imei_quantity_support: int | None
    allocation_date: str
    raw: dict


@dataclass(frozen=True, slots=True)
class RegistrationStatus:
    declaration_id: str
    declaration_hash: str
    brand: str
    model: str
    imeis: tuple[str, ...]
    business_state: str
    taxation_status: bool | None
    base_price: int
    customs_duty: int
    commercial_tax: int
    redemption_fee: int
    total_tax: int
    created_at: str
    confirmed_at: str
    expiration_date: str
    raw: dict


class CEIRService:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        cookie_jar = http.cookiejar.CookieJar()
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPSHandler(context=ssl_context),
        )
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 CEIR-Mobile-Tax-Calculator/1.0",
        }

    def _json_request(self, request: urllib.request.Request) -> dict:
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                error_data = json.loads(detail)
            except json.JSONDecodeError:
                error_data = {}
            message = error_data.get("message") or error_data.get("error")
            if message:
                friendly_message = "Not Found" if "not found" in str(message).lower() else str(message)
                raise RuntimeError(friendly_message) from exc
            fallback = detail.strip()[:200] or exc.reason or "Unknown error"
            raise RuntimeError(f"CEIR returned HTTP {exc.code}: {fallback}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not connect to CEIR: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("CEIR returned an unreadable response.") from exc

    def _challenge(self) -> dict:
        request = urllib.request.Request(CEIR_CHALLENGE_URL, headers=self.headers)
        data = self._json_request(request)
        if not all(key in data for key in ("challenge", "salt", "signature")):
            raise RuntimeError("CEIR challenge response is incomplete.")
        return data

    @staticmethod
    def _solve(challenge: dict) -> str:
        target = challenge["challenge"]
        salt = challenge["salt"]
        started = time.monotonic()
        for number in range(int(challenge.get("maxnumber", 1_000_000)) + 1):
            if hashlib.sha256(f"{salt}{number}".encode()).hexdigest() == target:
                payload = {
                    "algorithm": challenge.get("algorithm", "SHA-256"),
                    "challenge": target,
                    "number": number,
                    "salt": salt,
                    "signature": challenge["signature"],
                    "took": int((time.monotonic() - started) * 1000),
                }
                return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        raise RuntimeError("Could not solve the CEIR verification challenge.")

    def check_imei(self, imei: str) -> CheckResult:
        token = self._solve(self._challenge())
        url = f"{CEIR_VERIFY_URL}?{urllib.parse.urlencode({'altcha': token})}"
        request = urllib.request.Request(
            url,
            data=json.dumps([imei]).encode(),
            headers={**self.headers, "Content-Type": "application/json"},
            method="POST",
        )
        data = self._json_request(request)
        items = data.get("IMEI_CHECK_LIST") or []
        if not items:
            message = data.get("message") or data.get("error") or "No IMEI result was returned."
            raise RuntimeError(str(message))
        item = items[0]
        payment = str(item.get("paymentState", "UNKNOWN"))
        block = str(item.get("blockState", "UNKNOWN"))
        payment_upper = payment.upper()
        block_upper = block.upper()
        taxation = None if payment_upper == "UNKNOWN" else not any(word in payment_upper for word in ("FAIL", "BLOCK", "UNPAID"))
        network = None if block_upper == "UNKNOWN" else "UNBLOCKED" in block_upper or block_upper in {"PASS", "OK"}
        return CheckResult(
            imei=str(item.get("IMEI", imei)), payment_state=payment, block_state=block,
            taxation_status=taxation, network_status=network, raw=item,
        )

    def check_imeis(self, imeis: list[str]) -> list[CheckResult]:
        """Check IMEIs sequentially because CEIR accepts one per request."""
        return [self.check_imei(imei) for imei in imeis]

    def get_device_info(self, imei: str) -> DeviceInfo:
        """Return GSMA device metadata for one IMEI from CEIR."""
        token = self._solve(self._challenge())
        query = urllib.parse.urlencode({"altcha": token, "imei": imei})
        request = urllib.request.Request(f"{CEIR_DEVICE_INFO_URL}?{query}", headers=self.headers)
        data = self._json_request(request)
        if not data.get("tac"):
            message = data.get("message") or data.get("error") or "No device information was returned."
            raise RuntimeError(str(message))
        quantity = data.get("gsmaImeiQuantitySupport")
        return DeviceInfo(
            imei=imei,
            tac=str(data.get("tac", "")),
            brand=str(data.get("gsmaBrandName", "")),
            manufacturer=str(data.get("gsmaManufacturer", "")),
            model=str(data.get("gsmaModelName", "")),
            device_type=str(data.get("gsmaDeviceType", "")),
            operating_system=str(data.get("gsmaOperatingSystem", "")),
            imei_quantity_support=int(quantity) if quantity is not None else None,
            allocation_date=str(data.get("gsmaAllocationDate", "")),
            raw=data,
        )

    def get_registration_status(self, declaration_id: str) -> RegistrationStatus:
        """Return CEIR registration/tax status for one declaration ID."""
        token = self._solve(self._challenge())
        query = urllib.parse.urlencode({"DeclarationID": declaration_id, "altcha": token})
        request = urllib.request.Request(f"{CEIR_REGISTRATION_STATUS_URL}?{query}", headers=self.headers)
        data = self._json_request(request)
        status = data.get("RequestStatus")
        if not isinstance(status, dict):
            message = data.get("message") or data.get("error") or "No registration status was returned."
            raise RuntimeError(str(message))
        devices = status.get("devices") or []
        brands = list(dict.fromkeys(str(device.get("brand", "")) for device in devices if device.get("brand")))
        models = list(dict.fromkeys(str(device.get("model", "")) for device in devices if device.get("model")))
        imeis = tuple(
            str(imei)
            for device in devices
            for imei in (device.get("imeis") or [])
            if imei
        )
        calculations = (status.get("orderCalculation") or {}).get("collectingCalculations") or []
        amounts = {str(item.get("collectingType", "")): int(item.get("amount") or 0) for item in calculations}
        business_state = str(status.get("BusinessState", "UNKNOWN"))
        state_upper = business_state.upper()
        taxation_status = None if state_upper == "UNKNOWN" else state_upper in {"PAID", "APPROVED", "CONFIRMED", "COMPLETED"}
        total_tax = int((status.get("orderCalculation") or {}).get("amount") or status.get("amount") or 0)
        return RegistrationStatus(
            declaration_id=str(status.get("declarationId") or declaration_id),
            declaration_hash=str(status.get("declarationHash", "")),
            brand=", ".join(brands),
            model=", ".join(models),
            imeis=imeis,
            business_state=business_state,
            taxation_status=taxation_status,
            base_price=int(status.get("basePriceSum") or 0),
            customs_duty=amounts.get("CUSTOMS_DUTY", 0),
            commercial_tax=amounts.get("COMMERCIAL_TAX", 0),
            redemption_fee=amounts.get("REDEMPTION_FINE", 0),
            total_tax=total_tax,
            created_at=str(status.get("createdDt", "")),
            confirmed_at=str(status.get("confirmedDt", "")),
            expiration_date=str(status.get("ExpirationDate", "")),
            raw=data,
        )
