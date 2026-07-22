from __future__ import annotations

import os
import sys
from pathlib import Path


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    location = root / "CEIRMobileTaxCalculator"
    location.mkdir(parents=True, exist_ok=True)
    return location


def database_path() -> Path:
    override = os.environ.get("CEIR_TAX_DB")
    return Path(override) if override else app_data_dir() / "app.db"
