# CEIR Mobile Tax Calculator — Project Specification

## 1. Overview

**Application name:** CEIR Mobile Tax Calculator
**Purpose:** Desktop tool for calculating Myanmar CEIR mobile phone customs tax (customs duty, commercial tax, redemption fee, optional income tax) from a phone's base price, and for tracking those calculations alongside CEIR/IMEI check results.
**Platforms:** Windows and macOS
**Stack:** Python 3.12+, CustomTkinter (UI), SQLite (storage), service/repository architecture.

### Relationship to prior app
`ceir_app_mac.py` (uploaded reference) is a *different* tool — a PyQt6 app that automates IMEI checks against the CEIR API and IMEI changes over ADB. It is not reused as code (different framework, different domain). It is kept only as UX prior art for two patterns carried into this spec:
- Light/dark theme toggle with a single button in the top bar.
- Color-coded status values in tables (green = good/passed, red = bad/failed/blocked, amber = pending/warning).

Everything else in this document is a new build.

## 2. UI Flow (per attached History screenshot + requirements)

### 2.1 Shell
- Sidebar navigation, left side, with 5 items: **Dashboard**, **Calculator**, **Batch Calculator**, **History**, **Settings**.
- Top bar per page: page title, light/dark mode toggle.
- Blue application theme, responsive layout (window resizes cleanly, table columns stretch).

### 2.2 Dashboard
Summary cards in a responsive grid:
- Total calculations
- Total base price (sum, formatted `#,###,### MMK`)
- Total tax amount (sum)
- Average tax amount
- Calculations today

### 2.3 Calculator (single calculation)
Form fields: Brand (optional), Model (optional), IMEI or Application ID, Check Type selector (drives IMEI vs App ID validation), Base Price (numeric, auto-comma-formatted as typed).
Actions: **Calculate**, **Reset**, **Copy Result**, **Save Calculation**.
Result panel shows, in order: Base Price, Customs Duty (5%), Commercial Tax (5%), Redemption Fee (25%), Income Tax (if enabled, separate row), Total Tax, Effective Tax Rate (35.25%, or recalculated rate if settings changed), Grand Total (base price + total tax).

### 2.4 Batch Calculator
- Import CSV (`imei_or_app_id, brand, model, base_price, taxation_status, network_status`).
- Background import/validation (must not freeze UI — run on worker thread).
- Row-level validation with a visible error list.
- Summary of success vs. failed row counts.
- Save all valid rows to history as `BATCH CHECK` records.
- Export batch results to CSV.

### 2.5 History — matches attached screenshot exactly
Window/panel title: **Database Check History**.

Top toolbar, left to right:
- Search box: placeholder **"Filter by IMEI, Brand, Model, Date, Hash..."** — live filters as the user types, matching against IMEI/App ID, Brand, Model, and Date Time.
- **Type** dropdown, default **ALL**, options: ALL / APP ID CHECK / SINGLE CHECK / BATCH CHECK / MANUAL CALCULATION.
- **Export CSV** button (exports the currently filtered result set).
- **Clear History** button, styled as a destructive/red action, requires a confirmation dialog before wiping all records.

Table columns (in this order, matching the screenshot): `ID | Date Time | Type | IMEI / App ID | Brand / Model | Taxation | Network | Base Price | Tax Price`.

Row rendering rules:
- `Type` cell is colored text per type: APP ID CHECK = blue, SINGLE CHECK = green, BATCH CHECK = amber/orange, MANUAL CALCULATION = neutral/gray. Column is sortable by clicking header (nice-to-have).
- `IMEI / App ID` is right/left elided with `...` when the value is long (as seen in the screenshot), full value visible via tooltip or the row-detail dialog.
- `Brand / Model` combines brand + model into one string (`"Redmi Redmi Note 15 Pro+"`).
- `Taxation` and `Network` are boolean status columns rendered as check (✔, green) or cross (✘, red) glyphs, blank when not applicable to that check type.
- `Base Price` / `Tax Price` right-aligned, formatted `#,###,### MMK`; blank when not applicable (e.g., pure batch-check rows with no priced calculation attached).
- Row striping (alternating background) as in the screenshot.

Footer: **Prev** / **Next** buttons (left/right) with **"Page N of M (Total Records: X)"** centered, matching the screenshot's pagination bar exactly. Page size configurable (default such that ~12+ rows fit before paging, matching screenshot behavior).

Additional required behaviors not visible in the static screenshot but specified:
- Delete a selected record (row-level delete, with confirmation).
- Double-click a row opens a detail dialog with the full calculation breakdown (all tax components, full IMEI/App ID, timestamps).

### 2.6 Settings
Editable fields, each with a "Reset to default" affordance:
- Customs Duty % (default 5%)
- Commercial Tax % (default 5%)
- Redemption Fee % (default 25%)
- Income Tax % (default 2%) + enable/disable toggle (disabled by default)
- "Reset all to defaults" button

## 3. Calculation Logic

Let `P` = Base Price (MMK). All monetary results are `Decimal`, rounded with `ROUND_HALF_UP` to the nearest whole MMK — **never** Python's default banker's rounding, and never `round()`.

