from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS calculations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_time TEXT NOT NULL,
    check_type TEXT NOT NULL,
    imei_or_app_id TEXT,
    brand TEXT,
    model TEXT,
    base_price INTEGER,
    customs_duty INTEGER,
    commercial_tax INTEGER,
    redemption_fee INTEGER,
    income_tax INTEGER DEFAULT 0,
    total_tax INTEGER,
    taxation_status INTEGER,
    network_status INTEGER,
    check_message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calculations_created_at ON calculations(created_at DESC);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection
