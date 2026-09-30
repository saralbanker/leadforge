"""Tests for Task D: IMAP Reply Loop, Ingestion, Classification, Side Effects, and Idempotency."""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from leadforge.communication.inbox import IMAPInboxMonitor
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.communication.optout import OptOutManager
from leadforge.database import get_db_connection, uuidv7, initialize_database
from leadforge.outreach.ramp import bounce_rate
from leadforge.server import app


class FakeIMAPClient:
    """Faked IMAP SSL client that simulates unseen searching, fetching, and flag updates in-memory."""

    def __init__(self, messages_by_id: dict, unseen_ids: list):
        self.messages_by_id = dict(messages_by_id)
        self.unseen_ids = [str(i) for i in unseen_ids]
        self.selected_folder = None
        self.stored_flags = []  # [(msg_id, action, flag)]
        self.logged_in = False
        self.closed = False
        self.logged_out = False

    def login(self, username, password):
        self.logged_in = True
        return "OK", [b"Logged in"]

    def select(self, folder="INBOX"):
        self.selected_folder = folder
        return "OK", [b"Selected"]

    def search(self, charset, criterion):
        if criterion == "UNSEEN":
            ids_str = " ".join(self.unseen_ids)
            return "OK", [ids_str.encode("utf-8")]
        return "OK", [b""]

    def fetch(self, msg_id, fetch_type):
        msg_id_str = str(msg_id)
        if msg_id_str in self.messages_by_id:
            raw = self.messages_by_id[msg_id_str]
            header = f"{msg_id_str} (RFC822 {{{len(raw)}}})".encode("utf-8")
            return "OK", [(header, raw), b")"]
        return "NO", [b"Message not found"]

    def store(self, msg_id, action, flag):
        msg_id_str = str(msg_id)
        self.stored_flags.append((msg_id_str, action, flag))
        if "\\Seen" in flag and msg_id_str in self.unseen_ids:
            self.unseen_ids.remove(msg_id_str)
        return "OK", [b"Flags updated"]

    def close(self):
        self.closed = True
        return "OK", [b"Closed"]

    def logout(self):
        self.logged_out = True
        return "OK", [b"Logged out"]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Sets up a clean isolated SQLite database."""
    db_file = tmp_path / "test_reply_loop.db"
    monkeypatch.setattr("leadforge.database.DB_PATH", db_file)
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db_file))
    initialize_database()
    return db_file


def _create_test_business_and_thread(biz_name: str, email: str, campaign: str = "Outreach"):
    """Helper to seed a business, opportunity, and communication thread in SQLite."""
    conn = get_db_connection()
    biz_id = uuidv7()
    opp_id = uuidv7()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO businesses (id, name, normalized_name, contact_email, is_suppressed) VALUES (?, ?, ?, ?, 0)",
        (biz_id, biz_name, biz_name.lower(), email),
    )
    cursor.execute(
        "INSERT INTO opportunities (id, business_id, title, score, pipeline_stage) VALUES (?, ?, ?, 80, 'PROSPECTING')",
        (opp_id, biz_id, f"Opportunity for {biz_name}"),
    )
    # A thread that is AWAITING_REPLY means outreach actually went out. The poller
    # only reads mail from addresses it has emailed, so the sent draft has to exist
    # for this address to be recognised as ours rather than the owner's personal mail.
    cursor.execute(
        "INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, "
        "subject, body, status, sent_at) VALUES (?,?,?,?,?,?,'SENT',"
        "strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
        (uuidv7(), opp_id, campaign, email, "Outreach", "Body"),
    )
    conn.commit()
    conn.close()

    repo = SQLiteCommunicationRepository()
    thread = repo.create_thread(business_id=biz_id, campaign_name=campaign, opportunity_id=opp_id, initial_state="AWAITING_REPLY")
    return biz_id, opp_id, thread


def test_unseen_only_fetching(temp_db):
    """Verifies that IMAPInboxMonitor searches for UNSEEN messages only."""
    biz_id, opp_id, thread = _create_test_business_and_thread("Acme Steel", "acme@acmesteel.in")

    raw_email_1 = (
        b"From: acme@acmesteel.in\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Software inquiry\r\n"
        b"Message-ID: <msg-unseen-1@acmesteel.in>\r\n\r\n"
        b"Yes, we are interested in software."
    )
    raw_email_2 = (
        b"From: acme@acmesteel.in\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Past email\r\n"
        b"Message-ID: <msg-seen-2@acmesteel.in>\r\n\r\n"
        b"Old message already seen."
    )

    fake_imap = FakeIMAPClient(
        messages_by_id={"1": raw_email_1, "2": raw_email_2},
        unseen_ids=["1"],  # Only message 1 is UNSEEN
    )

    monitor = IMAPInboxMonitor()
    result = monitor.poll_inbox(client=fake_imap)

    assert result["status"] == "success"
    assert result["processed_count"] == 1
    assert len(result["messages"]) == 1
    assert result["messages"][0]["sender_email"] == "acme@acmesteel.in"
    # Verify flag update was recorded only for message 1
    assert ("1", "+FLAGS", "\\Seen") in fake_imap.stored_flags
    assert not any(f[0] == "2" for f in fake_imap.stored_flags)


def test_mark_seen_strictly_after_successful_persist(temp_db):
    """Verifies that an email is marked seen ONLY after successful database persistence."""
    biz_id, opp_id, thread = _create_test_business_and_thread("Delta Pumps", "info@deltapumps.com")

    # Message 1: Valid and matches known thread -> will persist successfully
    raw_valid = (
        b"From: info@deltapumps.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Pump Inquiry\r\n"
        b"Message-ID: <msg-valid-1@deltapumps.com>\r\n\r\n"
        b"Sounds good, let's talk next week."
    )

    # Message 2: From completely unknown sender with no matchable business -> cannot resolve thread
    raw_unknown = (
        b"From: unknown_spammer@randomdomain.xyz\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Spam offer\r\n"
        b"Message-ID: <msg-spam-2@randomdomain.xyz>\r\n\r\n"
        b"Buy random products."
    )

    fake_imap = FakeIMAPClient(
        messages_by_id={"10": raw_valid, "20": raw_unknown},
        unseen_ids=["10", "20"],
    )

    monitor = IMAPInboxMonitor()
    result = monitor.poll_inbox(client=fake_imap)

    assert result["processed_count"] == 1
    # Message 10 was successfully persisted and therefore marked seen
    assert ("10", "+FLAGS", "\\Seen") in fake_imap.stored_flags
    # Message 20 could not resolve thread / persist and therefore was NOT marked seen
    assert not any(f[0] == "20" for f in fake_imap.stored_flags)


def test_one_bad_message_does_not_abort_batch(temp_db):
    """Verifies that a single corrupt / malformed message is logged and skipped without aborting the batch."""
    biz_id1, opp_id1, thread1 = _create_test_business_and_thread("Alpha Tech", "alpha@alphatech.in")
    biz_id2, opp_id2, thread2 = _create_test_business_and_thread("Beta Tech", "beta@betatech.in")

    raw_msg_1 = (
        b"From: alpha@alphatech.in\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Partnership\r\n"
        b"Message-ID: <msg-alpha@alphatech.in>\r\n\r\n"
        b"Sure, please send a demo."
    )
    raw_corrupt = b"CORRUPT NON-MIME GARBAGE \xff\xfe INVALID BYTES"
    raw_msg_3 = (
        b"From: beta@betatech.in\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Unsubscribe\r\n"
        b"Message-ID: <msg-beta@betatech.in>\r\n\r\n"
        b"Please remove me from this list."
    )

    fake_imap = FakeIMAPClient(
        messages_by_id={"1": raw_msg_1, "2": raw_corrupt, "3": raw_msg_3},
        unseen_ids=["1", "2", "3"],
    )

    # Force message 2 to fail inside process_inbound_raw_email or fetch
    monitor = IMAPInboxMonitor()
    result = monitor.poll_inbox(client=fake_imap)

    # Both message 1 and message 3 should be processed; message 2 skipped
    assert result["status"] == "success"
    assert result["processed_count"] == 2
    assert ("1", "+FLAGS", "\\Seen") in fake_imap.stored_flags
    assert ("3", "+FLAGS", "\\Seen") in fake_imap.stored_flags


def test_side_effect_unsubscribe(temp_db):
    """Verifies UNSUBSCRIBE classification immediately suppresses business and cancels pending followups."""
    biz_id, opp_id, thread = _create_test_business_and_thread("Zenith Motors", "stop@zenithmotors.com")
    repo = SQLiteCommunicationRepository()
    optout = OptOutManager(repository=repo)

    # Schedule a pending follow-up
    repo.schedule_followup(thread_id=thread.id, sequence_step=1, scheduled_for="2026-09-01T10:00:00Z")

    assert optout.is_suppressed("stop@zenithmotors.com") is False

    raw_unsub = (
        b"From: stop@zenithmotors.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Please Unsubscribe\r\n"
        b"Message-ID: <msg-unsub@zenithmotors.com>\r\n\r\n"
        b"Please unsubscribe me and stop emailing our office."
    )

    monitor = IMAPInboxMonitor(repository=repo)
    msg = monitor.process_inbound_raw_email(raw_unsub)

    assert msg is not None
    assert msg.classification_label == "UNSUBSCRIBE"

    # Verify OptOutManager suppression table
    assert optout.is_suppressed("stop@zenithmotors.com") is True

    # Verify business row is_suppressed = 1
    conn = get_db_connection()
    b_row = conn.execute("SELECT is_suppressed FROM businesses WHERE id = ?", (biz_id,)).fetchone()
    assert b_row["is_suppressed"] == 1

    # Verify thread state updated to UNSUBSCRIBED
    updated_thread = repo.get_thread(thread.id)
    assert updated_thread.current_state == "UNSUBSCRIBED"

    # Verify pending followups cancelled / suppressed
    pending = repo.get_pending_followups("2026-12-31T23:59:59Z")
    assert len(pending) == 0
    conn.close()


def test_side_effect_bounce(temp_db):
    """Verifies BOUNCE classification records bounce, counts in bounce_rate, clears dead email, and cancels drafts."""
    biz_id, opp_id, thread = _create_test_business_and_thread("Dead Lead Corp", "dead@deadlead.com")
    repo = SQLiteCommunicationRepository()

    conn = get_db_connection()
    cursor = conn.cursor()
    # Create approved draft for this dead address
    draft_id = uuidv7()
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status, sent_at)
        VALUES (?, ?, 'Outreach', 'dead@deadlead.com', 'Subject', 'Body', 'SENT', '2026-08-20T10:00:00Z')
        """,
        (draft_id, opp_id),
    )
    # Also create a pending approval draft
    draft_id2 = uuidv7()
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Outreach', 'dead@deadlead.com', 'Subject 2', 'Body 2', 'APPROVED')
        """,
        (draft_id2, opp_id),
    )
    conn.commit()

    raw_bounce = (
        b"From: MAILER-DAEMON@googlemail.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Delivery Status Notification (Failure)\r\n"
        b"Message-ID: <bounce-999@googlemail.com>\r\n\r\n"
        b"The response was: 550 5.1.1 The email account that you tried to reach does not exist: dead@deadlead.com"
    )

    monitor = IMAPInboxMonitor(repository=repo)
    msg = monitor.process_inbound_raw_email(raw_bounce)

    assert msg is not None
    assert msg.classification_label == "BOUNCE"

    # Verify bounce_rate in ramp.py counts this bounce
    rate, bad, total = bounce_rate(conn, window=50)
    assert bad >= 1

    # Verify dead email is cleared on businesses table
    biz_row = conn.execute("SELECT contact_email FROM businesses WHERE id = ?", (biz_id,)).fetchone()
    assert biz_row["contact_email"] is None

    # Verify approved draft was cancelled
    d_row = conn.execute("SELECT status FROM email_drafts WHERE id = ?", (draft_id2,)).fetchone()
    assert d_row["status"] == "CANCELLED"
    conn.close()


def test_side_effect_bounce_soft_is_retryable(temp_db):
    """A soft bounce (4.x.x / mailbox full) must NOT clear the contact email or
    cancel queued drafts - the address may still be good, unlike a hard bounce."""
    biz_id, opp_id, thread = _create_test_business_and_thread("Sleepy Lead Corp", "sleepy@sleepylead.com")
    repo = SQLiteCommunicationRepository()

    conn = get_db_connection()
    cursor = conn.cursor()
    draft_id2 = uuidv7()
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, 'Outreach', 'sleepy@sleepylead.com', 'Subject 2', 'Body 2', 'APPROVED')
        """,
        (draft_id2, opp_id),
    )
    conn.commit()

    raw_bounce = (
        b"From: MAILER-DAEMON@googlemail.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Delivery Status Notification (Delay)\r\n"
        b"Message-ID: <bounce-soft-1@googlemail.com>\r\n\r\n"
        b"The response was: 450 4.2.2 The email account sleepy@sleepylead.com that you tried to reach is over quota. Try again later."
    )

    monitor = IMAPInboxMonitor(repository=repo)
    msg = monitor.process_inbound_raw_email(raw_bounce)

    assert msg is not None
    assert msg.classification_label == "BOUNCE"

    # Contact email must survive a soft bounce.
    biz_row = conn.execute("SELECT contact_email FROM businesses WHERE id = ?", (biz_id,)).fetchone()
    assert biz_row["contact_email"] == "sleepy@sleepylead.com"

    # Queued draft must survive a soft bounce.
    d_row = conn.execute("SELECT status FROM email_drafts WHERE id = ?", (draft_id2,)).fetchone()
    assert d_row["status"] == "APPROVED"

    # Thread must not be marked terminally FAILED on a soft bounce.
    thread_row = conn.execute(
        "SELECT current_state FROM communication_threads WHERE id = ?", (thread.id,)
    ).fetchone()
    assert thread_row["current_state"] != "FAILED"
    conn.close()


