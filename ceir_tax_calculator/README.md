# CEIR Mobile Tax Calculator

A focused Windows/macOS desktop app for checking a single IMEI with Myanmar CEIR and calculating CEIR mobile customs tax. It intentionally excludes the old app's ADB and IMEI-changing automation.

## Features

- Official CEIR multi-IMEI workflow with one fresh ALTCHA token per verification batch (the UI stays responsive)
- Exact `Decimal`/`ROUND_HALF_UP` tax calculation
- Automatic recalculation while the base price is entered
- Automatic CEIR GSMA lookup for manufacturer, brand, model, device type, OS, TAC, and supported IMEI count
- IMEI input accepts comma-separated values, new-line-separated values, or both
- APP ID CHECK tab using CEIR RegistrationStatus, including official base price, tax components, total tax, device, and payment status
- Editable customs, commercial, redemption, and optional income-tax rates
- SQLite history with live search, type filtering, pagination, details, deletion, and filtered CSV export
- Responsive CustomTkinter interface with light/dark mode
- Writable per-user database location on Windows, macOS, and Linux

The CEIR service is an external government system. An internet connection is required for checks, and temporary CEIR/Cloudflare errors are shown in the result table. The CEIR IMEI response does not supply a phone price or tax amount, so an unpaid IMEI check leaves Tax Price empty instead of showing an estimate. Official amounts are displayed when an App ID is checked or after the user explicitly submits a CEIR tax registration with completed Applicant Details. Tax calculation and history remain fully local.

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

### Windows one-click build

Copy the project to a Windows computer with Python 3.12 installed, then double-click:

```text
build_windows.bat
```

The executable and its required runtime files will be created at:

```text
dist\CEIR Mobile Tax Calculator.exe
```

This is a single-file Windows executable.

Equivalent manual command:

```powershell
pyinstaller --noconfirm --clean --windowed --onefile --name "CEIR Mobile Tax Calculator" --collect-all customtkinter --collect-all pywebview main.py
```

### Build without a Windows computer

The manual GitHub Actions workflow at `.github/workflows/build-windows.yml` builds on an official Windows runner. Push this directory to a GitHub repository, open **Actions → Build Windows EXE → Run workflow**, then download the `CEIR-Mobile-Tax-Calculator-Windows` artifact.

Build a macOS `.app` from a Mac:

```bash
pyinstaller --noconfirm --clean --windowed --name "CEIR Mobile Tax Calculator" --collect-all customtkinter --collect-all pywebview main.py
```

Packaged output is placed in `dist/`. The SQLite database is not stored beside the executable; it is created under the current user's application-data directory.

The repository-root workflow `.github/workflows/build-ceir-tax-calculator-macos.yml`
builds native Intel and Apple Silicon versions. Download
`CEIR-Tax-Calculator-macOS-Intel` for Intel Macs or
`CEIR-Tax-Calculator-macOS-Apple-Silicon` for M-series Macs.

## Data location

- Windows: `%LOCALAPPDATA%\CEIRMobileTaxCalculator\app.db`
- macOS: `~/Library/Application Support/CEIRMobileTaxCalculator/app.db`
- Linux: `$XDG_DATA_HOME/CEIRMobileTaxCalculator/app.db` or `~/.local/share/...`

For testing, set `CEIR_TAX_DB` to override the database path.
