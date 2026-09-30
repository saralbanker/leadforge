"""Tests for Follow-up Sequencing Engine (TASK F).

Covers:
- F1: Thread and schedule created exactly once on send, no duplicate thread on second send.
- F2: Scheduling with step delays, capping at 3 touches, suppression avoidance.
- F3: All cancellation triggers (suppression, inbound reply, bounce, non-awaiting state).
- F4: Follow-up copy differing from touch 1, deterministic selection, quality bans compliance.
- F5: Send allowance consumption, ramp adherence, bounce circuit breaker, priority over first touch.
- F6: Zero real mail transmission in test suite.
"""

import os
import tempfile
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import leadforge.database
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()

from leadforge.database import initialize_database, get_db_connection, uuidv7
from leadforge.outreach.deliverer import SMTPEmailDeliverer
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.communication.sequencer import FollowupSequencer
from leadforge.communication.writer import LocalLLMEmailWriter
from leadforge.communication.optout import OptOutManager
from leadforge.communication.context import BusinessContextBuilder
from leadforge.repositories.settings import SQLiteSettingsRepository, SettingsCache
from leadforge.outreach.router import CampaignRouter
from leadforge.outreach.ramp import delivery_allowance


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


@pytest.fixture(autouse=True)
def clean_test_tables():
    """Cleans tables between test cases for isolation."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM communication_messages")
        cursor.execute("DELETE FROM followup_schedules")
        cursor.execute("DELETE FROM communication_threads")
        cursor.execute("DELETE FROM email_drafts")
        cursor.execute("DELETE FROM opportunities")
        cursor.execute("DELETE FROM website_audits")
        cursor.execute("DELETE FROM digital_presences")
        cursor.execute("DELETE FROM addresses")
        cursor.execute("DELETE FROM businesses")
        cursor.execute("DELETE FROM unsubscribe_suppressions")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def mock_smtp_env():
    """Mocks SMTP configuration and network calls."""
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
         patch("leadforge.outreach.deliverer.SMTP_USE_TLS", True), \
         patch("smtplib.SMTP"):
        yield


def _create_test_business(name="Apex Engineering", email="contact@apexeng.in", city="Ahmedabad", is_suppressed=0):
    conn = get_db_connection()
    biz_id = uuidv7()
    opp_id = uuidv7()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM business_types WHERE name = ?", ("Manufacturing",))
        row = cursor.fetchone()
        if row:
            bt_id = row[0]
        else:
            bt_id = uuidv7()
            cursor.execute("INSERT INTO business_types (id, name) VALUES (?, ?)", (bt_id, "Manufacturing"))

        cursor.execute(
            """
            INSERT INTO businesses (id, name, normalized_name, contact_email, is_suppressed, business_type_id, rating, review_count, website_domain)
            VALUES (?, ?, ?, ?, ?, ?, 4.5, 20, 'apexeng.in')
            """,
            (biz_id, name, name.lower(), email, is_suppressed, bt_id),
        )
        cursor.execute(
            """
            INSERT INTO addresses (id, business_id, address_line, city, area, state, postal_code)
            VALUES (?, ?, '100 Industrial Area', ?, 'Naroda', 'Gujarat', '382330')
            """,
            (uuidv7(), biz_id, city),
        )
        cursor.execute(
            """
            INSERT INTO opportunities (id, business_id, title, pipeline_stage)
            VALUES (?, ?, 'Manufacturing RFQ Opportunity', 'PROSPECTING')
            """,
            (opp_id, biz_id),
        )
        conn.commit()
        return biz_id, opp_id
    finally:
        conn.close()


# ============================================================================
# F1: Thread and schedule created on send, reused on second send
# ============================================================================

def test_send_creates_thread_and_schedule_in_same_transaction(mock_smtp_env):
    """F1: Delivering an approved draft creates a communication_thread and followup_schedule."""
    biz_id, opp_id = _create_test_business("Shree Precision", "info@shreeprecision.in")
    conn = get_db_connection()
    draft_id = uuidv7()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Manufacturing - Direct RFQ & Plant Capability', 'info@shreeprecision.in', 'question regarding Shree Precision', 'First touch body text', 'APPROVED')
        """,
        (draft_id, opp_id),
    )
    conn.commit()
    conn.close()

    deliverer = SMTPEmailDeliverer()
    with patch.object(deliverer, "send_email", return_value=None):
        sent = deliverer.send_approved_drafts()
        assert sent == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    # Check draft is SENT
    d_row = cursor.execute("SELECT status, sent_at FROM email_drafts WHERE id = ?", (draft_id,)).fetchone()
    assert d_row["status"] == "SENT"
    assert d_row["sent_at"] is not None

    # Check thread exists with state AWAITING_REPLY
    t_rows = cursor.execute("SELECT id, business_id, current_state, campaign_name FROM communication_threads WHERE business_id = ?", (biz_id,)).fetchall()
    assert len(t_rows) == 1
    thread = t_rows[0]
    assert thread["current_state"] == "AWAITING_REPLY"
    assert thread["campaign_name"] == "Manufacturing - Direct RFQ & Plant Capability"

    # Check Touch 2 schedule exists
    s_rows = cursor.execute("SELECT id, thread_id, sequence_step, status, scheduled_for FROM followup_schedules WHERE thread_id = ?", (thread["id"],)).fetchall()
    assert len(s_rows) == 1
    sched = s_rows[0]
    assert sched["sequence_step"] == 2
    assert sched["status"] == "PENDING"

    # Check outbound message recorded
    m_rows = cursor.execute("SELECT id, thread_id, direction, subject FROM communication_messages WHERE thread_id = ?", (thread["id"],)).fetchall()
    assert len(m_rows) == 1
    assert m_rows[0]["direction"] == "OUTBOUND"
    assert m_rows[0]["subject"] == "question regarding Shree Precision"
    conn.close()


