"""Unit and Integration tests for Communication Engine Phase 3."""

import pytest
from leadforge.communication.inbox import IMAPInboxMonitor
from leadforge.communication.classifier import LLMReplyClassifier
from leadforge.communication.optout import OptOutManager
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.database import get_db_connection, uuidv7, initialize_database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Sets up a temporary SQLite database with Phase 1, 2, and 3 tables."""
    db_file = tmp_path / "test_comm_phase3.db"
    monkeypatch.setattr("leadforge.database.DB_PATH", db_file)
    initialize_database()
    return db_file


def test_imap_inbox_monitor(temp_db):
    repo = SQLiteCommunicationRepository()
    monitor = IMAPInboxMonitor(repository=repo)

    # 1. Create business and thread
    conn = get_db_connection()
    biz_id = uuidv7()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO businesses (id, name, normalized_name, display_phone, contact_email, rating, review_count, website_domain) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (biz_id, "Test Corp", "test corp", "0791234567", "info@testcorp.com", 4.5, 10, "testcorp.com"),
    )
    cursor.execute(
        "INSERT INTO addresses (id, business_id, address_line, city, area, state, postal_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uuidv7(), biz_id, "101 Test St", "Ahmedabad", "Navrangpura", "Gujarat", "380009"),
    )
    conn.commit()
    conn.close()

    thread = repo.create_thread(business_id=biz_id, campaign_name="Outreach 2026")

    # 2. Process raw MIME email bytes
    raw_email = (
        b"From: prospect@testcorp.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Quick question\r\n"
        b"Message-ID: <msg-12345@testcorp.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Thanks for reaching out! We are interested in seeing a demo."
    )

    msg = monitor.process_inbound_raw_email(raw_email, thread_id=thread.id)

    assert msg is not None
    assert msg.thread_id == thread.id
    assert msg.direction == "INBOUND"
    assert msg.sender_email == "prospect@testcorp.com"
    assert "interested" in msg.body_text


def test_llm_reply_classifier():
    classifier = LLMReplyClassifier(api_url="http://invalid-ollama-url:11434")

    assert classifier.classify_reply("Please unsubscribe me from this list.") == "UNSUBSCRIBE"
    assert classifier.classify_reply("I am out of office until next Monday.") == "OUT_OF_OFFICE"
    assert classifier.classify_reply("Mail delivery failed: Address not found") == "BOUNCE"
    assert classifier.classify_reply("Yes, we are interested in a call!") == "POSITIVE"
    assert classifier.classify_reply("No thanks, not interested.") == "NEGATIVE"

    # Verify quoted footer with 'unsubscribe' does not trigger false UNSUBSCRIBE
    quoted_reply = (
        "Yes. Please. Contact later.\n\n"
        "On 16 Sep 2026, at 11:03 AM, Saral Banker wrote:\n"
        "> should i check back with you next quarter?\n"
        "> Reply STOP to unsubscribe.\n"
    )
    assert classifier.classify_reply(quoted_reply) == "POSITIVE"


def test_opt_out_manager(temp_db):
    repo = SQLiteCommunicationRepository()
    optout = OptOutManager(repository=repo)

    # 1. Setup thread and pending follow-up schedule
    conn = get_db_connection()
    biz_id = uuidv7()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO businesses (id, name, normalized_name, display_phone, contact_email, rating, review_count, website_domain) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (biz_id, "OptOut LLC", "optout llc", "0791234567", "stop@optout.com", 4.0, 5, "optout.com"),
    )
    cursor.execute(
        "INSERT INTO addresses (id, business_id, address_line, city, area, state, postal_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uuidv7(), biz_id, "202 Stop St", "Surat", "Vesu", "Gujarat", "395007"),
    )
    conn.commit()
    conn.close()

    thread = repo.create_thread(business_id=biz_id, campaign_name="Campaign 1")
    repo.update_thread_state(thread.id, "OUTREACH_SENT")
    schedule = repo.schedule_followup(thread_id=thread.id, sequence_step=1, scheduled_for="2026-08-01T10:00:00Z")

    # Verify not suppressed initially
    assert optout.is_suppressed("stop@optout.com") is False

    # Process opt-out
    res = optout.process_opt_out(email_address="stop@optout.com", thread_id=thread.id)
    assert res is True

    # Verify now suppressed
    assert optout.is_suppressed("stop@optout.com") is True

    # Verify thread state updated to UNSUBSCRIBED
    updated_thread = repo.get_thread(thread.id)
    assert updated_thread.current_state == "UNSUBSCRIBED"

    # Verify pending followup status updated to SUPPRESSED
    pending = repo.get_pending_followups("2026-12-31T23:59:59Z")
    assert len(pending) == 0
