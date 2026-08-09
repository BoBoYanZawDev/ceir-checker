@echo off
setlocal
cd /d "%~dp0"

echo ==================================================
echo   Building CEIR Checker for Windows
echo ==================================================

py -3.12 -m venv .venv-build
if errorlevel 1 goto :python_error

call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :build_error

python -m pip install -r requirements-dev.txt
if errorlevel 1 goto :build_error

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onefile ^
  --name "CEIR Checker" ^
  --collect-all customtkinter ^
  --collect-all pywebview ^
  main.py
if errorlevel 1 goto :build_error

echo.
echo Build complete:
echo %CD%\dist\CEIR Checker.exe
echo.
pause
exit /b 0

:python_error
echo.
echo Python 3.12 was not found. Install it from https://www.python.org/downloads/windows/
echo During installation, enable "Add Python to PATH".
echo.
pause
exit /b 1

:build_error
echo.
echo Build failed. Review the error messages above.
echo.
pause
exit /b 1
