"""Follow-up Sequencer Engine for automated outreach cadences."""

from typing import Optional, List
from datetime import datetime, timezone
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.communication.optout import OptOutManager
from leadforge.communication.writer import LocalLLMEmailWriter
from leadforge.communication.context import BusinessContextBuilder
from leadforge.utils import get_logger

logger = get_logger()


class FollowupSequencer:
    """Processes pending follow-up schedules, verifies opt-out status, and dispatches automated steps."""

    def __init__(
        self,
        repository: Optional[SQLiteCommunicationRepository] = None,
        optout_manager: Optional[OptOutManager] = None,
        writer: Optional[LocalLLMEmailWriter] = None,
        context_builder: Optional[BusinessContextBuilder] = None,
    ):
        self.repo = repository or SQLiteCommunicationRepository()
        self.optout = optout_manager or OptOutManager(repository=self.repo)
        self.writer = writer or LocalLLMEmailWriter()
        self.context_builder = context_builder or BusinessContextBuilder()

    def process_due_followups(self, max_batch: int = 50) -> List[str]:
        """Scans pending follow-up schedules due at current time and processes them.

        Returns:
            List of processed schedule IDs.
        """
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        due_schedules = self.repo.get_pending_followups(now_str)[:max_batch]
        processed_ids: List[str] = []

        for sched in due_schedules:
            try:
                thread = self.repo.get_thread(sched.thread_id)
                if not thread:
                    logger.warning(f"[FollowupSequencer] Thread '{sched.thread_id}' not found for schedule {sched.id}")
                    continue

                if thread.current_state in ("UNSUBSCRIBED", "FAILED", "CANCELLED"):
                    logger.info(f"[FollowupSequencer] Thread '{thread.id}' is in terminal state '{thread.current_state}'. Skipping schedule {sched.id}.")
                    continue

                ctx = self.context_builder.build_context(thread.business_id)
                recipient_email = ctx.get("contact_email", "")

                # Check opt-out suppression list
                if recipient_email and self.optout.is_suppressed(recipient_email):
                    logger.info(f"[FollowupSequencer] Recipient {recipient_email} is suppressed. Opting out thread {thread.id}.")
                    self.optout.process_opt_out(recipient_email, thread_id=thread.id, reason="SUPPRESED_ON_FOLLOWUP")
                    continue

                # Generate follow-up copy
                subject, body = self.writer.generate_outbound_draft(ctx)

                # Record message
                self.repo.add_message(
                    thread_id=thread.id,
                    direction="OUTBOUND",
                    sender_email="outreach@leadforge.ai",
                    recipient_email=recipient_email or "prospect@business.com",
                    subject=f"Follow-up: {subject}",
                    body_text=body,
                    prompt_version="followup_v1",
                )

                # Mark schedule executed in SQLite
                from leadforge.database import get_db_connection
                conn = get_db_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE followup_schedules SET status = 'EXECUTED' WHERE id = ?",
                        (sched.id,),
                    )
                    conn.commit()
                finally:
                    conn.close()

                processed_ids.append(sched.id)
                logger.info(f"[FollowupSequencer] Successfully executed follow-up schedule {sched.id} for thread {thread.id}")
            except Exception as e:
                logger.error(f"[FollowupSequencer] Failed to process follow-up schedule {sched.id}: {e}")

        return processed_ids
