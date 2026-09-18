"""Configuration for WhatsApp-Auto Solo Outreach Engine."""

import os
from pathlib import Path

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