```
customs_duty    = P * customs_duty_rate        # default 5%
commercial_tax  = (P + customs_duty) * commercial_tax_rate   # default 5%
redemption_fee  = P * redemption_fee_rate      # default 25%
income_tax      = P * income_tax_rate  if income_tax_enabled else 0   # default 2%, off by default
total_tax       = customs_duty + commercial_tax + redemption_fee + income_tax
grand_total     = P + total_tax
```

At default rates (5% / 5% / 25%, income tax off), this collapses to the documented identity `total_tax = P * 35.25%`, because:
`5% + (1.05 * 5%) + 25% = 5% + 5.25% + 25% = 35.25%`.

Each intermediate amount (`customs_duty`, `commercial_tax`, `redemption_fee`, `income_tax`) is independently rounded half-up to the whole MMK before being summed, so `total_tax` is the sum of already-rounded components (this is what reproduces the worked examples exactly).

### Worked examples (must pass as unit tests)

| Base Price (P) | Customs Duty (5%) | Commercial Tax (5%) | Redemption Fee (25%) | Total Tax |
|---|---|---|---|---|
| 1,995,000 MMK | 99,750 MMK | 104,738 MMK | 498,750 MMK | 703,238 MMK |
| 693,000 MMK | 34,650 MMK | 36,383 MMK | 173,250 MMK | 244,283 MMK |
| 203,700 MMK | 10,185 MMK | 10,694 MMK | 50,925 MMK | 71,804 MMK |

Note: 693,000 → 244,283 and 203,700 → 71,804 also appear as `Base Price` / `Tax Price` in the attached History screenshot rows (IDs 1, 2, 12), confirming this formula and rounding behavior against real recorded data.

## 4. Data Model

`calculations` table (SQLite):

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| date_time | TEXT | display timestamp |
| check_type | TEXT | APP ID CHECK / SINGLE CHECK / BATCH CHECK / MANUAL CALCULATION |
| imei_or_app_id | TEXT | nullable |
| brand | TEXT | nullable |
| model | TEXT | nullable |
| base_price | INTEGER | MMK, whole number |
| customs_duty | INTEGER | |
| commercial_tax | INTEGER | |
| redemption_fee | INTEGER | |
| income_tax | INTEGER | nullable, 0 if disabled |
| total_tax | INTEGER | |
| taxation_status | INTEGER | boolean (0/1), nullable |
| network_status | INTEGER | boolean (0/1), nullable |
| created_at | TEXT | ISO timestamp, for "Calculations today" and sort order |

`settings` stored as key/value (or a single-row table): `customs_duty_rate`, `commercial_tax_rate`, `redemption_fee_rate`, `income_tax_rate`, `income_tax_enabled`.

## 5. Check Types

`APP ID CHECK`, `SINGLE CHECK`, `BATCH CHECK`, `MANUAL CALCULATION` — stored verbatim in `check_type`, drive both History filtering/coloring and Calculator-page validation (IMEI check types require 15 digits; App ID types allow letters/numbers/hyphens).

## 6. Validation Rules

- Base price must be > 0.
- Brand and Model are optional.
- IMEI must be exactly 15 digits when the selected check type is IMEI-based.
- Application ID may contain letters, numbers, and hyphens.
- CSV batch rows are validated per-row; invalid rows are reported with a reason and excluded from save, without blocking valid rows.

## 7. Project Structure

```
ceir_tax_calculator/
├── main.py
├── requirements.txt
├── README.md
├── app/
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   └── calculation.py
│   ├── repositories/
│   │   └── calculation_repository.py
│   ├── services/
│   │   ├── tax_service.py
│   │   ├── csv_service.py
│   │   └── export_service.py
│   ├── views/
│   │   ├── main_window.py
│   │   ├── dashboard_view.py
│   │   ├── calculator_view.py
│   │   ├── batch_view.py
│   │   ├── history_view.py
│   │   └── settings_view.py
│   └── utils/
│       ├── validators.py
│       ├── currency.py
│       └── constants.py
├── data/
│   └── app.db
└── tests/
    ├── test_tax_service.py
    └── test_validators.py
```

Architecture rules: business logic (`tax_service`, `csv_service`, `export_service`) is fully decoupled from CustomTkinter views; `calculation_repository` is the only module touching SQLite, using parameterized queries; no global mutable state; type hints and dataclasses throughout; logging + exception handling around DB/CSV/IO; CSV import/export and any batch calculation run off the UI thread so the window never freezes.

## 8. Testing

Unit tests cover: the three worked examples above (exact MMK match), half-up rounding behavior vs. banker's rounding, invalid base price (<= 0) rejection, IMEI validation (15-digit rule), and CSV row validation (missing/invalid fields).

## 9. Packaging

- Run: `pip install -r requirements.txt` then `python main.py`.
- Package with PyInstaller; provide the one-line Windows `.exe` build command in README.
- When packaged, the SQLite DB is created in a writable OS-appropriate app-data directory (not next to a read-only installed binary) rather than the bundled `data/` folder.

---
This spec is the build target for `main.py` + `app/` per Section 7. Next step: implement per this spec, generating complete working source files (no pseudocode).
