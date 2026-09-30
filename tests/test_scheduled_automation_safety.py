"""Tests for scheduled outreach safety controls:
1. Per-run send cap enforcement at dispatch time.
2. Content validation circuit breaker (trip, halt, clear).
3. Physical postal address CAN-SPAM compliance validation.
"""

import os
import sqlite3
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import leadforge.database
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()

from leadforge.database import initialize_database, get_db_connection, uuidv7
from leadforge.outreach.compliance import validate_postal_address
from leadforge.outreach.circuit_breaker import (
    validate_draft_content,
    trip_content_circuit_breaker,
    clear_content_circuit_breaker,
    is_content_circuit_breaker_tripped,
)
from leadforge.outreach.deliverer import SMTPEmailDeliverer


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown():
    mp = pytest.MonkeyPatch()
    mp.setattr(leadforge.database, "DB_PATH", temp_db_path)
    initialize_database()
    yield
    mp.undo()
    if temp_db_path.exists():
        try:
            os.remove(temp_db_path)
        except Exception:
            pass


@pytest.fixture
def smtp_env():
    """Mock SMTP configuration environment."""
    with patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "testuser",
        "SMTP_PASSWORD": "testpass",
        "SMTP_FROM_EMAIL": "outreach@orvion.com",
        "SMTP_FROM_NAME": "Orvion",
        "SMTP_USE_TLS": "True",
    }), patch("leadforge.outreach.deliverer.SMTP_CONFIGURED", True), \
         patch("leadforge.outreach.deliverer.SMTP_HOST", "smtp.example.com"), \
         patch("leadforge.outreach.deliverer.SMTP_PORT", 587), \
         patch("leadforge.outreach.deliverer.SMTP_USERNAME", "testuser"), \
         patch("leadforge.outreach.deliverer.SMTP_PASSWORD", "testpass"), \
         patch("leadforge.outreach.deliverer.SMTP_FROM_EMAIL", "outreach@orvion.com"), \
         patch("leadforge.outreach.deliverer.SMTP_FROM_NAME", "Orvion"), \
         patch("leadforge.outreach.deliverer.SMTP_USE_TLS", True):
        yield


# --- 1. Compliance: Postal Address Validation ---

def test_postal_address_validation_rejects_empty_or_short():
    valid, reason = validate_postal_address("")
    assert not valid
    assert "missing or empty" in reason.lower()

    valid, reason = validate_postal_address("12 Main St")
    assert not valid
    assert "too short" in reason.lower()


def test_postal_address_validation_rejects_placeholders():
    valid, reason = validate_postal_address("123 Example Road, Testville 12345")
    assert not valid
    assert "placeholder" in reason.lower()

    valid, reason = validate_postal_address("123 Fake Street, Springfield 99999")
    assert not valid
    assert "placeholder" in reason.lower()


def test_postal_address_validation_accepts_genuine_address():
    addr = "402 Silicon Square, SG Highway, Ahmedabad, Gujarat 380054, India"
    valid, reason = validate_postal_address(addr)
    assert valid
    assert "valid" in reason.lower()

    addr_us = "Suite 500, 100 Congress Ave, Austin, TX 78701, USA"
    valid_us, _ = validate_postal_address(addr_us)
    assert valid_us


# --- 2. Content Validation & Circuit Breaker ---

