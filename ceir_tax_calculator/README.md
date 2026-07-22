# CEIR Mobile Tax Calculator

A focused Windows/macOS desktop app for checking a single IMEI with Myanmar CEIR and calculating CEIR mobile customs tax. It intentionally excludes the old app's ADB and IMEI-changing automation.

## Features

- Official CEIR multi-IMEI workflow with one background API request per IMEI (the UI stays responsive)
- Exact `Decimal`/`ROUND_HALF_UP` tax calculation
- Automatic recalculation while the base price is entered
- Automatic CEIR GSMA lookup for manufacturer, brand, model, device type, OS, TAC, and supported IMEI count
- IMEI input accepts comma-separated values, new-line-separated values, or both
- APP ID CHECK tab using CEIR RegistrationStatus, including official base price, tax components, total tax, device, and payment status
- Editable customs, commercial, redemption, and optional income-tax rates
- SQLite history with live search, type filtering, pagination, details, deletion, and filtered CSV export
- Responsive CustomTkinter interface with light/dark mode
- Writable per-user database location on Windows, macOS, and Linux

The CEIR service is an external government system. An internet connection is required for checks, and temporary CEIR/Cloudflare errors are shown in the result table. The CEIR IMEI response does not supply a phone price, so enter Base Price on the Check screen when tax should be calculated together with the result. Tax calculation and history remain fully local.

## Run from source

Python 3.12 or newer is recommended.

```bash
cd ceir_tax_calculator
python -m venv .venv
```

Activate the environment:

```bash
# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install and run:

```bash
python -m pip install -r requirements.txt
python main.py
```

Only the runtime UI dependency is installed by `requirements.txt`. To run tests or build a packaged application, install the development tools separately:

```bash
python -m pip install -r requirements-dev.txt
```

## Tax formula

At the default rates:

```text
customs duty   = base price × 5%
commercial tax = (base price + rounded customs duty) × 5%
redemption fee = base price × 25%
total tax      = rounded customs + rounded commercial + rounded redemption
```

Every component is independently rounded half-up to a whole MMK before summing. Income tax is 2% of base price and disabled by default.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Package

Build a Windows `.exe` from a Windows machine:

```powershell
pyinstaller --noconfirm --clean --windowed --name "CEIR Mobile Tax Calculator" --collect-all customtkinter main.py
```

Build a macOS `.app` from a Mac:

```bash
pyinstaller --noconfirm --clean --windowed --name "CEIR Mobile Tax Calculator" --collect-all customtkinter main.py
```

Packaged output is placed in `dist/`. The SQLite database is not stored beside the executable; it is created under the current user's application-data directory.

## Data location

- Windows: `%LOCALAPPDATA%\CEIRMobileTaxCalculator\app.db`
- macOS: `~/Library/Application Support/CEIRMobileTaxCalculator/app.db`
- Linux: `$XDG_DATA_HOME/CEIRMobileTaxCalculator/app.db` or `~/.local/share/...`

For testing, set `CEIR_TAX_DB` to override the database path.
