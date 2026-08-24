# CEIR Tool API Documentation

> Source code version: `5.6.0`  
> Base URL: `https://ceir.gov.mm`  
> This document is derived from the current implementation in `main.js`,
> `preload.js`, and `lib/cloud.js`. The CEIR endpoints are third-party endpoints;
> their server-side contract can change independently of this application.

## 1. Overview

This document covers only the CEIR HTTP API endpoints used by the application
for IMEI checking, device information, registration, applicant data, payment
status, and IRD payment initialization.

The application runs these requests inside a hidden Electron browser window so
that the browser's Cloudflare cookies and session are included
(`credentials: "include"`).

## 2. Common CEIR requirements

### 2.1 Session and network

- The browser must first load `https://ceir.gov.mm` and pass any Cloudflare
  challenge.
- `/openapi/*` is geo-restricted to Myanmar IP addresses. A foreign VPN exit can
  return HTTP `403` with an `Access Restricted` HTML page.
- Requests use the hidden browser's cookies automatically.
- Most protected operations require a fresh ALTCHA proof-of-work token.
- The application treats ALTCHA tokens as one-time tokens and fetches a new one
  for protected calls.

### 2.2 ALTCHA flow

```text
Client                       CEIR
  |                            |
  | GET /Auth/altcha/altcha    |
  |--------------------------->|
  | challenge JSON             |
  |<---------------------------|
  |                            |
  | solve SHA256 PoW locally   |
  |                            |
  | request ?altchaData=<token>|
  |--------------------------->|
```

The solver searches for `number` where:

```text
SHA256(salt + number) == challenge
```

The solved payload contains these fields and is Base64-encoded before being
placed in the `altchaData` query parameter:

```json
{
  "algorithm": "SHA-256",
  "challenge": "...",
  "number": 12345,
  "salt": "...",
  "signature": "...",
  "took": 42
}
```

`took` is the local proof-of-work solve time in milliseconds.

## 3. CEIR HTTP endpoints

### 3.1 Get ALTCHA challenge

```http
GET /openapi/API/Auth/altcha/altcha
```

Parameters: none.

Expected response:

```json
{
  "algorithm": "SHA-256",
  "challenge": "hex digest",
  "maxnumber": 1000000,
  "salt": "random salt",
  "signature": "server signature"
}
```

Used before IMEI verification, registration, registration-status lookup,
applicant update, and payment initialization. The app retries challenge
generation up to three times with short backoff delays.

### 3.2 Verify IMEIs

```http
POST /openapi/API/IMEI/Verify?altchaData={ALTCHA_TOKEN}
Content-Type: application/json
```

Protected endpoints use `altchaData` for the solved ALTCHA token.

Request body: a JSON array of IMEI strings. One batch may contain both IMEIs of
each phone.

```json
[
  "353456789012345",
  "353456789012352"
]
```

Fields read from the response:

```json
{
  "IMEI_CHECK_LIST": [
    {
      "IMEI": "353456789012345",
      "paymentState": "PAID",
      "blockState": "UNBLOCKED"
    }
  ]
}
```

Known application values:

- `paymentState`: `PAID`, `UNPAID`, or treated as `FAILED` when absent.
- `blockState`: normally `UNBLOCKED`; other server values are passed through.

### 3.3 Get device information

```http
GET /openapi/API/Device/personal-device-info?altchaData={TOKEN_OR_NULL}&imei={IMEI}
```

Query parameters:

| Name | Required | Description |
| --- | --- | --- |
| `imei` | Yes | A Luhn-valid 15-digit IMEI. |
| `altchaData` | Yes | A solved ALTCHA token, or literal `null` when the endpoint allows the fast path. |

Fields used by this app:

```json
{
  "gsmaBrandName": "Apple",
  "gsmaManufacturer": "Apple Inc",
  "gsmaModelName": "iPhone ...",
  "gsmaDeviceType": "Smartphone",
  "gsmaOperatingSystem": "iOS"
}
```

The app first attempts `altchaData=null`. If that does not return usable data, it
fetches and solves a fresh ALTCHA challenge for each TAC lookup.

### 3.4 Create an IMEI registration request

```http
POST /openapi/API/IMEI/RegistrationRequest?source=LEGAL_INDIVIDUAL&altchaData={ALTCHA_TOKEN}
Content-Type: application/json
```

Request body:

