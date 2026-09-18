"""Unit and Integration tests for Communication Engine Phase 4."""

import pytest
from fastapi.testclient import TestClient

from leadforge.communication.sequencer import FollowupSequencer
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.database import get_db_connection, uuidv7, initialize_database
from leadforge.server import app


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Sets up a temporary SQLite database with all migrations applied."""
    db_file = tmp_path / "test_comm_phase4.db"
    monkeypatch.setattr("leadforge.database.DB_PATH", db_file)
    initialize_database()
    return db_file


def test_followup_sequencer_execution(temp_db):
    repo = SQLiteCommunicationRepository()
    sequencer = FollowupSequencer(repository=repo)

    conn = get_db_connection()
    biz_id = uuidv7()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO businesses (id, name, normalized_name, display_phone, contact_email, rating, review_count, website_domain) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (biz_id, "Sequencer Corp", "sequencer corp", "0791234567", "seq@sequencer.com", 4.2, 8, "sequencer.com"),
    )
    cursor.execute(
        "INSERT INTO addresses (id, business_id, address_line, city, area, state, postal_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uuidv7(), biz_id, "303 Seq Rd", "Vadodara", "Alkapuri", "Gujarat", "390007"),
    )
    conn.commit()
    conn.close()

    thread = repo.create_thread(business_id=biz_id, campaign_name="Followup Campaign")
    repo.update_thread_state(thread.id, "OUTREACH_SENT")
    schedule = repo.schedule_followup(thread_id=thread.id, sequence_step=1, scheduled_for="2026-01-01T00:00:00Z")

    processed = sequencer.process_due_followups()

    assert schedule.id in processed
    messages = repo.get_thread_messages(thread.id)
    assert len(messages) == 1
    assert messages[0].direction == "OUTBOUND"
    assert "Follow-up" in messages[0].subject


def test_communication_rest_endpoints(temp_db):
    client = TestClient(app)

    conn = get_db_connection()
    biz_id = uuidv7()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO businesses (id, name, normalized_name, display_phone, contact_email, rating, review_count, website_domain) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (biz_id, "API Test Business", "api test business", "0791234567", "api@test.com", 4.9, 100, "apitest.com"),
    )
    cursor.execute(
        "INSERT INTO addresses (id, business_id, address_line, city, area, state, postal_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uuidv7(), biz_id, "404 API St", "Rajkot", "Kalawad Rd", "Gujarat", "360005"),
    )
    conn.commit()
    conn.close()

    # 1. Create thread via API
    resp = client.post("/api/communication/threads", json={"business_id": biz_id, "campaign_name": "API Campaign"})
    assert resp.status_code == 200
    thread_data = resp.json()
    assert "id" in thread_data
    thread_id = thread_data["id"]

    # 2. Ingest inbound reply via API
    inbound_resp = client.post(
        "/api/communication/inbound",
        json={
            "thread_id": thread_id,
            "sender_email": "api@test.com",
            "subject": "Re: Outreach",
            "body_text": "Please unsubscribe me from this list.",
        },
    )
    assert inbound_resp.status_code == 200
    inbound_data = inbound_resp.json()
    assert inbound_data["classification_label"] == "UNSUBSCRIBE"

    # 3. Fetch stats via API
    stats_resp = client.get("/api/communication/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["total_threads"] >= 1
    assert stats["unsubscribes"] >= 1
