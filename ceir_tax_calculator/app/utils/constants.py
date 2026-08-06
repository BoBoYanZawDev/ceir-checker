from __future__ import annotations

APP_NAME = "CEIR Mobile Tax Calculator"
CHECK_TYPES = ("APP ID CHECK", "SINGLE CHECK", "BATCH CHECK", "REGISTRATION REQUEST")
DEFAULT_SETTINGS = {
    "customs_duty_rate": "5",
    "commercial_tax_rate": "5",
    "redemption_fee_rate": "25",
    "income_tax_rate": "2",
    "income_tax_enabled": "0",
}
DEFAULT_APPLICANT = {
    "applicant_taxpayer_type": "Individual",
    "applicant_is_foreigner": "0",
    "applicant_tin": "",
    "applicant_national_id": "",
    "applicant_full_name": "",
    "applicant_birthday": "",
    "applicant_address": "",
    "applicant_email": "",
    "applicant_phone": "",
    "applicant_tax_office_division": "",
    "applicant_tax_office_code": "",
    "applicant_region_code": "",
    "applicant_township_code": "",
    "applicant_uin": "",
}
CEIR_BASE_URL = "https://ceir.gov.mm"
CEIR_CHALLENGE_URL = f"{CEIR_BASE_URL}/openapi/API/Auth/altcha/altcha"
CEIR_VERIFY_URL = f"{CEIR_BASE_URL}/openapi/API/IMEI/Verify"
CEIR_DEVICE_INFO_URL = f"{CEIR_BASE_URL}/openapi/API/Device/personal-device-info"
CEIR_REGISTRATION_STATUS_URL = f"{CEIR_BASE_URL}/openapi/API/IMEI/RegistrationStatus"
CEIR_REGISTRATION_REQUEST_URL = f"{CEIR_BASE_URL}/openapi/API/IMEI/RegistrationRequest"
PAGE_SIZE = 12
