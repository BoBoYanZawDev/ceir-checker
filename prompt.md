old code is this

i want this ui flow

and add calculate logic =

Create a complete desktop Python application for calculating Myanmar CEIR mobile phone customs tax. Technology:



* Python 3.12+

* CustomTkinter for the user interface

* SQLite for local database storage

* Use a clean service/repository architecture

* The project must run on Windows and macOS

* Provide requirements.txt and README.md Application name: CEIR Mobile Tax Calculator Main Calculation Formula: Let Base Price = P



1. Customs Duty: customs_duty = P × 5%

2. Commercial Tax: commercial_tax = (P + customs_duty) × 5%

3. Redemption Fee: redemption_fee = P × 25%

4. Total Tax: total_tax = customs_duty + commercial_tax + redemption_fee Effective tax rate: total_tax = P × 35.25% Examples: Example 1: Base Price = 1,995,000 MMK Customs Duty = 99,750 MMK Commercial Tax = 104,738 MMK Redemption Fee = 498,750 MMK Total Tax = 703,238 MMK Example 2: Base Price = 693,000 MMK Customs Duty = 34,650 MMK Commercial Tax = 36,383 MMK Redemption Fee = 173,250 MMK Total Tax = 244,283 MMK Example 3: Base Price = 203,700 MMK Customs Duty = 10,185 MMK Commercial Tax = 10,694 MMK Redemption Fee = 50,925 MMK Total Tax = 71,804 MMK Use standard half-up rounding to the nearest whole MMK. Do not use Python's default banker's rounding. Use Decimal with ROUND_HALF_UP. Core Features:

5. Tax Calculator



* Input brand

* Input model

* Input IMEI or Application ID

* Input base price in MMK

* Numeric input validation

* Automatically format numbers with commas

* Calculate button

* Reset button

* Copy result button

* Save calculation button



2. Calculation Result Display:



* Base Price

* Customs Duty 5%

* Commercial Tax 5%

* Redemption Fee 25%

* Total Tax

* Effective Tax Rate 35.25%

* Grand Total including phone value: grand_total = base_price + total_tax



3. Editable Tax Settings Create a settings screen where the user can modify:



* Customs Duty percentage

* Commercial Tax percentage

* Redemption Fee percentage

* Optional Income Tax percentage

* Enable or disable Income Tax

* Reset rates to defaults Default values:

* Customs Duty: 5%

* Commercial Tax: 5%

* Redemption Fee: 25%

* Income Tax: 2%, disabled by default When Income Tax is enabled:

* Calculate income tax based on the base price

* Add it to the total tax

* Show it as a separate result row



4. Calculation History Store each calculation in SQLite with:



* ID

* Date and time

* Check type

* IMEI or Application ID

* Brand

* Model

* Base price

* Customs duty

* Commercial tax

* Redemption fee

* Income tax

* Total tax

* Taxation status

* Network status

* Created timestamp



5. History Screen Create a table similar to a database history viewer with columns:



* ID

* Date Time

* Type

* IMEI / App ID

* Brand / Model

* Taxation

* Network

* Base Price

* Tax Price Include:

* Search by IMEI, Application ID, brand, model or date

* Filter by check type

* Pagination

* Previous and Next buttons

* Total records count

* Delete selected record

* Clear all history with confirmation

* Export filtered records to CSV

* Double-click a row to view full calculation details



6. Check Types Support:



* APP ID CHECK

* SINGLE CHECK

* BATCH CHECK

* MANUAL CALCULATION



7. Batch Calculation



* Import a CSV file

* CSV columns: imei_or_app_id, brand, model, base_price, taxation_status, network_status

* Validate every row

* Calculate tax for valid rows

* Show success and failed row counts

* Display validation errors

* Save valid calculations to history

* Export results to CSV



8. Dashboard Show summary cards:



* Total calculations

* Total base price

* Total tax amount

* Average tax amount

* Calculations today



9. UI Requirements



* Modern professional desktop UI

* Sidebar navigation

* Pages: Dashboard Calculator Batch Calculator History Settings

* Light and dark mode

* Responsive resizing

* Blue application theme

* Clear typography

* Currency values displayed as: 1,995,000 MMK

* Success and error dialogs
* Confirmation dialogs before destructive actions

* Do not freeze the UI during CSV import/export



10. Validation



* Base price must be greater than zero

* Brand and model are optional

* IMEI must contain 15 digits when the selected type is an IMEI check

* Application ID can contain letters, numbers and hyphens

* Reject invalid CSV values

* Show user-friendly error messages



11. Project Structure Use a structure similar to: ceir_tax_calculator/ ├── main.py ├── requirements.txt ├── README.md ├── app/ │ ├── config.py │ ├── database.py │ ├── models/ │ │ └── calculation.py │ ├── repositories/ │ │ └── calculation_repository.py │ ├── services/ │ │ ├── tax_service.py │ │ ├── csv_service.py │ │ └── export_service.py │ ├── views/ │ │ ├── main_window.py │ │ ├── dashboard_view.py │ │ ├── calculator_view.py │ │ ├── batch_view.py │ │ ├── history_view.py │ │ └── settings_view.py │ └── utils/ │ ├── validators.py │ ├── currency.py │ └── constants.py ├── data/ │ └── app.db └── tests/ ├── test_tax_service.py └── test_validators.py

12. Code Quality



* Use type hints

* Use dataclasses where appropriate

* Follow PEP 8

* Separate business logic from UI logic

* Add exception handling

* Add logging

* Use parameterized SQLite queries

* Avoid global mutable state

* Add comments only where necessary

* Write reusable components



13. Testing Add unit tests for:



* 1,995,000 MMK producing 703,238 MMK tax

* 693,000 MMK producing 244,283 MMK tax

* 203,700 MMK producing 71,804 MMK tax

* Half-up rounding

* Invalid base prices

* IMEI validation

* CSV row validation



14. Packaging



* Add instructions for running the app

* Add PyInstaller packaging instructions

* Provide commands for creating a Windows .exe

* Store the SQLite database in a writable application-data directory when packaged Generate all source files with complete working code. Do not provide pseudocode or omit important sections. Ensure the application starts successfully by running: pip install -r requirements.txt python main.py


create a project spect and write it down to SEPC.md