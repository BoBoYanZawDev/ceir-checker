# CEIR Tool API Documentation

> Source code version: `5.6.0`  
> Base URL: `https://ceir.gov.mm`  
> This document is derived from the current implementation in `main.js`,
> `preload.js`, and `lib/cloud.js`. The CEIR endpoints are third-party endpoints;
> their server-side contract can change independently of this application.

## 1. Overview

The application uses three API layers:

1. **CEIR HTTP API** — IMEI checking, registration, applicant, and payment data.
2. **Supabase API** — account login, profiles, customer credit, and activity logs.
3. **Electron IPC API (`window.ceir`)** — the renderer-facing API exposed by
   `preload.js`.

The CEIR HTTP API is not called by a normal Node.js HTTP client. Requests run
inside a hidden Electron browser window so that the browser's Cloudflare cookies
and session are included (`credentials: "include"`).

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
  | request ?altcha=<token>    |
  |--------------------------->|
```

The solver searches for `number` where:

```text
SHA256(salt + number) == challenge
```

The solved payload contains these fields and is Base64-encoded before being
placed in the `altcha` query parameter:

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
POST /openapi/API/IMEI/Verify?altcha={ALTCHA_TOKEN}
Content-Type: application/json
```

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
GET /openapi/API/Device/personal-device-info?altcha={TOKEN_OR_NULL}&imei={IMEI}
```

Query parameters:

| Name | Required | Description |
| --- | --- | --- |
| `imei` | Yes | A Luhn-valid 15-digit IMEI. |
| `altcha` | Yes | A solved ALTCHA token, or literal `null` when the endpoint allows the fast path. |

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

The app first attempts `altcha=null`. If that does not return usable data, it
fetches and solves a fresh ALTCHA challenge for each TAC lookup.

### 3.4 Create an IMEI registration request

```http
POST /openapi/API/IMEI/RegistrationRequest?source=LEGAL_INDIVIDUAL&altcha={ALTCHA_TOKEN}
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
GET /openapi/API/IMEI/RegistrationStatus?DeclarationID={DECLARATION_ID}&altcha={ALTCHA_TOKEN}
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
GET /openapi/API/request/applicant?declarationHash={DECLARATION_HASH}&altcha=null
```

The declaration hash is obtained from Registration Status. The response is the
current applicant JSON object. Its full shape is controlled by CEIR; the app
preserves unknown fields when editing it.

### 3.7 Update/confirm applicant data

```http
POST /openapi/API/request/applicant?declarationHash={DECLARATION_HASH}&altcha={ALTCHA_TOKEN}
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
GET /openapi/API/phub/payment-check-result?declarationHash={DECLARATION_HASH}&altcha=null
```

This endpoint is called as a payment-flow warm-up in the current implementation.
Its response is not parsed.

### 3.9 Initialize Payment Hub

```http
POST /openapi/API/phub/payment?declarationHash={DECLARATION_HASH}&altcha={ALTCHA_TOKEN}
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

## 4. Other external services

### 4.1 Supabase

The Supabase project URL and publishable key are configured in `lib/cloud.js`.
The publishable key is deliberately not duplicated in this document.

Authentication uses Supabase Auth:

```js
client.auth.signInWithPassword({ email, password })
client.auth.getSession()
client.auth.signOut()
```

Database operations:

| Operation | Type | Input/selection | Purpose |
| --- | --- | --- | --- |
| `employee_users` | `SELECT` | `display_name, active, employee_id`; filter by `user_id` | Load employee profile. |
| `app_profiles` | `SELECT` | `shop_name, active`; filter by `user_id` | Load customer profile. |
| `app_balance` | RPC | none | Return current customer's credit balance. |
| `app_credit_cost` | RPC | none | Return credits charged per phone. |
| `consume_credit` | RPC | `p_ref`, `p_note` | Idempotently charge credit using Declaration ID as reference. |
| `app_activity_logs` | `UPSERT` | audit-event batches | Upload activity logs; conflict key is `user_id,client_id`. |

`consume_credit` request:

```json
{
  "p_ref": "DEC-...",
  "p_note": "353456789012345"
}
```

Handled RPC errors include `insufficient_credits`, `no_active_account`, and
`not_authenticated`.

### 4.2 Diagnostic services

| Method | URL | Purpose |
| --- | --- | --- |
| `HEAD` | `https://ceir.gov.mm/` | CEIR HTTPS reachability diagnosis. |
| `GET` | `https://ipinfo.io/json` | Detect egress IP/country for geo-block diagnosis. |
| `HEAD` | `https://1.1.1.1/` | General internet heartbeat. |

## 5. Electron renderer API (`window.ceir`)

These methods are available only inside this Electron application's renderer.
They are IPC calls, not publicly hosted HTTP endpoints.

### 5.1 Activation and account

