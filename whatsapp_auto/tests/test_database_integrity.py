"""Tests for database integrity and data quality of whatsapp_outreach.db."""

import sqlite3
from pathlib import Path
import pytest
from foundation import config
from foundation.phone_utils import normalize_indian_phone


class TestDatabaseIntegrity:
    """Test suite inspecting the live whatsapp_outreach.db."""

    def test_database_connection(self):
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        assert row[0] == "ok", f"SQLite integrity check failed: {row[0]}"
        conn.close()

    def test_schema_tables_exist(self):
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        assert "wa_contacts" in tables
        assert "wa_dispatch_logs" in tables
        conn.close()

    def test_unique_normalized_phone_constraint(self):
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT normalized_phone, COUNT(*)
            FROM wa_contacts
            GROUP BY normalized_phone
            HAVING COUNT(*) > 1
            """
        )
        duplicates = cur.fetchall()
        assert len(duplicates) == 0, f"Found duplicate normalized phones in database: {duplicates}"
        conn.close()

    def test_no_landlines_in_contacts_database(self):
        """Critical verification: Contacts in wa_contacts must be genuine mobile numbers, not landlines."""
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT company_name, raw_phone, normalized_phone FROM wa_contacts")
        contacts = cur.fetchall()
        conn.close()

        # In Ahmedabad, landlines start with STD code 079 followed by 2, 3, 4, 5, 6
        landlines_found = []
        for c in contacts:
            norm = c["normalized_phone"]
            raw = c["raw_phone"]
            # Check if raw phone starts with 079 followed by 2, 3, 4, 5, 6 (Ahmedabad telecom landline)
            # or if normalized phone starts with 792, 793, 794, 795, 796
            if norm.startswith(("792", "793", "794", "795", "796")):
                landlines_found.append((c["company_name"], raw, norm))

        assert len(landlines_found) == 0, (
            f"Found {len(landlines_found)} landlines in wa_contacts table that will fail on WhatsApp: {landlines_found}"
        )