```json
{
  "imeisList": [
    {
      "imeis": [
        "353456789012345",
        "353456789012352"
      ]
    }
  ],
  "applicant": {
    "id": null,
    "requestId": null,
    "taxpayerType": "Individual",
    "isForeigner": false,
    "tin": null,
    "nationalId": "12/ABC(N)123456",
    "fullName": "Example User",
    "birthday": "1990-01-01",
    "address": "Yangon",
    "email": "user@example.com",
    "phone": "09xxxxxxxxx",
    "taxOfficeDivision": "...",
    "taxOfficeCode": "...",
    "regionCode": null,
    "townshipCode": null,
    "uin": null
  }
}
```

Response fields consumed by the app:

```json
{
  "HasError": false,
  "Message": "...",
  "Registry": {
    "DeclarationID": "DEC-...",
    "amount": 100000,
    "orderCalculation": {
      "collectingCalculations": [
        {
          "collectingType": "CUSTOMS_DUTY",
          "amount": 50000,
          "conditionPassed": true
        }
      ]
    }
  }
}
```

Recognized calculation types are:

- `CUSTOMS_DUTY`
- `COMMERCIAL_TAX`
- `REDEMPTION_FINE`
- `ADVANCED_INCOME_TAX` (used when printing a receipt)

The application retries network errors, HTTP `403`, and HTTP `5xx` responses up
to three times. Other `4xx` responses are treated as final API responses.

### 3.5 Get registration/payment status

```http
GET /openapi/API/IMEI/RegistrationStatus?DeclarationID={DECLARATION_ID}&altchaData={ALTCHA_TOKEN}
```

Response may contain the status object at the root or under `RequestStatus`.
Fields consumed by the app include:

```json
{
  "RequestStatus": {
    "DeclarationID": "DEC-...",
    "declarationHash": "...",
    "BusinessState": "PAID",
    "amount": 100000,
    "confirmedDt": "2026-08-05T10:00:00",
    "paymentDt": "2026-08-05T10:00:00",
    "devices": [
      {
        "brand": "Apple",
        "model": "iPhone ...",
        "imeis": ["353456789012345"]
      }
    ],
    "orderCalculation": {
      "collectingCalculations": []
    }
  }
}
```

`BusinessState` is used as the payment state. The app commonly displays
`PENDING`, `PAID`, or `UNKNOWN` when no value can be obtained.

### 3.6 Get applicant data

```http
GET /openapi/API/request/applicant?declarationHash={DECLARATION_HASH}&altchaData=null
```

The declaration hash is obtained from Registration Status. The response is the
current applicant JSON object. Its full shape is controlled by CEIR; the app
preserves unknown fields when editing it.

### 3.7 Update/confirm applicant data

```http
POST /openapi/API/request/applicant?declarationHash={DECLARATION_HASH}&altchaData={ALTCHA_TOKEN}
Content-Type: application/json
```

Request body: the complete current applicant object merged with edited fields.

```json
{
  "nationalId": "12/ABC(N)123456",
  "fullName": "Updated Name",
  "birthday": "1990-01-01",
  "address": "Yangon",
  "email": "user@example.com",
  "phone": "09xxxxxxxxx"
}
```

The server may return the saved applicant object. If the response is not JSON
but the HTTP call succeeds, the application returns the locally merged object.

### 3.8 Check payment result

```http
GET /openapi/API/phub/payment-check-result?declarationHash={DECLARATION_HASH}&altchaData=null
```

This endpoint is called as a payment-flow warm-up in the current implementation.
Its response is not parsed.

### 3.9 Initialize Payment Hub

```http
POST /openapi/API/phub/payment?declarationHash={DECLARATION_HASH}&altchaData={ALTCHA_TOKEN}
Content-Type: application/json
```

Request body: the applicant JSON returned by the applicant endpoint.

Response: HTML containing the IRD payment form. It is not JSON. The app writes
the HTML to a temporary file and displays it in an embedded webview. The form
may subsequently submit to `onlinepayment.ird.gov.mm`.

Payment initialization sequence:

```text
RegistrationStatus
  -> ALTCHA challenge + local solve
  -> payment-check-result
  -> GET applicant
  -> POST phub/payment
  -> IRD HTML form
```

## 4. Errors and operational notes

- `HTTP 403` can indicate either Cloudflare/session failure or Myanmar
  geo-restriction. The app distinguishes geo-block pages by their HTML text.
- `HTTP 412` from device-info commonly means the supplied IMEI is not valid.
- The current application serializes CEIR requests through one browser session.
- Payment initialization calls should not overlap; concurrent chains can return
  HTTP `400`.
