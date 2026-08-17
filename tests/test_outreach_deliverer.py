import os
import tempfile
import pytest
import smtplib
from pathlib import Path
from unittest.mock import patch, MagicMock


# Important: Override database path before importing any db modules to isolate test data
import leadforge.database

temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()
leadforge.database.DB_PATH = temp_db_path

from leadforge.database import initialize_database, get_db_connection  # noqa: E402
from leadforge.outreach.deliverer import SMTPEmailDeliverer  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown():
    # Bootstrap database
    initialize_database()
    yield
    # Cleanup temp db
    if temp_db_path.exists():
        try:
            os.remove(temp_db_path)
        except Exception:
            pass


@pytest.fixture
def smtp_env():
    """Fixture to temporarily mock SMTP config flags."""
    with patch("leadforge.outreach.deliverer.SMTP_CONFIGURED", True), \
         patch("leadforge.outreach.deliverer.SMTP_HOST", "smtp.example.com"), \
         patch("leadforge.outreach.deliverer.SMTP_PORT", 587), \
         patch("leadforge.outreach.deliverer.SMTP_USERNAME", "testuser"), \
         patch("leadforge.outreach.deliverer.SMTP_PASSWORD", "testpass"), \
         patch("leadforge.outreach.deliverer.SMTP_FROM_EMAIL", "outreach@orvion.com"), \
         patch("leadforge.outreach.deliverer.SMTP_FROM_NAME", "Orvion"), \
         patch("leadforge.outreach.deliverer.SMTP_USE_TLS", True):
        yield


@patch("smtplib.SMTP")
def test_send_email_tls(mock_smtp: MagicMock, smtp_env):
    """Verify SMTP TLS connection, login, and sendmail sequence."""
    mock_instance = MagicMock()
    mock_smtp.return_value = mock_instance

    deliverer = SMTPEmailDeliverer()
    deliverer.send_email("client@target.com", "Subject Line", "Body content")

    mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
    mock_instance.starttls.assert_called_once()
    mock_instance.login.assert_called_once_with("testuser", "testpass")
    mock_instance.sendmail.assert_called_once()
    mock_instance.quit.assert_called_once()


@patch("smtplib.SMTP")
def test_send_approved_drafts_loop(mock_smtp: MagicMock, smtp_env):
    """Verify database updates from APPROVED to SENT or FAILED."""
    mock_instance = MagicMock()
    mock_smtp.return_value = mock_instance

    conn = get_db_connection()
    cursor = conn.cursor()

    # Clear drafts first
    cursor.execute("DELETE FROM email_drafts")

    # Insert dummy records matching foreign keys
    business_id = "01907de3-bc42-7c89-8d76-5a507db4f111"
    opp_id = "01907de3-bc42-7c89-8d76-5a507db4f222"
    bt_id = "01907de3-bc42-7c89-8d76-5a507db4f333"

    cursor.execute("INSERT OR IGNORE INTO business_types (id, name) VALUES (?, ?);", (bt_id, "Logistics"))
    cursor.execute(
        """
        INSERT OR IGNORE INTO businesses (id, normalized_name, name, website_domain, business_type_id)
        VALUES (?, ?, ?, ?, ?);
        """,
        (business_id, "apex logistics", "Apex Logistics", "apexlogistics.in", bt_id)
    )
    cursor.execute(
        """
        INSERT OR IGNORE INTO opportunities (id, business_id, title, pipeline_stage)
        VALUES (?, ?, ?, 'PROSPECTING');
        """,
        (opp_id, business_id, "Logistics Offer Opportunity")
    )

    # Insert draft 1: APPROVED (will succeed)
    draft_id_success = "01907de3-bc42-7c89-8d76-5a507db4f444"
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, ?, ?, ?, ?, 'APPROVED');
        """,
        (draft_id_success, opp_id, "Campaign B", "success@target.com", "Subject Success", "Body Success")
    )

    # Insert draft 2: APPROVED (will fail SMTP send)
    draft_id_fail = "01907de3-bc42-7c89-8d76-5a507db4f555"
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, ?, ?, ?, ?, 'APPROVED');
        """,
        (draft_id_fail, opp_id, "Campaign B", "fail@target.com", "Subject Fail", "Body Fail")
    )
    conn.commit()

    # Configure mock SMTP to raise exception specifically on the second email send
    def sendmail_side_effect(from_addr, to_addrs, msg):
        if "fail@target.com" in to_addrs:
            raise smtplib.SMTPException("SMTP Auth Failure")
        return {}

    mock_instance.sendmail.side_effect = sendmail_side_effect

    # Run dispatch loop
    deliverer = SMTPEmailDeliverer()
    sent_count = deliverer.send_approved_drafts()

    assert sent_count == 1  # 1 succeeded, 1 failed

    # Assert database updates
    cursor.execute("SELECT status, sent_at, error_message FROM email_drafts WHERE id = ?", (draft_id_success,))
    success_row = cursor.fetchone()
    assert success_row["status"] == "SENT"
    assert success_row["sent_at"] is not None
    assert success_row["error_message"] is None

    cursor.execute("SELECT status, sent_at, error_message FROM email_drafts WHERE id = ?", (draft_id_fail,))
    fail_row = cursor.fetchone()
    assert fail_row["status"] == "FAILED"
    assert fail_row["sent_at"] is None
    assert "SMTP Auth Failure" in fail_row["error_message"]

    conn.close()
