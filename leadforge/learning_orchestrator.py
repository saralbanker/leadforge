"""Learning Engine Orchestrator (LF-LRN-001).

Discovers potential learning candidates across Event Store, Email Drafts,
Opportunities, and Knowledge Graph entities, enqueuing them as structured
Learning Tasks for future batch execution.
"""

from typing import Any, Dict, List, Optional
from leadforge.database import get_db_connection
from leadforge.repositories.learning import SQLiteLearningTaskRepository
from leadforge.utils import get_logger

logger = get_logger()


class LearningOrchestrator:
    """Orchestrates discovery and queueing of learning tasks."""

    def __init__(self, task_repo: Optional[SQLiteLearningTaskRepository] = None) -> None:
        self.task_repo = task_repo or SQLiteLearningTaskRepository()

    def discover_and_enqueue_tasks(self) -> Dict[str, int]:
        """Scans database domain entities/events to discover candidates and enqueue learning tasks."""
        stats = {
            "email_sent": 0,
            "email_rejected": 0,
            "closed_won": 0,
            "closed_lost": 0,
        }
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # 1. Discover SENT outreach drafts for positive pattern learning
            cursor.execute(
                "SELECT id, opportunity_id, campaign_name FROM email_drafts WHERE status = 'SENT'"
            )
            for row in cursor.fetchall():
                task = self.task_repo.enqueue_task(
                    source_entity="EmailDraft",
                    entity_id=row["id"],
                    learning_type="SUCCESSFUL_OUTREACH",
                    priority=70,
                    payload={"opportunity_id": row["opportunity_id"], "campaign_name": row["campaign_name"]},
                )
                if task:
                    stats["email_sent"] += 1

            # 2. Discover REJECTED outreach drafts for failure pattern learning
            cursor.execute(
                "SELECT id, opportunity_id, error_message FROM email_drafts WHERE status = 'REJECTED'"
            )
            for row in cursor.fetchall():
                task = self.task_repo.enqueue_task(
                    source_entity="EmailDraft",
                    entity_id=row["id"],
                    learning_type="FAILED_OUTREACH",
                    priority=60,
                    payload={"opportunity_id": row["opportunity_id"], "rejection_reason": row["error_message"]},
                )
                if task:
                    stats["email_rejected"] += 1

            # 3. Discover CLOSED_WON opportunities
            cursor.execute(
                "SELECT id, business_id, estimated_value FROM opportunities WHERE pipeline_stage = 'CLOSED_WON'"
            )
            for row in cursor.fetchall():
                task = self.task_repo.enqueue_task(
                    source_entity="Opportunity",
                    entity_id=row["id"],
                    learning_type="CLOSED_DEAL",
                    priority=90,
                    payload={"business_id": row["business_id"], "deal_value": row["estimated_value"]},
                )
                if task:
                    stats["closed_won"] += 1

            # 4. Discover CLOSED_LOST opportunities
            cursor.execute(
                "SELECT id, business_id FROM opportunities WHERE pipeline_stage = 'CLOSED_LOST'"
            )
            for row in cursor.fetchall():
                task = self.task_repo.enqueue_task(
                    source_entity="Opportunity",
                    entity_id=row["id"],
                    learning_type="LOST_DEAL",
                    priority=50,
                    payload={"business_id": row["business_id"]},
                )
                if task:
                    stats["closed_lost"] += 1

            return stats
        finally:
            conn.close()

    def fetch_next_batch(self, batch_size: int = 10) -> List[Dict[str, Any]]:
        """Claims and returns the next batch of pending learning tasks."""
        return self.task_repo.claim_batch(batch_size=batch_size)

    def record_task_attempt(
        self, task_id: str, success: bool, failure_reason: str = ""
    ) -> Dict[str, Any]:
        """Records task execution result: marks COMPLETED if success, or fails/retries if failed."""
        if success:
            self.task_repo.complete_task(task_id)
            res = self.task_repo.get_task(task_id)
            return res or {"id": task_id, "status": "COMPLETED"}
        else:
            return self.task_repo.fail_task(task_id, failure_reason=failure_reason)

    def cleanup_tasks(self, days_old: int = 30) -> int:
        """Deletes completed/cancelled tasks older than specified days."""
        return self.task_repo.cleanup_completed(days_old=days_old)
