"""Tests for dispatch_queue.html structure, safety, and functionality."""

from pathlib import Path
import re
import pytest
from foundation import config
from foundation.queue_manager import WhatsAppQueueManager


class TestHtmlDashboard:
    """Test suite for the generated HTML dispatch queue dashboard."""

    def test_html_file_exists(self):
        html_path = config.ROOT_DIR / "dispatch_queue.html"
        assert html_path.exists(), "dispatch_queue.html does not exist in root directory"

    def test_html_contains_required_elements(self):
        html_path = config.ROOT_DIR / "dispatch_queue.html"
        content = html_path.read_text(encoding="utf-8")
        assert "⚡ WhatsApp-Auto Dispatch Queue" in content
        assert "card" in content
        assert "web.whatsapp.com/send" in content
        assert "markSent" in content
        assert "markSkip" in content

    def test_html_escaping_in_cards(self, tmp_path):
        """Verify that company names with HTML special characters (&, <, >) are safely escaped."""
        db_path = tmp_path / "xss_test.db"
        mgr = WhatsAppQueueManager(db_path=db_path)
        conn = mgr._get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO wa_contacts (id, company_name, area, city, products, raw_phone, normalized_phone, status)
            VALUES ('x1', '<script>alert(1)</script> & Sons', 'Vatva & Odhav', 'Ahmedabad', 'valves & pumps', '9825012345', '9825012345', 'PENDING')
            """
        )
        conn.commit()
        conn.close()

        out_html = tmp_path / "test_escape.html"
        mgr.generate_html_queue(output_path=out_html, limit=5)
        content = out_html.read_text(encoding="utf-8")

        # Must not contain raw unescaped script tag inside HTML body
        assert "<script>alert(1)</script>" not in content, "Unescaped HTML/XSS tag found in generated dashboard"
        assert "&amp;" in content or "&lt;script&gt;" in content, "Special characters were not HTML escaped"