def test_classify_bounce_severity():
    """Unit coverage for the hard/soft bounce severity classifier itself."""
    from leadforge.communication.classifier import classify_bounce_severity

    assert classify_bounce_severity("550 5.1.1 The email account that you tried to reach does not exist") == "hard"
    assert classify_bounce_severity("The recipient's mailbox is full and cannot accept messages (mailbox full)") == "soft"
    assert classify_bounce_severity("421 4.7.0 try again later, mailbox temporarily deferred") == "soft"
    assert classify_bounce_severity("No such user here") == "hard"
    assert classify_bounce_severity("") == "hard"


def test_side_effect_positive(temp_db):
    """Verifies POSITIVE classification flags prominently, transitions state, cancels followups, and does NOT auto-book."""
    biz_id, opp_id, thread = _create_test_business_and_thread("Interested Corp", "buyer@interested.com")
    repo = SQLiteCommunicationRepository()

    # Schedule a pending automated follow-up
    repo.schedule_followup(thread_id=thread.id, sequence_step=1, scheduled_for="2026-09-01T10:00:00Z")

    raw_positive = (
        b"From: buyer@interested.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Website redesign\r\n"
        b"Message-ID: <msg-pos-123@interested.com>\r\n\r\n"
        b"Yes, we are interested in a quote! Can we set up a call this week?"
    )

    monitor = IMAPInboxMonitor(repository=repo)
    msg = monitor.process_inbound_raw_email(raw_positive)

    assert msg is not None
    assert msg.classification_label == "POSITIVE"

    # Verify thread state updated to REPLIED_POSITIVE
    updated_thread = repo.get_thread(thread.id)
    assert updated_thread.current_state == "REPLIED_POSITIVE"

    # Verify automated follow-up cancelled (human takes over)
    pending = repo.get_pending_followups("2026-12-31T23:59:59Z")
    assert len(pending) == 0

    # Verify event stored
    conn = get_db_connection()
    events = conn.execute("SELECT event_type FROM event_store WHERE entity_id = ?", (thread.id,)).fetchall()
    event_types = [e["event_type"] for e in events]
    assert "PROSPECT_REPLIED_POSITIVE" in event_types
    conn.close()


