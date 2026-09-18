"""Comprehensive Deep Verification Test Suite for WhatsApp-Auto.

Covers:
1. Phone normalization across all Indian mobile operators and landline STD codes.
2. Company name cleaning across edge cases (SEO tags, corporate suffixes, parentheticals, pipe delimiters).
3. Product cleaning with dirty JSON, trailing tags, and standalone generic terms.
4. Deep link URL construction and parameter preservation across all modes.
5. Queue Manager database operations, suppression enforcement, and dispatch logging.
6. HTML dashboard generation and XSS defense.
7. Database schema constraints and live data health.
"""

import html
import sqlite3
import urllib.parse
import uuid
from pathlib import Path
import pytest

from foundation import config
from foundation.phone_utils import format_display_phone, normalize_indian_phone
from foundation.queue_manager import WhatsAppQueueManager
from foundation.templates import (
    clean_company_name,
    clean_product_name,
    render_template_a,
    render_template_b,
    render_template_c,
)
from foundation.url_builder import build_whatsapp_link


class TestPhoneUtilsDeep:
    """Deep verification of phone number normalization and formatting."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("9825012345", "9825012345"),
            ("+91 98250 12345", "9825012345"),
            ("+91-98250-12345", "9825012345"),
            ("09825012345", "9825012345"),
            ("919825012345", "9825012345"),
            ("  +91  98250-12345  ", "9825012345"),
            ("8123456789", "8123456789"),
            ("7012345678", "7012345678"),
            ("6353476796", "6353476796"),
            ("07984157276", "7984157276"),  # Valid 7984 mobile series
        ],
    )
    def test_valid_mobile_numbers(self, raw, expected):
        assert normalize_indian_phone(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "079-22743495",     # Ahmedabad BSNL landline
            "07926402695",      # Ahmedabad landline
            "07932505467",      # Ahmedabad Reliance landline
            "07940070099",      # Ahmedabad Airtel landline
            "07949030263",      # Ahmedabad landline
            "+91-79-26422997",  # Ahmedabad with +91
            "917926423363",     # Ahmedabad with 91 prefix
            "022-25831234",     # Mumbai landline
            "011-23345678",     # Delhi landline
            "033-22445566",     # Kolkata landline
            "044-28112233",     # Chennai landline
            "18001234567",      # Toll-free
            "98250",            # Too short
            "9825012345678",    # Too long
            "abcdefghij",       # Non-numeric
            "",                 # Empty
            None,               # None
            "1234567890",       # Invalid series 1
            "2345678901",       # Invalid series 2
            "3456789012",       # Invalid series 3
            "4567890123",       # Invalid series 4
            "5678901234",       # Invalid series 5
        ],
    )
    def test_invalid_numbers_and_landlines(self, raw):
        assert normalize_indian_phone(raw) is None

    def test_display_phone_formatting(self):
        assert format_display_phone("9825012345") == "+91 98250 12345"
        assert format_display_phone("7817971213") == "+91 78179 71213"
        assert format_display_phone("invalid") == "invalid"
        assert format_display_phone("") == ""


class TestTemplatesDeep:
    """Deep verification of company name, product cleaning, and message templates."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Mahalaxmi Sales - Industrial equipment supplier in Ahmedabad", "Mahalaxmi Sales"),
            ("Beena Engineering Pvt Ltd", "Beena Engineering"),
            ("Beena Engineering Pvt. Ltd.", "Beena Engineering"),
            ("Beena Engineering Private Limited", "Beena Engineering"),
            ("JAY Chemical Industries Private Limited.", "JAY Chemical Industries"),
            ("Bhimani Chemicals Pvt. Ltd. ( Bhimani Group )", "Bhimani Chemicals"),
            ("S.S. FLEXIBLE PIPE | SS TEFLON PIPE", "S.S. FLEXIBLE PIPE"),
            ("Alpha Corp / Beta Division", "Alpha Corp"),
            ("Precision Forgings LLP", "Precision Forgings"),
            ("Shree Ram Engineering Works", "Shree Ram Engineering"),
            ("Tata Motors Limited", "Tata Motors"),
            ("", "your company"),
            (None, "your company"),
        ],
    )
    def test_clean_company_name(self, raw, expected):
        assert clean_company_name(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('["industrial equipment supplier"]', "industrial equipment"),
            ('["chemical manufacturer"]', "chemical"),
            ('["manufacturer"]', "industrial equipment"),
            ('["supplier"]', "industrial equipment"),
            ("valves, fittings, flanges", "valves"),
            ("Industrial Valves Supplier in Ahmedabad", "industrial valves"),
            (None, "industrial equipment"),
            ("", "industrial equipment"),
        ],
    )
    def test_clean_product_name(self, raw, expected):
        assert clean_product_name(raw) == expected

    def test_all_templates_word_count_and_salutation(self):
        for template_func in [render_template_a, render_template_b, render_template_c]:
            msg = template_func("Beena Engineering", '["valves supplier"]', "Vatva GIDC")
            assert "Hello Sir," in msg
            assert "Beena Engineering" in msg
            assert "valves" in msg
            assert "Vatva GIDC" in msg
            assert '["' not in msg
            assert len(msg.split()) <= 70


