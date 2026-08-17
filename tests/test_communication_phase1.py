"""Unit and Integration tests for Communication Engine Phase 1."""

import pytest
from datetime import datetime, timezone, timedelta

from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.execution_state import EntityStateMachine, InvalidTransitionError
from leadforge.database import get_db_connection, uuidv7, initialize_database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Sets up a temporary SQLite database with migration 018 applied."""
    db_file = tmp_path / "test_comm_phase1.db"
    monkeypatch.setattr("leadforge.database.DB_PATH", db_file)
    initialize_database()
    return db_file


def test_communication_repository_crud(temp_db):
    repo = SQLiteCommunicationRepository()

    # 1. Setup a test business record
    conn = get_db_connection()
    biz_id = uuidv7()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO businesses (id, name, normalized_name) VALUES (?, ?, ?)",
        (biz_id, "Apex Automation", "apex automation"),
    )
    conn.commit()
    conn.close()

    # 2. Create communication thread
    thread = repo.create_thread(
        business_id=biz_id,
        campaign_name="Ahmedabad_Manufacturers_2026",
        initial_state="PLANNED",
    )
    assert thread.id is not None
    assert thread.business_id == biz_id
    assert thread.current_state == "PLANNED"

    # 3. Retrieve thread by business
    fetched = repo.get_thread_by_business(biz_id)
    assert fetched is not None
    assert fetched.id == thread.id

    # 4. Update state
    repo.update_thread_state(thread.id, "OUTREACH_SENT")
    updated = repo.get_thread(thread.id)
    assert updated.current_state == "OUTREACH_SENT"

    # 5. Add outbound message
    out_msg = repo.add_message(
        thread_id=thread.id,
        direction="OUTBOUND",
        sender_email="sales@leadforge.ai",
        recipient_email="info@apexauto.in",
        subject="Automation Opportunity for Apex Automation",
        body_text="Hello, I noticed your manufacturing presence in Ahmedabad...",
    )
    assert out_msg.id is not None
    assert out_msg.direction == "OUTBOUND"

    # 6. Add inbound message
    in_msg = repo.add_message(
        thread_id=thread.id,
        direction="INBOUND",
        sender_email="info@apexauto.in",
        recipient_email="sales@leadforge.ai",
        subject="Re: Automation Opportunity",
        body_text="Thanks for reaching out! Please share pricing.",
        classification_label="POSITIVE",
    )
    assert in_msg.classification_label == "POSITIVE"

    # 7. Get all messages
    msgs = repo.get_thread_messages(thread.id)
    assert len(msgs) == 2
    assert msgs[0].direction == "OUTBOUND"
    assert msgs[1].direction == "INBOUND"

    # 8. Schedule follow-up
    due_time = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sched = repo.schedule_followup(
        thread_id=thread.id,
        sequence_step=1,
        scheduled_for=due_time,
        trigger_reason="AWAITING_REPLY",
    )
    assert sched.id is not None
    assert sched.sequence_step == 1

    # 9. Get pending follow-ups
    future_time = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pending = repo.get_pending_followups(future_time)
    assert len(pending) >= 1
    assert pending[0].thread_id == thread.id


def test_communication_thread_state_machine(temp_db):
    # 1. Valid transitions (validate_transition returns None on success)
    EntityStateMachine.validate_transition("CommunicationThread", "PLANNED", "OUTREACH_SENT")
    EntityStateMachine.validate_transition("CommunicationThread", "OUTREACH_SENT", "AWAITING_REPLY")
    EntityStateMachine.validate_transition("CommunicationThread", "AWAITING_REPLY", "REPLIED_POSITIVE")
    EntityStateMachine.validate_transition("CommunicationThread", "REPLIED_POSITIVE", "CLOSED_WON")

    # 2. Terminal state constraint
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("CommunicationThread", "UNSUBSCRIBED", "OUTREACH_SENT")

    # 3. Invalid transition
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("CommunicationThread", "PLANNED", "CLOSED_WON")