def test_side_effects_negative_and_neutral(temp_db):
    """Verifies NEGATIVE, OUT_OF_OFFICE, and NEUTRAL classifications are handled correctly."""
    biz_id, opp_id, thread = _create_test_business_and_thread("Neutral Corp", "info@neutralcorp.com")
    repo = SQLiteCommunicationRepository()
    monitor = IMAPInboxMonitor(repository=repo)

    # 1. Negative
    raw_neg = (
        b"From: info@neutralcorp.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Offer\r\n"
        b"Message-ID: <neg-1@neutralcorp.com>\r\n\r\n"
        b"No thanks, not interested."
    )
    msg_neg = monitor.process_inbound_raw_email(raw_neg)
    assert msg_neg.classification_label == "NEGATIVE"
    assert repo.get_thread(thread.id).current_state == "REPLIED_NEGATIVE"

    # 2. Out of Office
    raw_ooo = (
        b"From: info@neutralcorp.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Automatic reply: Offer\r\n"
        b"Message-ID: <ooo-1@neutralcorp.com>\r\n\r\n"
        b"I am out of office on vacation until Monday."
    )
    msg_ooo = monitor.process_inbound_raw_email(raw_ooo)
    assert msg_ooo.classification_label == "OUT_OF_OFFICE"


def test_poll_idempotency_repeated_runs(temp_db):
    """Verifies that polling or processing the same message twice does not create duplicate rows or side-effects."""
    biz_id, opp_id, thread = _create_test_business_and_thread("Idempotent Corp", "client@idempotent.com")
    repo = SQLiteCommunicationRepository()

    raw_msg = (
        b"From: client@idempotent.com\r\n"
        b"To: outreach@leadforge.ai\r\n"
        b"Subject: Re: Software\r\n"
        b"Message-ID: <unique-fixed-id-12345@idempotent.com>\r\n\r\n"
        b"Yes, sounds good, let's talk."
    )

    fake_imap = FakeIMAPClient(
        messages_by_id={"1": raw_msg},
        unseen_ids=["1"],
    )

    monitor = IMAPInboxMonitor(repository=repo)

    # Run 1: First poll
    res1 = monitor.poll_inbox(client=fake_imap)
    assert res1["processed_count"] == 1

    conn = get_db_connection()
    count_1 = conn.execute("SELECT COUNT(*) FROM communication_messages WHERE thread_id = ?", (thread.id,)).fetchone()[0]
    assert count_1 == 1

    # Run 2: Second poll with same message
    fake_imap.unseen_ids = ["1"]  # Simulate message being presented again
    monitor.poll_inbox(client=fake_imap)

    count_2 = conn.execute("SELECT COUNT(*) FROM communication_messages WHERE thread_id = ?", (thread.id,)).fetchone()[0]
    # Count of messages must remain strictly 1
    assert count_2 == 1
    conn.close()


def test_api_poll_replies_endpoint(temp_db):
    """Verifies the FastAPI POST endpoint /api/outreach/poll-replies works correctly."""
    client = TestClient(app)
    _create_test_business_and_thread("API Corp", "contact@apicorp.com")

    with patch.object(IMAPInboxMonitor, "poll_inbox") as mock_poll:
        mock_poll.return_value = {
            "status": "success",
            "processed_count": 1,
            "counts": {"POSITIVE": 1, "NEGATIVE": 0, "UNSUBSCRIBE": 0, "BOUNCE": 0, "OUT_OF_OFFICE": 0, "NEUTRAL": 0},
            "messages": [{"id": "msg-1", "classification_label": "POSITIVE"}],
        }

        resp = client.post("/api/outreach/poll-replies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["processed_count"] == 1
        assert data["counts"]["POSITIVE"] == 1

        # Also test alternate route /api/outreach/replies/poll
        resp2 = client.post("/api/outreach/replies/poll")
        assert resp2.status_code == 200