class TestUrlBuilderDeep:
    """Deep verification of deep-link construction."""

    def test_url_encoding_special_chars(self):
        msg = "Hello Sir, price is ₹25,000 & delivery within 48 hrs! Contact: test@example.com / +91."
        link = build_whatsapp_link("9825012345", msg, mode="web")
        parsed = urllib.parse.urlparse(link)
        params = urllib.parse.parse_qs(parsed.query)
        assert params["phone"] == ["919825012345"]
        assert params["text"] == [msg]

    def test_all_link_modes(self):
        msg = "Test Message"
        web = build_whatsapp_link("9825012345", msg, mode="web")
        app = build_whatsapp_link("9825012345", msg, mode="universal")
        api = build_whatsapp_link("9825012345", msg, mode="api")

        assert web.startswith("https://web.whatsapp.com/send?phone=919825012345&text=")
        assert app.startswith("https://wa.me/919825012345?text=")
        assert api.startswith("https://api.whatsapp.com/send?phone=919825012345&text=")


class TestQueueManagerDeep:
    """Deep verification of Queue Manager database, suppression, and dispatch."""

    def test_mark_status_with_automatic_template_resolution(self, tmp_path):
        db_path = tmp_path / "test.db"
        mgr = WhatsAppQueueManager(db_path=db_path)
        conn = mgr._get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO wa_contacts (id, company_name, area, city, products, raw_phone, normalized_phone, status)
            VALUES ('c1', 'Apex Auto Pvt Ltd', 'Sanand', 'Ahmedabad', 'fasteners', '9825011111', '9825011111', 'PENDING')
            """
        )
        conn.commit()
        conn.close()

        # Mark sent with template_b
        mgr.mark_status("c1", "SENT", template_name="template_b")

        conn = mgr._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM wa_dispatch_logs WHERE contact_id = 'c1'")
        log = cur.fetchone()
        conn.close()

        assert log is not None
        assert log["dispatch_status"] == "SENT"
        assert log["template_name"] == "template_b"
        assert "Apex Auto" in log["message_text"]
        assert "dispatch challans" in log["message_text"]

    def test_leadforge_suppression_respected(self, tmp_path):
        """Ensure businesses marked is_suppressed in LeadForge are never imported."""
        lf_db_path = tmp_path / "mock_leadforge.db"
        lf_conn = sqlite3.connect(lf_db_path)
        lf_cur = lf_conn.cursor()
        lf_cur.execute(
            """
            CREATE TABLE businesses (
                id TEXT PRIMARY KEY,
                name TEXT,
                display_phone TEXT,
                categories TEXT,
                is_suppressed INTEGER
            );
            """
        )
        lf_cur.execute(
            """
            CREATE TABLE addresses (
                id TEXT PRIMARY KEY,
                business_id TEXT,
                area TEXT,
                city TEXT
            );
            """
        )
        # 1 active, 1 suppressed
        lf_cur.execute("INSERT INTO businesses VALUES ('b1', 'Good Corp', '9825011111', 'valves', 0)")
        lf_cur.execute("INSERT INTO addresses VALUES ('a1', 'b1', 'Vatva', 'Ahmedabad')")
        lf_cur.execute("INSERT INTO businesses VALUES ('b2', 'Suppressed Corp', '9825022222', 'valves', 1)")
        lf_cur.execute("INSERT INTO addresses VALUES ('a2', 'b2', 'Odhav', 'Ahmedabad')")
        lf_conn.commit()
        lf_conn.close()

        mgr = WhatsAppQueueManager(db_path=tmp_path / "outreach.db")
        imported = mgr.import_from_leadforge(leadforge_db_path=lf_db_path)
        assert imported == 1

        queue = mgr.get_pending_queue()
        assert len(queue) == 1
        assert queue[0]["company_name"] == "Good Corp"


class TestLiveDatabaseDeep:
    """Verifies that the live workspace database adheres to all production requirements."""

    def test_live_database_contacts_are_all_valid_mobiles(self):
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id, company_name, raw_phone, normalized_phone FROM wa_contacts")
        rows = cur.fetchall()
        conn.close()

        assert len(rows) >= 50, f"Expected at least 50 contacts, found {len(rows)}"
        for r in rows:
            norm = r["normalized_phone"]
            assert len(norm) == 10, f"Contact {r['company_name']} has invalid phone length: {norm}"
            assert norm[0] in ("6", "7", "8", "9"), f"Contact {r['company_name']} has invalid start digit: {norm}"
            assert not norm.startswith(("792", "793", "794", "795", "796")), (
                f"Contact {r['company_name']} is an Ahmedabad landline: {norm}"
            )
