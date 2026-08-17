import os
import tempfile
import pytest
from leadforge.learning_orchestrator import LearningOrchestrator
from leadforge.repositories.learning import SQLiteLearningTaskRepository


@pytest.fixture
def learning_setup():
    """Fixture providing initialized DB and LearningOrchestrator."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    os.environ["LEADFORGE_DB_PATH"] = path

    from leadforge.database import initialize_database
    initialize_database()

    repo = SQLiteLearningTaskRepository()
    orchestrator = LearningOrchestrator(task_repo=repo)

    yield repo, orchestrator

    if os.path.exists(path):
        os.remove(path)


def test_task_creation_and_enqueueing(learning_setup):
    """Verify enqueuing a learning task stores task correctly in PENDING state."""
    repo, _ = learning_setup
    task = repo.enqueue_task(
        source_entity="EmailDraft",
        entity_id="draft-123",
        learning_type="SUCCESSFUL_OUTREACH",
        priority=80,
        payload={"campaign": "Campaign A"},
    )

    assert task["id"] is not None
    assert task["source_entity"] == "EmailDraft"
    assert task["entity_id"] == "draft-123"
    assert task["learning_type"] == "SUCCESSFUL_OUTREACH"
    assert task["priority"] == 80
    assert task["status"] == "PENDING"
    assert task["retry_count"] == 0


def test_duplicate_task_prevention(learning_setup):
    """Verify duplicate task enqueueing ignores second insertion and returns existing task."""
    repo, _ = learning_setup
    t1 = repo.enqueue_task(
        source_entity="Opportunity",
        entity_id="opp-999",
        learning_type="CLOSED_DEAL",
        priority=90,
    )
    t2 = repo.enqueue_task(
        source_entity="Opportunity",
        entity_id="opp-999",
        learning_type="CLOSED_DEAL",
        priority=90,
    )

    assert t1["id"] == t2["id"]


def test_batch_selection_and_claiming(learning_setup):
    """Verify claiming next batch picks highest priority tasks and sets status to PROCESSING."""
    repo, orchestrator = learning_setup

    repo.enqueue_task("EmailDraftBatch", "batch-low-1", "OUTREACH", priority=10)
    repo.enqueue_task("EmailDraftBatch", "batch-high-1", "OUTREACH", priority=90)
    repo.enqueue_task("EmailDraftBatch", "batch-med-1", "OUTREACH", priority=50)

    batch = orchestrator.fetch_next_batch(batch_size=2)
    assert len(batch) == 2
    assert batch[0]["entity_id"] == "batch-high-1"
    assert batch[0]["status"] == "PROCESSING"
    assert batch[1]["entity_id"] == "batch-med-1"
    assert batch[1]["status"] == "PROCESSING"


def test_retry_increment_and_failure_transition(learning_setup):
    """Verify failing a task increments retry count and sets FAILED after max retries."""
    repo, orchestrator = learning_setup
    task = repo.enqueue_task(
        "EmailDraft", "fail-lead", "FAIL_TYPE", max_retries=2
    )
    task_id = task["id"]

    # Attempt 1: Fails -> status back to PENDING (retry_count = 1)
    res1 = orchestrator.record_task_attempt(task_id, success=False, failure_reason="Temporary API timeout")
    assert res1["retry_count"] == 1
    assert res1["status"] == "PENDING"

    # Claim task again
    orchestrator.fetch_next_batch(batch_size=1)

    # Attempt 2: Fails -> max_retries reached (retry_count = 2) -> status FAILED
    res2 = orchestrator.record_task_attempt(task_id, success=False, failure_reason="Permanent error")
    assert res2["retry_count"] == 2
    assert res2["status"] == "FAILED"


def test_successful_task_completion(learning_setup):
    """Verify recording a successful task attempt marks status COMPLETED."""
    repo, orchestrator = learning_setup
    task = repo.enqueue_task("Opportunity", "success-1", "CLOSED_DEAL")
    task_id = task["id"]

    orchestrator.fetch_next_batch(batch_size=1)
    res = orchestrator.record_task_attempt(task_id, success=True)
    assert res["status"] == "COMPLETED"


def test_orchestrator_discovery_scan(learning_setup):
    """Verify discover_and_enqueue_tasks scans existing entities and enqueues learning candidates."""
    repo, orchestrator = learning_setup

    biz_id = "00000000-0000-0000-0000-000000000001"
    opp_id = "00000000-0000-0000-0000-000000000002"
    draft_id = "00000000-0000-0000-0000-000000000003"

    # Insert sample domain data conforming to FK constraints
    from leadforge.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO businesses (id, name, normalized_name, created_at, updated_at)
        VALUES (?, 'Test Business', 'test business', '2026-07-21T00:00:00Z', '2026-07-21T00:00:00Z')
        """,
        (biz_id,),
    )
    cursor.execute(
        """
        INSERT INTO opportunities (id, business_id, title, pipeline_stage, estimated_value, created_at, updated_at)
        VALUES (?, ?, 'Deal 1', 'CLOSED_WON', 5000.0, '2026-07-21T00:00:00Z', '2026-07-21T00:00:00Z')
        """,
        (opp_id, biz_id),
    )
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, status, recipient_email, subject, body, created_at, updated_at)
        VALUES (?, ?, 'Campaign A', 'SENT', 'test@example.com', 'Sub', 'Body', '2026-07-21T00:00:00Z', '2026-07-21T00:00:00Z')
        """,
        (draft_id, opp_id),
    )
    conn.commit()
    conn.close()

    stats = orchestrator.discover_and_enqueue_tasks()
    assert stats["email_sent"] == 1
    assert stats["closed_won"] == 1

    t1 = repo.get_task_by_source("EmailDraft", draft_id, "SUCCESSFUL_OUTREACH")
    assert t1 is not None
    assert t1["priority"] == 70

    t2 = repo.get_task_by_source("Opportunity", opp_id, "CLOSED_DEAL")
    assert t2 is not None
    assert t2["priority"] == 90