def test_send_reuses_existing_thread_no_duplicate(mock_smtp_env):
    """F1: Sending a second email for the same business reuses the existing thread without duplicating it."""
    biz_id, opp_id = _create_test_business("Keval Forgings", "sales@kevalforgings.in")
    conn = get_db_connection()
    cursor = conn.cursor()

    draft_id1 = uuidv7()
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Campaign A (General No Website)', 'sales@kevalforgings.in', 'Subject 1', 'Body 1', 'APPROVED')
        """,
        (draft_id1, opp_id),
    )
    conn.commit()
    conn.close()

    deliverer = SMTPEmailDeliverer()
    with patch.object(deliverer, "send_email", return_value=None):
        deliverer.send_approved_drafts()

    # Verify 1 thread
    conn = get_db_connection()
    t_count = conn.execute("SELECT COUNT(*) FROM communication_threads WHERE business_id = ?", (biz_id,)).fetchone()[0]
    assert t_count == 1

    # Insert second draft for same business
    draft_id2 = uuidv7()
    conn.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Campaign A (General No Website)', 'sales@kevalforgings.in', 'Subject 2', 'Body 2', 'APPROVED')
        """,
        (draft_id2, opp_id),
    )
    conn.commit()

    with patch.object(deliverer, "send_email", return_value=None):
        deliverer.send_approved_drafts()

    # Still exactly 1 thread for that business
    t_count_after = conn.execute("SELECT COUNT(*) FROM communication_threads WHERE business_id = ?", (biz_id,)).fetchone()[0]
    assert t_count_after == 1
    conn.close()


# ============================================================================
# F2: Step delays, max 3 touches, no scheduling for suppressed businesses
# ============================================================================

