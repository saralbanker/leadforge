"""Opt-Out & Compliance Suppression Manager."""

from typing import Optional
from datetime import datetime, timezone
from leadforge.database import get_db_connection, uuidv7
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.execution_state import EntityStateMachine, InvalidTransitionError
from leadforge.repositories.base import RepositoryException
from leadforge.utils import get_logger

logger = get_logger()


class OptOutManager:
    """Manages suppression lists and handles opt-out / unsubscribe workflows."""

    def __init__(self, repository: Optional[SQLiteCommunicationRepository] = None):
        self.repo = repository or SQLiteCommunicationRepository()

    def is_suppressed(self, email_address: str) -> bool:
        """Checks if an email address is listed in unsubscribe_suppressions."""
        if not email_address or not email_address.strip():
            return False

        clean_email = email_address.strip().lower()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM unsubscribe_suppressions WHERE email = ?",
                (clean_email,),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def process_opt_out(self, email_address: str, thread_id: Optional[str] = None, reason: str = "PROSPECT_UNSUBSCRIBE") -> bool:
        """Registers email in suppressions and updates thread state to UNSUBSCRIBED.

        Args:
            email_address: Email address to suppress.
            thread_id: Optional CommunicationThread ID to transition.
            reason: Reason code for suppression.

        Returns:
            True if opt-out processed successfully.
        """
        clean_email = email_address.strip().lower()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO unsubscribe_suppressions (id, email, reason, created_at)
                VALUES (?, ?, ?, ?)
            """,
                (uuidv7(), clean_email, reason, now_str),
            )

            if thread_id:
                # Cancel pending followups for this thread
                cursor.execute(
                    "UPDATE followup_schedules SET status = 'SUPPRESSED' WHERE thread_id = ? AND status = 'PENDING'",
                    (thread_id,),
                )
            conn.commit()

            # Update thread state using EntityStateMachine if thread_id provided
            if thread_id:
                thread = self.repo.get_thread(thread_id)
                if thread and thread.current_state != "UNSUBSCRIBED":
                    try:
                        EntityStateMachine.validate_transition("CommunicationThread", thread.current_state, "UNSUBSCRIBED")
                        self.repo.update_thread_state(thread_id, "UNSUBSCRIBED")
                    except InvalidTransitionError as e:
                        logger.warning(f"[OptOutManager] State transition warning for thread {thread_id}: {e}")

            logger.info(f"[OptOutManager] Successfully processed opt-out for {clean_email}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"[OptOutManager] Failed to process opt-out for {clean_email}: {e}")
            raise RepositoryException(f"Failed to process opt-out: {e}")
        finally:
            conn.close()
