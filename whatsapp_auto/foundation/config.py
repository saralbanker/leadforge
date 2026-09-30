"""Configuration for WhatsApp-Auto Solo Outreach Engine."""

import os
import sqlite3
from pathlib import Path
from typing import Dict, Optional

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "whatsapp_outreach.db"
SCHEMA_PATH = ROOT_DIR / "foundation" / "schema.sql"
LEADFORGE_DB_PATH = Path(
    os.environ.get("LEADFORGE_DB_PATH") or (ROOT_DIR.parent / "leadforge.db")
)

# Operational Limits
DAILY_SEND_LIMIT = 25  # Recommended 20-30 for zero ban risk
DEFAULT_CITY = "Ahmedabad"
DEFAULT_AREA = "Vatva GIDC"
DEFAULT_PRODUCTS = "machinery & equipment"

# Operator Info
OPERATOR_NAME = "Saral Banker"
OPERATOR_COMPANY = "Orvion"
OPERATOR_LOCATION = "Ahmedabad (Ellisbridge)"


class SettingsCache:
    """Loads WhatsApp-Auto settings once from its own SQLite database.

    This intentionally does not read LeadForge's settings table.  Keeping the
    cache local lets the two outreach channels be configured independently.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._data: Dict[str, str] = {}
        try:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute("SELECT key, value FROM wa_settings").fetchall()
                self._data = {key: value for key, value in rows}
            finally:
                conn.close()
        except sqlite3.Error:
            # A freshly-created or pre-migration database should still be able
            # to use the deterministic fallback without configuration.
            pass

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def get_str(self, key: str, default: str) -> str:
        return self._data.get(key, default)

    def get_int(self, key: str, default: int) -> int:
        try:
            return int(self._data.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float) -> float:
        try:
            return float(self._data.get(key, default))
        except (TypeError, ValueError):
            return default