def test_no_schedule_for_suppressed_business_on_send(mock_smtp_env):
    """F2: Never schedule a follow-up for a business that is suppressed."""
    biz_id, opp_id = _create_test_business("OptedOut Ltd", "optout@optedout.com", is_suppressed=1)
    conn = get_db_connection()
    draft_id = uuidv7()
    conn.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Campaign A (General No Website)', 'optout@optedout.com', 'Subject', 'Body', 'APPROVED')
        """,
        (draft_id, opp_id),
    )
    conn.commit()
    conn.close()

    deliverer = SMTPEmailDeliverer()
    with patch.object(deliverer, "send_email", return_value=None):
        deliverer.send_approved_drafts()

    conn = get_db_connection()
    s_count = conn.execute(
        "SELECT COUNT(*) FROM followup_schedules s JOIN communication_threads t ON s.thread_id = t.id WHERE t.business_id = ?",
        (biz_id,),
    ).fetchone()[0]
    assert s_count == 0
    conn.close()


def test_followup_step_delays_and_touch3_scheduling():
    """F2: Step 2 defaults to 3 days, Step 3 defaults to 6 days after Touch 2."""
    biz_id, opp_id = _create_test_business("Cadence Works", "info@cadenceworks.in")
    repo = SQLiteCommunicationRepository()
    thread = repo.create_thread(business_id=biz_id, campaign_name="Manufacturing - Direct RFQ & Plant Capability", opportunity_id=opp_id, initial_state="AWAITING_REPLY")

    # Add initial outbound message
    repo.add_message(thread_id=thread.id, direction="OUTBOUND", sender_email="outreach@orvion.com", recipient_email="info@cadenceworks.in", subject="rfq inquiries for Cadence Works", body_text="Initial body text")

    # Schedule Touch 2 as due
    past_due = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sched2 = repo.schedule_followup(thread_id=thread.id, sequence_step=2, scheduled_for=past_due)

    sequencer = FollowupSequencer(repository=repo)
    mock_deliv = MagicMock()
    mock_deliv.is_configured = True
    mock_deliv.from_email = "outreach@orvion.com"
    sequencer.deliverer = mock_deliv

    processed = sequencer.process_due_followups()
    assert sched2.id in processed
    mock_deliv.send_email.assert_called_once()

    conn = get_db_connection()
    # Check sched2 status is EXECUTED
    s2_row = conn.execute("SELECT status FROM followup_schedules WHERE id = ?", (sched2.id,)).fetchone()
    assert s2_row["status"] == "EXECUTED"

    # Check Touch 3 is scheduled with status PENDING and ~6 days in future
    s3_row = conn.execute("SELECT sequence_step, status, scheduled_for FROM followup_schedules WHERE thread_id = ? AND sequence_step = 3", (thread.id,)).fetchone()
    assert s3_row is not None
    assert s3_row["status"] == "PENDING"
    scheduled_dt = datetime.strptime(s3_row["scheduled_for"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    delta_days = (scheduled_dt - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 5.5 <= delta_days <= 6.5
    conn.close()


def test_sequence_capped_at_three_touches():
    """F2: Cap the sequence at 3 touches total (original + 2 follow-ups)."""
    biz_id, opp_id = _create_test_business("MaxTouches Corp", "max@maxtouches.com")
    repo = SQLiteCommunicationRepository()
    thread = repo.create_thread(business_id=biz_id, campaign_name="Manufacturing - Direct RFQ & Plant Capability", opportunity_id=opp_id, initial_state="AWAITING_REPLY")

    repo.add_message(thread_id=thread.id, direction="OUTBOUND", sender_email="outreach@orvion.com", recipient_email="max@maxtouches.com", subject="Touch 1", body_text="Initial")

    # Schedule Touch 3 as due (touch 3 = final follow-up)
    past_due = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sched3 = repo.schedule_followup(thread_id=thread.id, sequence_step=3, scheduled_for=past_due)

    sequencer = FollowupSequencer(repository=repo)
    mock_deliv = MagicMock()
    mock_deliv.is_configured = True
    mock_deliv.from_email = "outreach@orvion.com"
    sequencer.deliverer = mock_deliv

    processed = sequencer.process_due_followups()
    assert sched3.id in processed

    conn = get_db_connection()
    # Ensure NO Touch 4 is scheduled
    s4_count = conn.execute("SELECT COUNT(*) FROM followup_schedules WHERE thread_id = ? AND sequence_step > 3", (thread.id,)).fetchone()[0]
    assert s4_count == 0

    # Total schedules on thread = 1 (touch 3)
    total_scheds = conn.execute("SELECT COUNT(*) FROM followup_schedules WHERE thread_id = ?", (thread.id,)).fetchone()[0]
    assert total_scheds == 1
    conn.close()


# ============================================================================
# F3: Stop on any signal (suppression, inbound reply, bounce, thread state)
# ============================================================================

def test_stop_on_suppression():
    """F3: Cancel pending followups with trigger_reason='BUSINESS_SUPPRESSED' when business is suppressed."""
    biz_id, opp_id = _create_test_business("StopSupp Corp", "stop@suppressed.com", is_suppressed=1)
    repo = SQLiteCommunicationRepository()
    thread = repo.create_thread(business_id=biz_id, campaign_name="Campaign A (General No Website)", opportunity_id=opp_id, initial_state="AWAITING_REPLY")
    sched = repo.schedule_followup(thread_id=thread.id, sequence_step=2, scheduled_for="2026-01-01T00:00:00Z")

    sequencer = FollowupSequencer(repository=repo)
    mock_deliv = MagicMock()
    sequencer.deliverer = mock_deliv

    processed = sequencer.process_due_followups()
    assert sched.id not in processed
    mock_deliv.send_email.assert_not_called()

    conn = get_db_connection()
    s_row = conn.execute("SELECT status, trigger_reason FROM followup_schedules WHERE id = ?", (sched.id,)).fetchone()
    assert s_row["status"] == "CANCELLED"
    assert s_row["trigger_reason"] == "BUSINESS_SUPPRESSED"
    conn.close()


def test_stop_on_inbound_reply():
    """F3: Cancel pending followups when ANY inbound message exists (prospect replied, human takes over)."""
    biz_id, opp_id = _create_test_business("Reply Corp", "buyer@replycorp.in")
    repo = SQLiteCommunicationRepository()
    thread = repo.create_thread(business_id=biz_id, campaign_name="Manufacturing - Direct RFQ & Plant Capability", opportunity_id=opp_id, initial_state="AWAITING_REPLY")
    sched = repo.schedule_followup(thread_id=thread.id, sequence_step=2, scheduled_for="2026-01-01T00:00:00Z")

    # Inbound message received
    repo.add_message(
        thread_id=thread.id,
        direction="INBOUND",
        sender_email="buyer@replycorp.in",
        recipient_email="outreach@orvion.com",
        subject="Re: Inquiry",
        body_text="Yes, let's talk tomorrow.",
        classification_label="POSITIVE",
    )

    sequencer = FollowupSequencer(repository=repo)
    mock_deliv = MagicMock()
    sequencer.deliverer = mock_deliv

    processed = sequencer.process_due_followups()
    assert sched.id not in processed
    mock_deliv.send_email.assert_not_called()

    conn = get_db_connection()
    s_row = conn.execute("SELECT status, trigger_reason FROM followup_schedules WHERE id = ?", (sched.id,)).fetchone()
    assert s_row["status"] == "CANCELLED"
    assert s_row["trigger_reason"] == "INBOUND_REPLY_RECEIVED"
    conn.close()


def test_stop_on_bounce():
    """F3: Cancel pending followups when the address bounced."""
    biz_id, opp_id = _create_test_business("Bounce Corp", "bad@bounced.com")
    repo = SQLiteCommunicationRepository()
    thread = repo.create_thread(business_id=biz_id, campaign_name="Campaign A (General No Website)", opportunity_id=opp_id, initial_state="AWAITING_REPLY")
    sched = repo.schedule_followup(thread_id=thread.id, sequence_step=2, scheduled_for="2026-01-01T00:00:00Z")

    # Record bounce message
    repo.add_message(
        thread_id=thread.id,
        direction="INBOUND",
        sender_email="mailer-daemon@google.com",
        recipient_email="outreach@orvion.com",
        subject="Undeliverable",
        body_text="Address not found",
        classification_label="BOUNCE",
    )

    sequencer = FollowupSequencer(repository=repo)
    mock_deliv = MagicMock()
    sequencer.deliverer = mock_deliv

    processed = sequencer.process_due_followups()
    assert sched.id not in processed
    mock_deliv.send_email.assert_not_called()

    conn = get_db_connection()
    s_row = conn.execute("SELECT status, trigger_reason FROM followup_schedules WHERE id = ?", (sched.id,)).fetchone()
    assert s_row["status"] == "CANCELLED"
    assert s_row["trigger_reason"] == "EMAIL_BOUNCED"
    conn.close()


def test_stop_on_non_awaiting_thread_state():
    """F3: Cancel pending followups if thread is not in an awaiting state."""
    biz_id, opp_id = _create_test_business("NonAwaiting Corp", "client@nonawaiting.com")
    repo = SQLiteCommunicationRepository()
    thread = repo.create_thread(business_id=biz_id, campaign_name="Campaign B (Booking)", opportunity_id=opp_id, initial_state="REPLIED_POSITIVE")
    sched = repo.schedule_followup(thread_id=thread.id, sequence_step=2, scheduled_for="2026-01-01T00:00:00Z")

    sequencer = FollowupSequencer(repository=repo)
    mock_deliv = MagicMock()
    sequencer.deliverer = mock_deliv

    processed = sequencer.process_due_followups()
    assert sched.id not in processed
    mock_deliv.send_email.assert_not_called()

    conn = get_db_connection()
    s_row = conn.execute("SELECT status, trigger_reason FROM followup_schedules WHERE id = ?", (sched.id,)).fetchone()
    assert s_row["status"] == "CANCELLED"
    assert "THREAD_STATE_REPLIED_POSITIVE" in s_row["trigger_reason"]
    conn.close()


# ============================================================================
# F4: Follow-up copy quality, deterministic selection, hard bans
# ============================================================================

def test_followup_copy_differs_from_touch1_and_passes_bans():
    """F4: Follow-up copy must not repeat touch 1, must be shorter, end in '?', and obey all hard bans."""
    biz_id, opp_id = _create_test_business("Precision Tech", "info@precisiontech.in", city="Ahmedabad")
    writer = LocalLLMEmailWriter()
    ctx = BusinessContextBuilder().build_context(biz_id)

    touch1_body = (
        "When procurement teams look for manufacturers in Ahmedabad, they check catalogs online before picking up the phone. "
        "Without a site, those RFQs go straight to other shops in the area.\n\n"
        "Could you handle a few more direct client inquiries this quarter?"
    )

    subj2, body2 = writer.generate_followup_draft(
        ctx,
        step=2,
        campaign_name="Manufacturing - Direct RFQ & Plant Capability",
        first_subject="rfq inquiries for Precision Tech",
        first_body=touch1_body,
    )

    subj3, body3 = writer.generate_followup_draft(
        ctx,
        step=3,
        campaign_name="Manufacturing - Direct RFQ & Plant Capability",
        first_subject="rfq inquiries for Precision Tech",
        first_body=touch1_body,
    )

    # Must differ from touch 1
    assert body2 != touch1_body
    assert body3 != touch1_body
    assert body2 != body3

    # Must be shorter than touch 1 (count words before the compliance footer,
    # greeting, and sign-off - see EmailQualityEngine._core_body / P0-3).
    from leadforge.outreach.quality import EmailQualityEngine
    core2 = EmailQualityEngine._core_body(body2)
    core3 = EmailQualityEngine._core_body(body3)
    core1 = touch1_body.split("---")[0].strip()
    assert len(core2.split()) < len(core1.split())
    assert len(core3.split()) < len(core1.split())

    # Hard bans check across all generated copy
    banned_words = [
        "online presence",
        "solutions",
        "leverage",
        "optimize",
        "streamline",
        "just bumping this",
        "did you see my last email",
        "—",
        "!",
    ]
    for banned in banned_words:
        assert banned not in core2.lower(), f"Found banned term '{banned}' in step 2 body: {core2}"
        assert banned not in core3.lower(), f"Found banned term '{banned}' in step 3 body: {core3}"

    # Must end in a genuine question
    assert core2.endswith("?")
    assert core3.endswith("?")


def test_followup_copy_deterministic_selection():
    """F4: Template variant selection is deterministic per business_id and step."""
    writer = LocalLLMEmailWriter()
    biz_id = "01932a00-1111-7001-8000-000000000001"
    ctx = {"business_id": biz_id, "name": "Vortex Valves", "city": "Vadodara"}

    # Repeated calls must return exact same text
    s2_a, b2_a = writer.generate_followup_draft(ctx, step=2, campaign_name="Manufacturing - Direct RFQ & Plant Capability")
    s2_b, b2_b = writer.generate_followup_draft(ctx, step=2, campaign_name="Manufacturing - Direct RFQ & Plant Capability")
    assert s2_a == s2_b
    assert b2_a == b2_b

    s3_a, b3_a = writer.generate_followup_draft(ctx, step=3, campaign_name="Manufacturing - Direct RFQ & Plant Capability")
    s3_b, b3_b = writer.generate_followup_draft(ctx, step=3, campaign_name="Manufacturing - Direct RFQ & Plant Capability")
    assert s3_a == s3_b
    assert b3_a == b3_b


# ============================================================================
# F5: Delivery allowance consumption and priority over first touch
# ============================================================================

def test_followups_consume_delivery_allowance(mock_smtp_env):
    """F5: Follow-ups draw down the same daily allowance as new outreach."""
    settings_repo = SQLiteSettingsRepository()
    settings_repo.set("outreach.daily_send_limit", "2")
    settings_repo.set("outreach.ramp_schedule", "1:2")

    biz1, opp1 = _create_test_business("Biz One", "b1@test.com")
    biz2, opp2 = _create_test_business("Biz Two", "b2@test.com")
    biz3, opp3 = _create_test_business("Biz Three", "b3@test.com")

    repo = SQLiteCommunicationRepository()
    t1 = repo.create_thread(business_id=biz1, campaign_name="Campaign A (General No Website)", opportunity_id=opp1, initial_state="AWAITING_REPLY")
    t2 = repo.create_thread(business_id=biz2, campaign_name="Campaign A (General No Website)", opportunity_id=opp2, initial_state="AWAITING_REPLY")
    t3 = repo.create_thread(business_id=biz3, campaign_name="Campaign A (General No Website)", opportunity_id=opp3, initial_state="AWAITING_REPLY")

    past_due = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s1 = repo.schedule_followup(thread_id=t1.id, sequence_step=2, scheduled_for=past_due)
    s2 = repo.schedule_followup(thread_id=t2.id, sequence_step=2, scheduled_for=past_due)
    s3 = repo.schedule_followup(thread_id=t3.id, sequence_step=2, scheduled_for=past_due)

    sequencer = FollowupSequencer(repository=repo)
    mock_deliv = MagicMock()
    mock_deliv.is_configured = True
    mock_deliv.from_email = "outreach@orvion.com"
    sequencer.deliverer = mock_deliv

    # Allowance is 2: only 2 followups can go out
    processed = sequencer.process_due_followups()
    assert len(processed) == 2
    assert s1.id in processed
    assert s2.id in processed
    assert s3.id not in processed

    # Third schedule remains PENDING for next run
    conn = get_db_connection()
    s3_status = conn.execute("SELECT status FROM followup_schedules WHERE id = ?", (s3.id,)).fetchone()["status"]
    assert s3_status == "PENDING"

    # Now verify new draft delivery is halted because allowance is 0
    draft_id = uuidv7()
    conn.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Campaign A (General No Website)', 'b3@test.com', 'New Draft', 'Body', 'APPROVED')
        """,
        (draft_id, opp3),
    )
    conn.commit()

    deliverer = SMTPEmailDeliverer()
    with patch.object(deliverer, "send_email", return_value=None):
        sent = deliverer.send_approved_drafts()
        # Must be 0 because daily allowance (2) was consumed by the 2 follow-ups
        assert sent == 0

    d_status = conn.execute("SELECT status FROM email_drafts WHERE id = ?", (draft_id,)).fetchone()["status"]
    assert d_status == "APPROVED"  # Still approved, not sent
    conn.close()
