from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import certifi

from app.utils.constants import (
    CEIR_APPLICANT_URL,
    CEIR_BASE_URL,
    CEIR_CHALLENGE_URL,
    CEIR_DEVICE_INFO_URL,
    CEIR_DOCUMENT_TYPE_URL,
    CEIR_PAYMENT_CHECK_URL,
    CEIR_PAYMENT_URL,
    CEIR_REGION_URL,
    CEIR_REGISTRATION_REQUEST_URL,
    CEIR_REGISTRATION_STATUS_URL,
    CEIR_SAME_DEVICE_URL,
    CEIR_TAX_OFFICE_URL,
    CEIR_TAX_REGION_URL,
    CEIR_TOWNSHIP_URL,
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
class RegistrationTaxQuote:
    declaration_id: str
    customs_duty: int
    commercial_tax: int
    redemption_fee: int
    income_tax: int
    total_tax: int
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
    payment_at: str
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
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{CEIR_BASE_URL}/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
        }
        self._session_ready = False
        self._browser = None
        self._browser_lock = threading.RLock()
        self._pending_challenge: dict | None = None

    def _json_request(self, request: urllib.request.Request) -> dict | list | bool:
        if self._browser is not None:
            return self._browser_json_request(request)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 403 and self._is_geo_blocked(detail):
                raise RuntimeError(
                    "CEIR is only accessible from Myanmar. Turn off your VPN and try again."
                ) from exc
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

    def _browser_json_request(self, request: urllib.request.Request) -> dict | list | bool:
        """Run a CEIR request inside the embedded webview so Cloudflare cookies are included."""
        body = request.data.decode("utf-8") if request.data is not None else None
        command = {
            "action": "request",
            "method": request.get_method(),
            "url": request.full_url,
            "headers": dict(request.header_items()),
            "body": body,
        }
        with self._browser_lock:
            try:
                result = self._send_command(command)
            except RuntimeError as exc:
                raise RuntimeError(f"CEIR browser request failed: {exc}") from exc
        if result.get("error"):
            raise RuntimeError(f"Could not connect to CEIR: {result['error']}")
        status = int(result.get("status") or 0)
        detail = str(result.get("text") or "")
        if status >= 400:
            if status == 403 and self._is_geo_blocked(detail):
                raise RuntimeError(
                    "CEIR is only accessible from Myanmar. Turn off your VPN and try again."
                )
            try:
                error_data = json.loads(detail)
            except json.JSONDecodeError:
                error_data = {}
            message = error_data.get("message") or error_data.get("error")
            if message:
                friendly = "Not Found" if "not found" in str(message).lower() else str(message)
                raise RuntimeError(friendly)
            raise RuntimeError(f"CEIR returned HTTP {status}: {detail.strip()[:200] or 'Unknown error'}")
        try:
            return json.loads(detail)
        except json.JSONDecodeError as exc:
            raise RuntimeError("CEIR returned an unreadable response.") from exc

    def _text_request(self, request: urllib.request.Request) -> str:
        """Return a successful CEIR response without forcing JSON decoding."""
        if self._browser is None:
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"CEIR returned HTTP {exc.code}: {detail.strip()[:200] or exc.reason or 'Unknown error'}"
                ) from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f"Could not connect to CEIR: {exc.reason}") from exc

        body = request.data.decode("utf-8") if request.data is not None else None
        command = {
            "action": "request",
            "method": request.get_method(),
            "url": request.full_url,
            "headers": dict(request.header_items()),
            "body": body,
        }
        with self._browser_lock:
            result = self._send_command(command)
        if result.get("error"):
            raise RuntimeError(f"Could not connect to CEIR: {result['error']}")
        status = int(result.get("status") or 0)
        detail = str(result.get("text") or "")
        if status >= 400:
            if status == 403 and self._is_geo_blocked(detail):
                raise RuntimeError("CEIR is only accessible from Myanmar. Turn off your VPN and try again.")
            try:
                error_data = json.loads(detail)
            except json.JSONDecodeError:
                error_data = {}
            message = error_data.get("message") or error_data.get("error")
            raise RuntimeError(str(message) if message else f"CEIR returned HTTP {status}: {detail.strip()[:200] or 'Unknown error'}")
        return detail

    @staticmethod
    def _worker_command() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--altcha-browser-worker"]
        return [sys.executable, "-m", "app.services.altcha_browser"]

    def _send_command(self, command: dict) -> dict:
        process = self._browser
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("The CEIR browser session is not available.")
        process.stdin.write(json.dumps(command) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("The CEIR browser session ended unexpectedly.")
        return json.loads(line)

    def _abandon_session(self) -> None:
        process, self._browser = self._browser, None
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass

    def _ensure_session(self) -> None:
        """Open CEIR in an embedded webview and wait for its managed challenge to clear."""
        if self._session_ready:
            return
        with self._browser_lock:
            if self._session_ready:
                return
            try:
                import webview  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "CEIR browser support is missing. Reinstall the application dependencies."
                ) from exc

            try:
                self._browser = subprocess.Popen(
                    self._worker_command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                raise RuntimeError("Could not start the CEIR browser session.") from exc

            deadline = time.monotonic() + max(self.timeout, 45)
            last_text = ""
            while time.monotonic() < deadline:
                if self._browser.poll() is not None:
                    break
                try:
                    last_text = self._send_command({"action": "peek"}).get("text", "")
                except RuntimeError:
                    last_text = ""
                    time.sleep(0.4)
                    continue
                if self._is_geo_blocked(last_text):
                    self._abandon_session()
                    raise RuntimeError(
                        "CEIR is only accessible from Myanmar. Turn off your VPN and try again."
                    )
                try:
                    data = json.loads(last_text)
                except json.JSONDecodeError:
                    data = None
                if data and data.get("challenge") and data.get("salt"):
                    self._pending_challenge = data
                    self._session_ready = True
                    return
                time.sleep(0.4)
            self._abandon_session()
            if "security verification" in last_text.lower():
                raise RuntimeError("CEIR's Cloudflare verification did not finish. Please try again.")
            raise RuntimeError("Could not establish the CEIR browser session.")

    def reload_session(self) -> None:
        """Close any existing embedded-webview session and open a fresh one."""
        self.close()
        self._ensure_session()

    def close(self) -> None:
        with self._browser_lock:
            if self._browser is not None:
                try:
                    self._send_command({"action": "stop"})
                except Exception:
                    pass
            self._abandon_session()
            self._session_ready = False
            self._pending_challenge = None

    @staticmethod
    def _is_geo_blocked(detail: str) -> bool:
        lowered = detail.lower()
        return "access restricted" in lowered or "only accessible from myanmar" in lowered

    def _challenge(self) -> dict:
        """Fetch a fresh, one-use ALTCHA challenge with the reference backoff."""
        self._ensure_session()
        if self._pending_challenge is not None:
            challenge = self._pending_challenge
            self._pending_challenge = None
            return challenge
        last_error: RuntimeError | None = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(CEIR_CHALLENGE_URL, headers=self.headers)
                data = self._json_request(request)
                # The current endpoint always supplies salt; signature is
                # optional in the newer flow (the Electron reference only
                # requires the challenge field).
                if not data.get("challenge") or not data.get("salt"):
                    raise RuntimeError("CEIR challenge response is incomplete.")
                return data
            except RuntimeError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep((attempt + 1) * 0.8)
        raise RuntimeError("Could not get a fresh CEIR verification challenge.") from last_error

    @staticmethod
    def _solve(challenge: dict) -> str:
        target = challenge["challenge"]
        salt = challenge["salt"]
        started = time.monotonic()
        for number in range(int(challenge.get("maxnumber", 1_000_000))):
            if hashlib.sha256(f"{salt}{number}".encode()).hexdigest() == target:
                payload = {
                    "algorithm": challenge.get("algorithm", "SHA-256"),
                    "challenge": target,
                    "number": number,
                    "salt": salt,
                    "took": int((time.monotonic() - started) * 1000),
                }
                if challenge.get("signature"):
                    payload["signature"] = challenge["signature"]
                return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        raise RuntimeError("Could not solve the CEIR verification challenge.")

    @staticmethod
    def _to_check_result(imei: str, item: dict) -> CheckResult:
        payment = str(item.get("paymentState", "FAILED"))
        block = str(item.get("blockState", "UNKNOWN"))
        payment_upper = payment.upper()
        block_upper = block.upper()
        if payment_upper == "UNKNOWN":
            taxation = None
        else:
            unpaid_markers = ("UNPAID", "NOT_", "PENDING", "ACCUMULATION", "DUE")
            taxation = not any(marker in payment_upper for marker in unpaid_markers) and (
                payment_upper in {"PAID", "PAYMENT_SUCCESS", "COMPLETED"}
                or payment_upper.endswith("_PAID")
            )
        network = None if block_upper == "UNKNOWN" else "UNBLOCKED" in block_upper or block_upper in {"PASS", "OK"}
        return CheckResult(
            imei=str(item.get("IMEI", imei)), payment_state=payment, block_state=block,
            taxation_status=taxation, network_status=network, raw=item,
        )

    def check_imei(self, imei: str) -> CheckResult:
        return self.check_imeis([imei])[0]

    def check_imeis(self, imeis: list[str]) -> list[CheckResult]:
        """Verify IMEIs one at a time, in order.

        CEIR's Verify endpoint rejects a batch whose IMEIs aren't all from the
        same device ("IMEIs do not belong to the same device"), so unrelated
        IMEIs can't be checked together in one call. Each IMEI gets its own
        fresh, one-time ALTCHA token; a failure on one doesn't stop the rest.
        """
        if not imeis:
            return []
        results: list[CheckResult] = []
        for imei in imeis:
            try:
                results.append(self._verify_one(imei))
            except RuntimeError as exc:
                results.append(self._to_check_result(imei, {
                    "IMEI": imei, "paymentState": "FAILED", "blockState": "UNKNOWN", "error": str(exc),
                }))
        return results

    def _verify_one(self, imei: str) -> CheckResult:
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
        if not isinstance(items, list) or not items:
            message = data.get("message") or data.get("error") or "No IMEI result was returned."
            raise RuntimeError(str(message))
        lookup = {str(item.get("IMEI")): item for item in items if isinstance(item, dict)}
        return self._to_check_result(
            imei, lookup.get(imei, {"IMEI": imei, "paymentState": "FAILED", "blockState": "UNKNOWN"}),
        )

    def get_device_info(self, imei: str) -> DeviceInfo:
        """Return GSMA device metadata for one IMEI from CEIR."""
        self._ensure_session()
        # CEIR currently allows public device metadata with altcha=null. Fall
        # back to a fresh PoW token if that fast path is rejected or empty.
        null_query = urllib.parse.urlencode({"altcha": "null", "imei": imei})
        try:
            request = urllib.request.Request(f"{CEIR_DEVICE_INFO_URL}?{null_query}", headers=self.headers)
            data = self._json_request(request)
        except RuntimeError:
            data = {}
        if not self._has_device_info(data):
            token = self._solve(self._challenge())
            query = urllib.parse.urlencode({"altcha": token, "imei": imei})
            request = urllib.request.Request(f"{CEIR_DEVICE_INFO_URL}?{query}", headers=self.headers)
            data = self._json_request(request)
        if not self._has_device_info(data):
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

    def are_same_device(self, imeis: list[str]) -> bool:
        """Return CEIR's same-device decision for exactly two IMEIs."""
        if len(imeis) != 2:
            raise ValueError("Same-device validation requires exactly two IMEIs.")
        # Dual-SIM IMEIs commonly share one TAC; CEIR's documented request sends
        # that TAC once. Preserve order while removing duplicates.
        tacs = list(dict.fromkeys(self.get_device_info(imei).tac or imei[:8] for imei in imeis))
        token = self._solve(self._challenge())
        query = urllib.parse.urlencode({"altcha": token, "tacs": tacs}, doseq=True)
        response = self._json_request(urllib.request.Request(f"{CEIR_SAME_DEVICE_URL}?{query}", headers=self.headers))
        if isinstance(response, bool):
            return response
        if isinstance(response, dict):
            value = response.get("sameDevice", response.get("result", response.get("data")))
            if isinstance(value, bool):
                return value
        raise RuntimeError("CEIR returned an unreadable same-device response.")

    def _protected_list(self, url: str, **parameters: object) -> list[dict]:
        token = self._solve(self._challenge())
        query = urllib.parse.urlencode({**parameters, "altcha": token})
        response = self._json_request(urllib.request.Request(f"{url}?{query}", headers=self.headers))
        if not isinstance(response, list):
            raise RuntimeError("CEIR returned an unreadable filter response.")
        return [item for item in response if isinstance(item, dict)]

    def get_regions(self) -> list[dict]:
        return self._protected_list(CEIR_REGION_URL)

    def get_townships(self, region_code: int | str) -> list[dict]:
        return self._protected_list(CEIR_TOWNSHIP_URL, regionCode=region_code)

    def get_document_types(self) -> list[dict]:
        return self._protected_list(CEIR_DOCUMENT_TYPE_URL)

    def get_tax_regions(self) -> list[dict]:
        return self._protected_list(CEIR_TAX_REGION_URL)

    def get_tax_offices(self, region_code: str) -> list[dict]:
        return self._protected_list(CEIR_TAX_OFFICE_URL, regionCode=region_code)

    @staticmethod
    def _has_device_info(data: dict) -> bool:
        return bool(data.get("tac") or data.get("gsmaBrandName") or data.get("gsmaModelName"))

    def get_registration_status(self, declaration_id: str) -> RegistrationStatus:
        """Return CEIR registration/tax status for one declaration ID."""
        token = self._solve(self._challenge())
        query = urllib.parse.urlencode({"DeclarationID": declaration_id, "altcha": token})
        request = urllib.request.Request(f"{CEIR_REGISTRATION_STATUS_URL}?{query}", headers=self.headers)
        data = self._json_request(request)
        status = data.get("RequestStatus") or data
        status_fields = ("DeclarationID", "declarationId", "BusinessState", "devices")
        if not isinstance(status, dict) or not any(key in status for key in status_fields):
            message = data.get("message") or data.get("error") or "No registration status was returned."
            raise RuntimeError(str(message))
        declaration_hash = str(status.get("declarationHash") or status.get("DeclarationHash") or "")
        if declaration_hash:
            applicant_query = urllib.parse.urlencode({"declarationHash": declaration_hash, "altcha": "null"})
            try:
                applicant = self._json_request(
                    urllib.request.Request(f"{CEIR_APPLICANT_URL}?{applicant_query}", headers=self.headers)
                )
            except RuntimeError:
                applicant = None
            if isinstance(applicant, dict):
                status["applicant"] = applicant
                data["applicant"] = applicant
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
            declaration_id=str(status.get("DeclarationID") or status.get("declarationId") or declaration_id),
            declaration_hash=declaration_hash,
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
            payment_at=str(status.get("paymentDt", "")),
            expiration_date=str(status.get("ExpirationDate", "")),
            raw=data,
        )

    def create_registration_request(
        self, devices: list[list[str]], applicant: dict, source: str = "LEGAL_INDIVIDUAL",
    ) -> RegistrationTaxQuote:
        """Submit a CEIR registration request for the given devices.

        `devices` is a list of phones, each given as its own list of 1 or 2
        IMEIs (dual-SIM phones share one device entry with both IMEIs, e.g.
        `[["111...345"], ["222...111", "222...222"]]` for one single-SIM phone
        and one dual-SIM phone) - CEIR groups tax and payment per device, not
        per individual IMEI.

        This creates a real, submitted declaration with CEIR under the given
        applicant identity - it is not a read-only quote.
        """
        token = self._solve(self._challenge())
        query = urllib.parse.urlencode({"source": source, "altcha": token})
        body = json.dumps({
            "imeisList": [{"imeis": imeis} for imeis in devices],
            "applicant": applicant,
        }).encode()
        request = urllib.request.Request(
            f"{CEIR_REGISTRATION_REQUEST_URL}?{query}",
            data=body,
            headers={**self.headers, "Content-Type": "application/json"},
            method="POST",
        )
        data = self._json_request(request)
        if data.get("HasError"):
            raise RuntimeError(str(data.get("Message") or "CEIR rejected the registration request."))
        registry = data.get("Registry") or {}
        if not registry.get("DeclarationID"):
            message = data.get("Message") or data.get("message") or "No registration was returned."
            raise RuntimeError(str(message))
        calculations = (registry.get("orderCalculation") or {}).get("collectingCalculations") or []
        amounts = {str(item.get("collectingType", "")): int(item.get("amount") or 0) for item in calculations}
        return RegistrationTaxQuote(
            declaration_id=str(registry.get("DeclarationID", "")),
            customs_duty=amounts.get("CUSTOMS_DUTY", 0),
            commercial_tax=amounts.get("COMMERCIAL_TAX", 0),
            redemption_fee=amounts.get("REDEMPTION_FINE", 0),
            income_tax=amounts.get("ADVANCED_INCOME_TAX", 0),
            total_tax=int(registry.get("amount") or 0),
            raw=data,
        )

    def create_registration_requests(
        self, devices: list[list[str]], applicant: dict, source: str = "LEGAL_INDIVIDUAL",
    ) -> list[RegistrationTaxQuote]:
        """Register one device at a time, looping over `devices`.

        CEIR issues one DeclarationID per RegistrationRequest call, so this is
        the only CEIR call that needs splitting for a multi-device batch -
        every other endpoint in this service already sends its full input in
        one normal call. Each device is submitted with its own fresh ALTCHA
        token, in order.
        """
        return [self.create_registration_request([imeis], applicant, source) for imeis in devices]

    def initialize_payment(
        self, declaration_id: str, declaration_hash: str = "", applicant: dict | None = None,
    ) -> str:
        """Build the IRD page, reusing fresh registration data when available."""
        if not declaration_hash:
            status = self.get_registration_status(declaration_id)
            declaration_hash = status.declaration_hash
        if not declaration_hash:
            raise RuntimeError("CEIR did not return a declaration hash for payment.")

        warmup_query = urllib.parse.urlencode({"declarationHash": declaration_hash, "altcha": "null"})
        self._text_request(urllib.request.Request(f"{CEIR_PAYMENT_CHECK_URL}?{warmup_query}", headers=self.headers))

        if applicant is None:
            applicant_query = urllib.parse.urlencode({"declarationHash": declaration_hash, "altcha": "null"})
            applicant = self._json_request(
                urllib.request.Request(f"{CEIR_APPLICANT_URL}?{applicant_query}", headers=self.headers)
            )
        token = self._solve(self._challenge())
        payment_query = urllib.parse.urlencode({"declarationHash": declaration_hash, "altcha": token})
        request = urllib.request.Request(
            f"{CEIR_PAYMENT_URL}?{payment_query}",
            data=json.dumps(applicant).encode("utf-8"),
            headers={**self.headers, "Accept": "text/html", "Content-Type": "application/json"},
            method="POST",
        )
        html = self._text_request(request)
        if len(html.strip()) < 20:
            raise RuntimeError("CEIR returned an empty IRD payment page.")
        injection = '<base href="https://ceir.gov.mm/"><meta name="viewport" content="width=1280">'
        lowered = html.lower()
        head_at = lowered.find("<head")
        head_end = html.find(">", head_at) if head_at >= 0 else -1
        html = html[:head_end + 1] + injection + html[head_end + 1:] if head_end >= 0 else injection + html
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".html", prefix="ceir_ird_", delete=False
        ) as handle:
            handle.write(html)
            return handle.name
