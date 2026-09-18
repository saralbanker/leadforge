"""Tests for foundation/queue_manager.py."""

import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest
from foundation.queue_manager import WhatsAppQueueManager


@pytest.fixture
def temp_manager(tmp_path):
    """Creates a WhatsAppQueueManager instance with an isolated database."""
    db_path = tmp_path / "test_outreach.db"
    mgr = WhatsAppQueueManager(db_path=db_path)
    return mgr


class TestQueueManager:
    """Test suite for WhatsAppQueueManager."""

    def test_db_initialization(self, temp_manager):
        """Tables and indexes are properly created."""
        conn = temp_manager._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        assert "wa_contacts" in tables
        assert "wa_dispatch_logs" in tables
        conn.close()

    def test_import_and_pending_queue(self, temp_manager, tmp_path):
        """Test inserting contacts and querying pending queue."""
        conn = temp_manager._get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO wa_contacts (id, company_name, area, city, products, raw_phone, normalized_phone, status)
            VALUES ('c1', 'Test Corp', 'Vatva', 'Ahmedabad', 'valves', '9825012345', '9825012345', 'PENDING'),
                   ('c2', 'Demo Ltd', 'Odhav', 'Ahmedabad', 'pumps', '9825099999', '9825099999', 'PENDING')
            """
        )
        conn.commit()
        conn.close()

        pending = temp_manager.get_pending_queue(limit=1)
        assert len(pending) == 1
        assert pending[0]["company_name"] == "Test Corp"

        pending_all = temp_manager.get_pending_queue(limit=10)
        assert len(pending_all) == 2

    def test_mark_status_and_dispatch_log(self, temp_manager):
        """Test status update and verify message logging."""
        conn = temp_manager._get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO wa_contacts (id, company_name, area, city, products, raw_phone, normalized_phone, status)
            VALUES ('c1', 'Test Corp', 'Vatva', 'Ahmedabad', 'valves', '9825012345', '9825012345', 'PENDING')
            """
        )
        conn.commit()
        conn.close()

        temp_manager.mark_status("c1", "SENT", notes="First send", template_name="template_a")

        conn = temp_manager._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, notes FROM wa_contacts WHERE id = 'c1'")
        contact = cur.fetchone()
        assert contact["status"] == "SENT"
        assert contact["notes"] == "First send"

        cur.execute("SELECT * FROM wa_dispatch_logs WHERE contact_id = 'c1'")
        log = cur.fetchone()
        assert log is not None
        assert log["dispatch_status"] == "SENT"
        # Verify message text logged - does it record the actual message or empty string?
        assert log["message_text"] != "", "Dispatch log should record the message text dispatched, not empty string"
        conn.close()

    def test_generate_html_queue(self, temp_manager, tmp_path):
        """Test HTML queue generation."""
        conn = temp_manager._get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO wa_contacts (id, company_name, area, city, products, raw_phone, normalized_phone, status)
            VALUES ('c1', 'Test & Co <Pvt> Ltd', 'Vatva', 'Ahmedabad', 'valves', '9825012345', '9825012345', 'PENDING')
            """
        )
        conn.commit()
        conn.close()

        out_html = tmp_path / "test_queue.html"
        generated = temp_manager.generate_html_queue(output_path=out_html, limit=10)
        assert generated.exists()
        content = generated.read_text(encoding="utf-8")
        assert "⚡ WhatsApp-Auto Dispatch Queue" in content
        assert "web.whatsapp.com/send" in content


class TestCliInterface:
    """Test suite for CLI command-line argument handling."""

    def test_runbook_documented_flag(self):
        """Verify the CLI flag documented in docs/OPERATOR_RUNBOOK.md (--daily-limit 25) works."""
        # The runbook explicitly tells the operator:
        # python3 -m foundation.queue_manager --daily-limit 25
        result = subprocess.run(
            [sys.executable, "-m", "foundation.queue_manager", "--daily-limit", "5"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0 or "unrecognized arguments: --daily-limit" not in result.stderr, (
            f"Runbook-documented flag '--daily-limit' failed: {result.stderr}"
        )
