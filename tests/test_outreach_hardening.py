import smtplib
import socket
import pytest
from unittest.mock import MagicMock, patch
from leadforge.database import get_db_connection, initialize_database, uuidv7
from leadforge.outreach.deliverer import SMTPEmailDeliverer
from leadforge.outreach.generator import compile_compliance_footer
from leadforge.repositories.settings import SQLiteSettingsRepository, SettingsCache


@pytest.fixture(autouse=True)
def setup_db():
    initialize_database()


def test_ph001_smtp_4xx_retry_success():
    """PH-001: Verifies 4xx temporary error retries up to 3 times before succeeding."""
    deliverer = SMTPEmailDeliverer()

    attempt_count = 0

    def mock_send(msg, to_email):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise smtplib.SMTPResponseException(421, b"4.4.2 Connection timed out, retrying")
        return None

    with patch("leadforge.outreach.deliverer.SMTP_CONFIGURED", True):
        with patch.object(deliverer, "_connect_and_send", side_effect=mock_send):
            with patch("time.sleep") as mock_sleep:
                deliverer.send_email("test@example.com", "Test Subject", "Test Body")
                assert attempt_count == 3
                assert mock_sleep.call_count == 2


def test_ph001_smtp_5xx_permanent_no_retry():
    """PH-001: Verifies 5xx permanent error fails immediately without retrying."""
    deliverer = SMTPEmailDeliverer()

    def mock_send(msg, to_email):
        raise smtplib.SMTPResponseException(550, b"5.1.1 User unknown")

    with patch("leadforge.outreach.deliverer.SMTP_CONFIGURED", True):
        with patch.object(deliverer, "_connect_and_send", side_effect=mock_send):
            with patch("time.sleep") as mock_sleep:
                with pytest.raises(smtplib.SMTPResponseException) as exc:
                    deliverer.send_email("baduser@example.com", "Test", "Test Body")
                assert exc.value.smtp_code == 550
                # Must fail on attempt 1 without sleeping/retrying
                assert mock_sleep.call_count == 0


def test_ph002_daily_send_safety_limit():
    """PH-002: Verifies dispatcher halts when daily_send_limit is reached."""
    repo = SQLiteSettingsRepository()
    repo.set("outreach.daily_send_limit", "2")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Clear existing drafts
    cursor.execute("DELETE FROM email_drafts")
    conn.commit()

    # Create 4 APPROVED drafts using existing or new opportunity
    cursor.execute("SELECT id FROM opportunities LIMIT 1")
    opp_row = cursor.fetchone()

    if opp_row:
        opp_id = opp_row[0]
    else:
        biz_id = uuidv7()
        opp_id = uuidv7()
        cursor.execute(
            "INSERT INTO businesses (id, name, normalized_name) VALUES (?, 'Test Business', 'test business')",
            (biz_id,),
        )
        cursor.execute(
            "INSERT INTO opportunities (id, business_id, title, score, pipeline_stage) VALUES (?, ?, 'Test Opportunity', 75.0, 'QUALIFICATION')",
            (opp_id, biz_id),
        )
        conn.commit()

    # Create 4 APPROVED drafts
    for i in range(4):
        draft_id = uuidv7()
        cursor.execute(
            """
            INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status, created_at, updated_at)
            VALUES (?, ?, 'Campaign A', ?, 'Subj', 'Body', 'APPROVED', '2026-07-21T00:00:00Z', '2026-07-21T00:00:00Z')
            """,
            (draft_id, opp_id, f"lead{i}@example.com"),
        )
    conn.commit()
    conn.close()

    deliverer = SMTPEmailDeliverer()

    with patch("leadforge.outreach.deliverer.SMTP_CONFIGURED", True):
        with patch.object(deliverer, "send_email") as mock_send:
            sent_count = deliverer.send_approved_drafts()
            assert sent_count == 2
            assert mock_send.call_count == 2

    # Verify remaining 2 drafts remain APPROVED
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM email_drafts WHERE status = 'APPROVED'")
    approved_remaining = cursor.fetchone()[0]
    assert approved_remaining == 2

    # Verify DAILY_SEND_LIMIT_REACHED event was recorded
    cursor.execute("SELECT COUNT(*) FROM event_store WHERE event_type = 'DAILY_SEND_LIMIT_REACHED'")
    limit_events = cursor.fetchone()[0]
    assert limit_events > 0
    conn.close()


def test_ph003_compliance_footer_compilation():
    """PH-003: Verifies compliance footer is built dynamically from settings."""
    repo = SQLiteSettingsRepository()
    repo.set("outreach.footer_company_name", "Acme Growth Consultants")
    repo.set("outreach.footer_website", "https://acmegrowth.com")
    repo.set("outreach.footer_opt_out_text", "Reply STOP to unsubscribe.")

    cache = SettingsCache()
    footer = compile_compliance_footer(cache)

    assert "Acme Growth Consultants" in footer
    assert "https://acmegrowth.com" in footer
    assert "Reply STOP to unsubscribe." in footer
    assert "---" in footer


def test_ph004_delivery_metrics_endpoint():
    """PH-004: Verifies FastAPI GET /api/outreach/metrics endpoint output structure."""
    from fastapi.testclient import TestClient
    from leadforge.server import app

    client = TestClient(app)
    response = client.get("/api/outreach/metrics")
    assert response.status_code == 200
    data = response.json()

    assert "sent_today" in data
    assert "failed_today" in data
    assert "approved_waiting" in data
    assert "pending_approval" in data
    assert "daily_send_limit" in data
    assert isinstance(data["sent_today"], int)
    assert isinstance(data["daily_send_limit"], int)