| Method | Input | Main result |
| --- | --- | --- |
| `getMachineId()` | none | Formatted machine ID string. |
| `activate(code)` | license string | `{ ok, expiresAt? , reason?/error? }` from license validation. |
| `licenseInfo()` | none | `{ ok, reason, expiresAt, machineId }`. |
| `copyToClipboard(text)` | string | `true`. |
| `cloudLogin(email, password)` | credentials | `{ ok, profile? }` or `{ ok:false, message }`. |
| `cloudLogout()` | none | Signs out and restarts the application. |
| `cloudUser()` | none | Current profile or `null`. |
| `creditInfo()` | none | `{ ok:true, balance, cost }` or `{ ok:false, error }`. |

Cloud profile shape:

```json
{
  "kind": "employee",
  "user_id": "uuid",
  "email": "user@example.com",
  "display_name": "User",
  "active": true,
  "registered": true
}
```

`kind` may be `employee`, `customer`, or `none`.

### 5.2 Connection and diagnostics

| Method | Input | Main result |
| --- | --- | --- |
| `connect()` | none | `{ ok, title?, url?, error? }`. |
| `reconnect()` | none | Reloads CEIR, then returns the same result as `connect`. |
| `testApi()` | none | `{ ok:true, challenge, max }` or `{ ok:false, error }`. |
| `diagnose()` | none | DNS, HTTPS, egress-IP, bridge, and bridge-window diagnostic object. |
| `showCeirWindow()` | none | Shows the hidden CEIR browser window. |
| `captureStart()` | none | `{ ok:true, file }` or an error. |
| `captureStop()` | none | `{ ok:true, file, count }` or an error. |
| `captureStatus()` | none | `{ active, file?, count? }`. |

### 5.3 IMEI and registration operations

| Method | Input | Main result |
| --- | --- | --- |
| `enrichTacs(payload)` | TAC array, or `{ tacs, tacImeiMap }` | Object keyed by TAC with brand/model/device data. |
| `lookupDeclaration(decId)` | Declaration ID | `{ ok:true, row }` or `{ ok:false, error }`. |
| `smartResumeCheck(decIds)` | Declaration ID array | Array of `{ decId, biz_state }`. |
| `verifyBatch(opts)` | See below | `{ ok:true, total }` or a license error. |
| `verifyCancel()` | none | Requests cancellation. |
| `taxRegisterBatch(opts)` | See below | `{ ok:true, registered }` or an error. |
| `taxCancel()` | none | Requests cancellation. |
| `checkPayment(decId)` | Declaration ID | `{ ok, biz_state, rs }`. |
| `refetchDetails(rows)` | `[{ row, decId }]` | Refreshed tax/payment detail array. |

`verifyBatch` input:

```json
{
  "pairs": [
    { "imei1": "353456789012345", "imei2": "353456789012352" }
  ],
  "batchSize": 5,
  "delayMs": 2000
}
```

Each `verify-progress` result contains:

```json
{
  "imei1": "353456789012345",
  "imei2": "353456789012352",
  "payment1": "PAID",
  "payment2": "PAID",
  "blockState": "UNBLOCKED",
  "status": "OK"
}
```

`taxRegisterBatch` input:

```json
{
  "pairs": [
    { "imei1": "353456789012345", "imei2": "353456789012352" }
  ],
  "applicant": {
    "nationalId": "12/ABC(N)123456",
    "fullName": "Example User",
    "birthday": "1990-01-01",
    "address": "Yangon",
    "email": "user@example.com",
    "phone": "09xxxxxxxxx",
    "taxOfficeDivision": "...",
    "taxOfficeCode": "..."
  },
  "delayMs": 3000,
  "skipDuplicates": true
}
```

Successful registered-row shape:

```json
{
  "imei1": "353456789012345",
  "imei2": "353456789012352",
  "declaration_id": "DEC-...",
  "amount": 100000,
  "customs": 50000,
  "commercial": 50000,
  "fine": 0,
  "status": "OK",
  "pay_status": "PENDING",
  "print_flag": true
}
```

### 5.4 Applicant, payment, and printing

| Method | Input | Main result |
| --- | --- | --- |
| `fetchIrdHtml(decId)` | Declaration ID | `{ ok:true, url, html, dec_hash }` or `{ ok:false, error }`. |
| `getApplicant(decId)` | Declaration ID | `{ ok:true, dh, applicant }` or an error. |
| `updateApplicant(payload)` | `{ decId, fields }` | `{ ok:true, applicant }` or an error. |
| `printReceipt(payload)` | `{ decId, rowData, cfg }` | Printer or browser-preview result. |
| `listPrinters()` | none | `{ ok:true, printers, detected }`. |

`printReceipt` can return either:

```json
{ "ok": true, "mode": "printer", "printer": "Brother_QL_820NWB" }
```

or:

```json
{ "ok": true, "mode": "browser", "file": "/path/to/receipt.html" }
```

### 5.5 Files, configuration, state, and reports

| Method | Input | Main result |
| --- | --- | --- |
| `loadConfig()` | none | Current configuration object with defaults applied. |
| `saveConfig(cfg)` | configuration object | `{ ok:true }` or `{ ok:false, error }`. |
| `openLogsFolder()` | none | Opens and returns the audit-log directory. |
| `getLogsPath()` | none | Audit-log directory path. |
| `stateLoad()` | none | Saved renderer state. |
| `stateSave(state)` | any serializable state | Save result. |
| `stateClear()` | none | Clear result. |
| `imeiHistory()` | none | Object keyed by IMEI with Declaration ID and date. |
| `auditTodayDecls()` | none | Today's registered declaration rows from the audit log. |
| `dailyStats(days)` | number | Daily audit statistics. |
| `parseImeiText(text)` | string | Parsed IMEI pairs. |
| `importImeiFile()` | none | File-dialog/import result. |
| `exportImeiResults(results, label)` | results array, label | Export-dialog result. |
| `exportFailList(results)` | results array | Failed-list export result. |
| `exportTaxResults(results)` | results array | Tax-results export result. |
| `importTaxResults()` | none | `{ ok:true, results, path }`, cancellation, or error. |

Configuration defaults:

```json
{
  "batch_size": 5,
  "ceir_check_delay_sec": 2,
  "req_timeout": 20,
  "cf_wait_sec": 90,
  "tax_req_delay_sec": 3,
  "applicant": {
    "nationalId": "",
    "fullName": "",
    "birthday": "",
    "address": "",
    "email": "",
    "phone": "",
    "taxOfficeDivision": "",
    "taxOfficeCode": ""
  },
  "brother_printer_name": "",
  "brother_label_size": "62",
  "bank_account": "",
  "pay_autofill": false,
  "pay_auto_otp": true,
  "otp_listen_port": 8377,
  "otp_secret": ""
}
```

The current source defines OTP-related configuration fields, but it does not
implement a local HTTP OTP-listener endpoint.

## 6. Renderer events

Register listeners with the corresponding `window.ceir.on...` method.

| Listener | IPC event | Payload/purpose |
| --- | --- | --- |
| `onLicenseInfo(cb)` | `license-info` | License expiry and machine ID. |
| `onCloudUser(cb)` | `cloud-user` | Signed-in profile. |
| `onCreditBalance(cb)` | `credit-balance` | `{ balance }`. |
| `onCreditExhausted(cb)` | `credit-exhausted` | `{ balance, remaining }`. |
| `onLog(cb)` | `log` | Application log entry. |
| `onCfProgress(cb)` | `cf-progress` | `{ state, ts }`; state includes `loading`, `cf_challenge`, `parsing`, `ready`. |
| `onSessionExpired(cb)` | `session-expired` | `{ error }`. |
| `onGeoBlocked(cb)` | `geo-blocked` | `{ error }`. |
| `onConnTick(cb)` | `conn-tick` | Internet/API health and latency. |
| `onEnrichProgress(cb)` | `enrich-progress` | `{ done, total }`. |
| `onSmartResumeProgress(cb)` | `smart-resume-progress` | `{ done, total }`. |
| `onVerifyProgress(cb)` | `verify-progress` | `{ done, total, batchResults }`. |
| `onVerifyDone(cb)` | `verify-done` | `{ total }`. |
| `onTaxProgress(cb)` | `tax-progress` | `{ idx, total, result }`. |
| `onTaxDone(cb)` | `tax-done` | `{ total }`. |
| `onRefetchProgress(cb)` | `refetch-progress` | `{ done, total }`. |
| `onIrdProgress(cb)` | `ird-progress` | Payment/IRD workflow progress when emitted. |

Example renderer usage:

```js
window.ceir.onVerifyProgress(({ done, total, batchResults }) => {
  console.log(`${done}/${total}`, batchResults);
});

const result = await window.ceir.verifyBatch({
  pairs: [{ imei1: "353456789012345", imei2: "" }],
  batchSize: 5,
  delayMs: 2000
});
```

## 7. Errors and operational notes

- `HTTP 403` can indicate either Cloudflare/session failure or Myanmar
  geo-restriction. The app distinguishes geo-block pages by their HTML text.
- `HTTP 412` from device-info commonly means the supplied IMEI is not valid.
- Network and HTTP errors are written to the local audit log with request and
  truncated response details.
- CEIR API calls are serialized through a bridge lock to avoid concurrent use of
  the same browser session.
- Payment initialization chains are also serialized because overlapping CEIR
  payment calls can return HTTP `400`.
- License checks are local application gates. They are not CEIR HTTP endpoints.
- Supabase permissions are expected to be enforced server-side with Row Level
  Security (RLS).