def test_validate_draft_content_detects_defects():
    # Defect 1: Word count under budget (25 words)
    short_body = (
        "Hi, we notice your plant in Ahmedabad.\n\n"
        "I found your textile catalog online.\n\n"
        "Would you be open to talking?"
    )
    valid, issues = validate_draft_content(
        body=short_body,
        subject="Quick question",
        city="Ahmedabad",
        has_website=True,
        scraped_text="textile machinery parts",
    )
    assert not valid
    assert any("budget" in issue.lower() or "word count" in issue.lower() for issue in issues)

    # Defect 2: Missing contact bridge
    no_bridge_body = (
        "Hi, we notice your manufacturing operations in Ahmedabad.\n\n"
        "We help industrial suppliers automate their incoming quote workflow so your sales team never loses another high-value inquiry to a slow response.\n\n"
        "Would you be open to a brief conversation this week?"
    )
    valid2, issues2 = validate_draft_content(
        body=no_bridge_body,
        subject="textile machinery parts at ABC Corp",
        city="Ahmedabad",
        has_website=True,
        scraped_text="",
    )
    # Either word count or bridge issue
    assert not valid2

    # Defect 3: Subject line > 50 chars
    valid3, issues3 = validate_draft_content(
        body=short_body,
        subject="This is an extremely long subject line that completely exceeds fifty characters limit",
        city="Ahmedabad",
        has_website=True,
    )
    assert not valid3
    assert any("subject" in issue.lower() for issue in issues3)


def test_circuit_breaker_trip_and_clear():
    conn = get_db_connection()
    clear_content_circuit_breaker(conn)

    tripped, _ = is_content_circuit_breaker_tripped(conn)
    assert not tripped

    trip_content_circuit_breaker(conn, reason="Draft body length 68 words exceeded 40-60 budget")
    tripped, reason = is_content_circuit_breaker_tripped(conn)
    assert tripped
    assert "68 words" in reason

    clear_content_circuit_breaker(conn)
    tripped, _ = is_content_circuit_breaker_tripped(conn)
    assert not tripped
    conn.close()


# --- 3. Per-Run Send Cap Enforcement at Dispatch Time ---

@patch("smtplib.SMTP")
def test_send_approved_drafts_enforces_per_run_cap(mock_smtp: MagicMock, smtp_env):
    """Proves that passing max_sends=2 strictly limits dispatch to 2 emails
    even when 5 drafts are approved and daily limit is 10."""
    mock_instance = MagicMock()
    mock_smtp.return_value = mock_instance

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM email_drafts")

    # Set daily limit to 10
    cursor.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES ('outreach.daily_send_limit', '10', datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = '10'
        """
    )
    cursor.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES ('outreach.content_breaker_tripped', 'false', datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = 'false'
        """
    )

    bt_id = uuidv7()
    business_id = uuidv7()
    opp_id = uuidv7()
    addr_id = uuidv7()
    cursor.execute("INSERT OR IGNORE INTO business_types (id, name) VALUES (?, 'Machinery')", (bt_id,))
    cursor.execute(
        "INSERT OR IGNORE INTO businesses (id, normalized_name, name, website_domain, business_type_id) "
        "VALUES (?, 'apex mfg', 'Apex Mfg', 'apex.in', ?)",
        (business_id, bt_id),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO addresses (id, business_id, city) "
        "VALUES (?, ?, 'Ahmedabad')",
        (addr_id, business_id),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO opportunities (id, business_id, title, pipeline_stage) "
        "VALUES (?, ?, 'Opp 1', 'PROSPECTING')",
        (opp_id, business_id),
    )

    # Insert 5 valid approved drafts
    # Valid body within 40-60 words with bridge and single location
    compliant_body = (
        "I noticed your precision machining operations in Ahmedabad.\n\n"
        "I came across your CNC components catalog while researching regional manufacturers. "
        "We help industrial suppliers locally automate their incoming inquiry workflow.\n\n"
        "Would you be open to a brief introductory conversation this week?\n\n"
        "---\nOrvion\nReply STOP to unsubscribe."
    )

    for i in range(1, 6):
        d_id = uuidv7()
        cursor.execute(
            """
            INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status, quality_score, quality_passed)
            VALUES (?, ?, 'Campaign A', ?, 'precision machining at Apex Mfg', ?, 'APPROVED', 100, 1)
            """,
            (d_id, opp_id, f"lead{i}@example.com", compliant_body),
        )
    conn.commit()

    # Deliver with hard per-run cap max_sends=2
    deliverer = SMTPEmailDeliverer()
    sent_count = deliverer.send_approved_drafts(max_sends=2)

    assert sent_count == 2

    cursor.execute("SELECT count(*) FROM email_drafts WHERE status = 'SENT'")
    sent_in_db = cursor.fetchone()[0]
    assert sent_in_db == 2

    cursor.execute("SELECT count(*) FROM email_drafts WHERE status = 'APPROVED'")
    remaining_approved = cursor.fetchone()[0]
    assert remaining_approved == 3

    conn.close()


