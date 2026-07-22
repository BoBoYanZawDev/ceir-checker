from __future__ import annotations

APP_NAME = "CEIR Mobile Tax Calculator"
CHECK_TYPES = ("APP ID CHECK", "SINGLE CHECK", "BATCH CHECK")
DEFAULT_SETTINGS = {
    "customs_duty_rate": "5",
    "commercial_tax_rate": "5",
    "redemption_fee_rate": "25",
    "income_tax_rate": "2",
    "income_tax_enabled": "0",
}
CEIR_BASE_URL = "https://www.ceir.gov.mm"
CEIR_CHALLENGE_URL = f"{CEIR_BASE_URL}/openapi/API/Auth/altcha/altcha"
CEIR_VERIFY_URL = f"{CEIR_BASE_URL}/openapi/API/IMEI/Verify"
CEIR_DEVICE_INFO_URL = "https://ceir.gov.mm/openapi/API/Device/personal-device-info"
CEIR_REGISTRATION_STATUS_URL = f"{CEIR_BASE_URL}/openapi/API/IMEI/RegistrationStatus"
PAGE_SIZE = 12
