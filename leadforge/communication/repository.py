"""SQLite Repository for Communication Engine persistence."""

from typing import Optional, List
from datetime import datetime, timezone
from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import RepositoryException
from leadforge.communication.base import (
    CommunicationThread,
    CommunicationMessage,
    FollowupSchedule,
)
from leadforge.utils import get_logger

logger = get_logger()


class SQLiteCommunicationRepository:
    """Repository handling CRUD operations for communication threads, messages, and schedules."""

    def create_thread(
        self,
        business_id: str,
        campaign_name: str,
        opportunity_id: Optional[str] = None,
        initial_state: str = "PLANNED",
    ) -> CommunicationThread:
        """Creates and persists a new communication thread."""
        thread_id = uuidv7()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO communication_threads (
                    id, business_id, opportunity_id, campaign_name, current_state, last_activity_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    thread_id,
                    business_id,
                    opportunity_id,
                    campaign_name,
                    initial_state,
                    now_str,
                    now_str,
                    now_str,
                ),
            )
            conn.commit()
            return CommunicationThread(
                id=thread_id,
                business_id=business_id,
                opportunity_id=opportunity_id,
                campaign_name=campaign_name,
                current_state=initial_state,
                last_activity_at=now_str,
                created_at=now_str,
                updated_at=now_str,
            )
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to create communication thread: {e}")
        finally:
            conn.close()

    def get_thread(self, thread_id: str) -> Optional[CommunicationThread]:
        """Retrieves a communication thread by ID."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, business_id, opportunity_id, campaign_name, current_state, last_activity_at, created_at, updated_at FROM communication_threads WHERE id = ?",
                (thread_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return CommunicationThread(
                id=row["id"],
                business_id=row["business_id"],
                opportunity_id=row["opportunity_id"],
                campaign_name=row["campaign_name"],
                current_state=row["current_state"],
                last_activity_at=row["last_activity_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    def get_thread_by_business(self, business_id: str) -> Optional[CommunicationThread]:
        """Retrieves the most recent communication thread for a business."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, business_id, opportunity_id, campaign_name, current_state, last_activity_at, created_at, updated_at FROM communication_threads WHERE business_id = ? ORDER BY created_at DESC LIMIT 1",
                (business_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return CommunicationThread(
                id=row["id"],
                business_id=row["business_id"],
                opportunity_id=row["opportunity_id"],
                campaign_name=row["campaign_name"],
                current_state=row["current_state"],
                last_activity_at=row["last_activity_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    def find_thread_by_email(self, email_address: str) -> Optional[CommunicationThread]:
        """Finds an active thread by matching sender/recipient email against business records, past messages, or email drafts."""
        if not email_address:
            return None
        clean_email = email_address.strip().lower()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            # 1. Match via businesses.contact_email with an existing thread
            cursor.execute(
                """
                SELECT ct.id, ct.business_id, ct.opportunity_id, ct.campaign_name, ct.current_state, ct.last_activity_at, ct.created_at, ct.updated_at
                FROM communication_threads ct
                JOIN businesses b ON ct.business_id = b.id
                WHERE LOWER(b.contact_email) = ?
                ORDER BY ct.created_at DESC LIMIT 1
                """,
                (clean_email,),
            )
            row = cursor.fetchone()
            if not row:
                # 2. Match via past outbound or inbound messages in communication_messages
                cursor.execute(
                    """
                    SELECT ct.id, ct.business_id, ct.opportunity_id, ct.campaign_name, ct.current_state, ct.last_activity_at, ct.created_at, ct.updated_at
                    FROM communication_threads ct
                    JOIN communication_messages cm ON ct.id = cm.thread_id
                    WHERE LOWER(cm.recipient_email) = ? OR LOWER(cm.sender_email) = ?
                    ORDER BY cm.created_at DESC LIMIT 1
                    """,
                    (clean_email, clean_email),
                )
                row = cursor.fetchone()

            if row:
                return CommunicationThread(
                    id=row["id"],
                    business_id=row["business_id"],
                    opportunity_id=row["opportunity_id"],
                    campaign_name=row["campaign_name"],
                    current_state=row["current_state"],
                    last_activity_at=row["last_activity_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )

            # 3. Match via email_drafts (in case email was sent via outreach pipeline before thread was initialized)
            cursor.execute(
                """
                SELECT b.id as business_id, ed.opportunity_id, ed.campaign_name
                FROM email_drafts ed
                JOIN opportunities o ON ed.opportunity_id = o.id
                JOIN businesses b ON o.business_id = b.id
                WHERE LOWER(ed.recipient_email) = ?
                ORDER BY ed.created_at DESC LIMIT 1
                """,
                (clean_email,),
            )
            draft_row = cursor.fetchone()
            if draft_row:
                b_id = draft_row["business_id"]
                opp_id = draft_row["opportunity_id"]
                camp_name = draft_row["campaign_name"] or "Outreach"
                conn.close()
                return self.create_thread(
                    business_id=b_id,
                    campaign_name=camp_name,
                    opportunity_id=opp_id,
                    initial_state="AWAITING_REPLY",
                )

            # 4. Match via businesses table directly
            cursor.execute(
                """
                SELECT id as business_id FROM businesses
                WHERE LOWER(contact_email) = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (clean_email,),
            )
            biz_row = cursor.fetchone()
            if biz_row:
                b_id = biz_row["business_id"]
                conn.close()
                return self.create_thread(
                    business_id=b_id,
                    campaign_name="Inbound Discovery",
                    initial_state="AWAITING_REPLY",
                )

            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def find_message_by_header(self, message_id_header: str) -> Optional[CommunicationMessage]:
        """Finds a communication message by its Message-ID header for deduplication."""
        if not message_id_header:
            return None
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, thread_id, direction, message_id_header, sender_email, recipient_email, subject, body_text, classification_label, prompt_version, created_at
                FROM communication_messages
                WHERE message_id_header = ?
                LIMIT 1
                """,
                (message_id_header.strip(),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return CommunicationMessage(
                id=row["id"],
                thread_id=row["thread_id"],
                direction=row["direction"],
                message_id_header=row["message_id_header"],
                sender_email=row["sender_email"],
                recipient_email=row["recipient_email"],
                subject=row["subject"],
                body_text=row["body_text"],
                classification_label=row["classification_label"],
                prompt_version=row["prompt_version"],
                created_at=row["created_at"],
            )
        finally:
            conn.close()

    def find_duplicate_inbound_message(
        self, thread_id: str, sender_email: str, subject: str, body_text: str
    ) -> Optional[CommunicationMessage]:
        """Finds an existing inbound message with identical thread, sender, subject, and body for idempotency."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, thread_id, direction, message_id_header, sender_email, recipient_email, subject, body_text, classification_label, prompt_version, created_at
                FROM communication_messages
                WHERE thread_id = ? AND direction = 'INBOUND' AND sender_email = ? AND subject = ? AND body_text = ?
                LIMIT 1
                """,
                (thread_id, sender_email, subject, body_text),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return CommunicationMessage(
                id=row["id"],
                thread_id=row["thread_id"],
                direction=row["direction"],
                message_id_header=row["message_id_header"],
                sender_email=row["sender_email"],
                recipient_email=row["recipient_email"],
                subject=row["subject"],
                body_text=row["body_text"],
                classification_label=row["classification_label"],
                prompt_version=row["prompt_version"],
                created_at=row["created_at"],
            )
        finally:
            conn.close()

    def update_thread_state(self, thread_id: str, new_state: str) -> None:
        """Updates the state and last_activity_at of a thread."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE communication_threads SET current_state = ?, last_activity_at = ?, updated_at = ? WHERE id = ?",
                (new_state, now_str, now_str, thread_id),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to update thread state: {e}")
        finally:
            conn.close()

    def add_message(
        self,
        thread_id: str,
        direction: str,
        sender_email: str,
        recipient_email: str,
        subject: str,
        body_text: str,
        message_id_header: Optional[str] = None,
        classification_label: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> CommunicationMessage:
        """Appends a new inbound or outbound message to a thread."""
        msg_id = uuidv7()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            conn.execute("BEGIN TRANSACTION;")
            cursor.execute(
                """
                INSERT INTO communication_messages (
                    id, thread_id, direction, message_id_header, sender_email, recipient_email, subject, body_text, classification_label, prompt_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    msg_id,
                    thread_id,
                    direction,
                    message_id_header,
                    sender_email,
                    recipient_email,
                    subject,
                    body_text,
                    classification_label,
                    prompt_version,
                    now_str,
                ),
            )
            # Update parent thread's last_activity_at
            cursor.execute(
                "UPDATE communication_threads SET last_activity_at = ?, updated_at = ? WHERE id = ?",
                (now_str, now_str, thread_id),
            )
            conn.commit()
            return CommunicationMessage(
                id=msg_id,
                thread_id=thread_id,
                direction=direction,
                message_id_header=message_id_header,
                sender_email=sender_email,
                recipient_email=recipient_email,
                subject=subject,
                body_text=body_text,
                classification_label=classification_label,
                prompt_version=prompt_version,
                created_at=now_str,
            )
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to add communication message: {e}")
        finally:
            conn.close()

    def get_thread_messages(self, thread_id: str) -> List[CommunicationMessage]:
        """Retrieves all messages for a thread ordered by creation time ASC."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, thread_id, direction, message_id_header, sender_email, recipient_email, subject, body_text, classification_label, prompt_version, created_at
                FROM communication_messages
                WHERE thread_id = ?
                ORDER BY created_at ASC
            """,
                (thread_id,),
            )
            rows = cursor.fetchall()
            return [
                CommunicationMessage(
                    id=row["id"],
                    thread_id=row["thread_id"],
                    direction=row["direction"],
                    message_id_header=row["message_id_header"],
                    sender_email=row["sender_email"],
                    recipient_email=row["recipient_email"],
                    subject=row["subject"],
                    body_text=row["body_text"],
                    classification_label=row["classification_label"],
                    prompt_version=row["prompt_version"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]
        finally:
            conn.close()

    def schedule_followup(
        self,
        thread_id: str,
        sequence_step: int,
        scheduled_for: str,
        trigger_reason: Optional[str] = None,
    ) -> FollowupSchedule:
        """Schedules a new follow-up step."""
        schedule_id = uuidv7()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO followup_schedules (
                    id, thread_id, sequence_step, scheduled_for, status, trigger_reason, created_at
                )
                VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
            """,
                (
                    schedule_id,
                    thread_id,
                    sequence_step,
                    scheduled_for,
                    trigger_reason,
                    now_str,
                ),
            )
            conn.commit()
            return FollowupSchedule(
                id=schedule_id,
                thread_id=thread_id,
                sequence_step=sequence_step,
                scheduled_for=scheduled_for,
                status="PENDING",
                trigger_reason=trigger_reason,
                created_at=now_str,
            )
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to schedule follow-up: {e}")
        finally:
            conn.close()

    def get_pending_followups(self, before_timestamp: str) -> List[FollowupSchedule]:
        """Retrieves all pending follow-up schedules due before the given timestamp."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, thread_id, sequence_step, scheduled_for, status, trigger_reason, created_at
                FROM followup_schedules
                WHERE status = 'PENDING' AND scheduled_for <= ?
                ORDER BY scheduled_for ASC
            """,
                (before_timestamp,),
            )
            rows = cursor.fetchall()
            return [
                FollowupSchedule(
                    id=row["id"],
                    thread_id=row["thread_id"],
                    sequence_step=row["sequence_step"],
                    scheduled_for=row["scheduled_for"],
                    status=row["status"],
                    trigger_reason=row["trigger_reason"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]
        finally:
            conn.close()