@patch("smtplib.SMTP")
def test_post_send_circuit_breaker_trips_and_halts_batch(mock_smtp: MagicMock, smtp_env):
    """Proves that a defective draft dispatched with enforce_content_validation=True
    trips the content circuit breaker post-send, halts the batch immediately,
    and locks out future dispatches until cleared."""
    mock_instance = MagicMock()
    mock_smtp.return_value = mock_instance

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM email_drafts")
    clear_content_circuit_breaker(conn)

    bt_id = uuidv7()
    business_id = uuidv7()
    opp_id = uuidv7()
    addr_id = uuidv7()
    cursor.execute("INSERT OR IGNORE INTO business_types (id, name) VALUES (?, 'Machinery')", (bt_id,))
    cursor.execute(
        "INSERT OR IGNORE INTO businesses (id, normalized_name, name, website_domain, business_type_id) "
        "VALUES (?, 'apex mfg', 'Apex Mfg', 'apex.in', ?)",
        (business_id, bt_id),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO addresses (id, business_id, city) "
        "VALUES (?, ?, 'Ahmedabad')",
        (addr_id, business_id),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO opportunities (id, business_id, title, pipeline_stage) "
        "VALUES (?, ?, 'Opp 1', 'PROSPECTING')",
        (opp_id, business_id),
    )

    # Draft 1: Defective body (12 words, below 40-60 budget)
    defective_body = "Hello from Orvion. We noticed your industrial operations in Ahmedabad. Contact us today."
    d1_id = uuidv7()
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Campaign A', 'bad@example.com', 'precision machining at Apex Mfg', ?, 'APPROVED')
        """,
        (d1_id, opp_id, defective_body),
    )

    # Draft 2: Compliant body
    compliant_body = (
        "I noticed your precision machining operations in Ahmedabad.\n\n"
        "I came across your CNC components catalog while researching regional manufacturers. "
        "We help industrial suppliers locally automate their incoming inquiry workflow.\n\n"
        "Would you be open to a brief introductory conversation this week?\n\n"
        "---\nOrvion\nReply STOP to unsubscribe."
    )
    d2_id = uuidv7()
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Campaign A', 'good@example.com', 'precision machining at Apex Mfg', ?, 'APPROVED')
        """,
        (d2_id, opp_id, compliant_body),
    )
    conn.commit()

    deliverer = SMTPEmailDeliverer()
    # Dispatch with enforce_content_validation=True
    sent_count = deliverer.send_approved_drafts(max_sends=5, enforce_content_validation=True)

    # Only 1 email was sent before the breaker tripped and halted the batch
    assert sent_count == 1

    # Verify breaker is TRIPPED in DB
    tripped, reason = is_content_circuit_breaker_tripped(conn)
    assert tripped
    assert "budget" in reason.lower() or "word count" in reason.lower()

    # Verify draft 2 was NOT sent (still APPROVED)
    cursor.execute("SELECT status FROM email_drafts WHERE id = ?", (d2_id,))
    assert cursor.fetchone()[0] == "APPROVED"

    # Verify subsequent dispatch attempt is completely locked out by preflight breaker
    second_run_count = deliverer.send_approved_drafts(max_sends=5, enforce_content_validation=True)
    assert second_run_count == 0

    # Clear breaker and verify unlock
    clear_content_circuit_breaker(conn)
    tripped_after, _ = is_content_circuit_breaker_tripped(conn)
    assert not tripped_after

    conn.close()
