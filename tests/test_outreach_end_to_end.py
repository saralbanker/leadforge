import os
import tempfile
import pytest
from leadforge.database import get_db_connection, initialize_database
from leadforge.decision_engine import DecisionEngine
from leadforge.execution_state import EntityStateMachine
from leadforge.outreach.deliverer import SMTPEmailDeliverer


@pytest.fixture
def outreach_env():
    """Fixture providing initialized database for end-to-end outreach test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    os.environ["LEADFORGE_DB_PATH"] = path
    initialize_database()

    conn = get_db_connection()
    yield conn

    conn.close()
    if os.path.exists(path):
        os.remove(path)


def test_complete_outreach_workflow(outreach_env):
    """End-to-end verification of the 8-step founder outreach workflow."""
    conn = outreach_env
    cursor = conn.cursor()

    # 1. Select / Seed Business & Opportunity
    biz_id = "00000000-0000-0000-0000-000000000010"
    opp_id = "00000000-0000-0000-0000-000000000020"
    draft_id = "00000000-0000-0000-0000-000000000030"

    cursor.execute(
        """
        INSERT INTO businesses (id, name, normalized_name, website_domain, display_phone, contact_email, created_at, updated_at)
        VALUES (?, 'Smile Dental Clinic', 'smile dental clinic', 'smiledental.com', '9876543210', 'dr@smiledental.com', '2026-07-21T00:00:00Z', '2026-07-21T00:00:00Z')
        """,
        (biz_id,),
    )
    cursor.execute(
        """
        INSERT INTO opportunities (id, business_id, title, pipeline_stage, score, estimated_value, created_at, updated_at)
        VALUES (?, ?, 'Dental Booking Integration', 'QUALIFICATION', 85.0, 3500.0, '2026-07-21T00:00:00Z', '2026-07-21T00:00:00Z')
        """,
        (opp_id, biz_id),
    )
    conn.commit()

    # 2. Find Contact Email
    cursor.execute("SELECT contact_email FROM businesses WHERE id = ?", (biz_id,))
    recipient_email = cursor.fetchone()["contact_email"]
    assert recipient_email == "dr@smiledental.com"

    # 3. Evaluate Decision Engine for Offer & Strategy Selection
    engine = DecisionEngine()
    decision = engine.evaluate_decision({
        "category": "Dental Clinic",
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 1.2,
        "rating": 4.8,
        "review_count": 50,
    })

    assert "Booking" in decision.service_name
    assert decision.outreach_strategy == "CONVERSION_OPTIMIZATION"
    assert len(decision.reasoning) > 0

    # 4. Create Email Draft (PENDING_APPROVAL)
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'Question re: scheduling', 'Hello Dr, do you accept online bookings?', 'PENDING_APPROVAL', '2026-07-21T00:00:00Z', '2026-07-21T00:00:00Z')
        """,
        (draft_id, opp_id, decision.campaign_name, recipient_email),
    )
    conn.commit()

    # 5. Review Draft Status
    cursor.execute("SELECT status FROM email_drafts WHERE id = ?", (draft_id,))
    assert cursor.fetchone()["status"] == "PENDING_APPROVAL"

    # 6. Validate & Approve Draft
    EntityStateMachine.validate_transition(
        entity_type="EmailDraft",
        current_state="PENDING_APPROVAL",
        next_state="APPROVED",
        triggering_event="EMAIL_APPROVED",
    )
    cursor.execute("UPDATE email_drafts SET status = 'APPROVED' WHERE id = ?", (draft_id,))
    conn.commit()

    cursor.execute("SELECT status FROM email_drafts WHERE id = ?", (draft_id,))
    assert cursor.fetchone()["status"] == "APPROVED"

    # 7. Deliver Approved Drafts (using mock/unconfigured SMTP handling)
    deliverer = SMTPEmailDeliverer()
    sent_count = deliverer.send_approved_drafts()
    # Unconfigured SMTP updates draft to FAILED and records EMAIL_SEND_FAILED event
    cursor.execute("SELECT status, error_message FROM email_drafts WHERE id = ?", (draft_id,))
    final_draft = cursor.fetchone()
    assert final_draft["status"] in ("SENT", "FAILED")

    # 8. Event Store Verification
    cursor.execute("SELECT event_type FROM event_store WHERE entity_id = ?", (draft_id,))
    events = [r["event_type"] for r in cursor.fetchall()]
    assert any(e in events for e in ("EMAIL_SENT", "EMAIL_SEND_FAILED"))
