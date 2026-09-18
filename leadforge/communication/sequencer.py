"""Follow-up Sequencer Engine for automated outreach cadences."""

from typing import Optional, List
from datetime import datetime, timezone, timedelta
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.communication.optout import OptOutManager
from leadforge.communication.writer import LocalLLMEmailWriter
from leadforge.communication.context import BusinessContextBuilder
from leadforge.outreach.deliverer import SMTPEmailDeliverer
from leadforge.outreach.ramp import delivery_allowance
from leadforge.repositories.settings import SettingsCache
from leadforge.database import get_db_connection, append_event, uuidv7
from leadforge.utils import get_logger

logger = get_logger()


class FollowupSequencer:
    """Processes pending follow-up schedules, verifies opt-out and signal status, and dispatches automated steps."""

    def __init__(
        self,
        repository: Optional[SQLiteCommunicationRepository] = None,
        optout_manager: Optional[OptOutManager] = None,
        writer: Optional[LocalLLMEmailWriter] = None,
        context_builder: Optional[BusinessContextBuilder] = None,
        deliverer: Optional[SMTPEmailDeliverer] = None,
    ):
        self.repo = repository or SQLiteCommunicationRepository()
        self.optout = optout_manager or OptOutManager(repository=self.repo)
        self.writer = writer or LocalLLMEmailWriter()
        self.context_builder = context_builder or BusinessContextBuilder()
        self.deliverer = deliverer or SMTPEmailDeliverer()

    def process_due_followups(self, max_batch: int = 50) -> List[str]:
        """Scans pending follow-up schedules due at current time and processes them.

        Respects delivery allowance, stops on any cancellation signal (suppression,
        inbound reply, bounce, non-awaiting state), caps sequences at max touches,
        and records sends across thread messages and draft history.

        Returns:
            List of successfully processed schedule IDs.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        settings_cache = SettingsCache()

        try:
            # F5: Delivery allowance and circuit breaker check
            allowance, allowance_reason = delivery_allowance(conn, settings_cache)
            logger.info(f"[FollowupSequencer] Delivery allowance: {allowance_reason}")
            if allowance <= 0:
                logger.warning(f"[FollowupSequencer] Outreach dispatch halted: {allowance_reason}")
                append_event(
                    event_type="DAILY_SEND_LIMIT_REACHED",
                    entity_type="System",
                    entity_id="sequencer",
                    payload={"allowance": allowance, "reason": allowance_reason},
                    conn=conn,
                )
                conn.commit()
                return []

            max_touches = settings_cache.get_int(
                "outreach.max_sequence_touches",
                settings_cache.get_int("outreach.max_touches", settings_cache.get_int("outreach.followup_max_touches", 3)),
            )

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            due_schedules = self.repo.get_pending_followups(now_str)
            batch_limit = min(max_batch, allowance)
            due_schedules = due_schedules[:batch_limit]

            processed_ids: List[str] = []

            for sched in due_schedules:
                if allowance <= 0:
                    logger.warning("[FollowupSequencer] Daily send limit reached during batch. Halting remaining followups.")
                    break

                try:
                    thread = self.repo.get_thread(sched.thread_id)
                    if not thread:
                        logger.warning(f"[FollowupSequencer] Thread '{sched.thread_id}' not found for schedule {sched.id}")
                        cursor.execute("UPDATE followup_schedules SET status = 'CANCELLED', trigger_reason = 'THREAD_NOT_FOUND' WHERE id = ?", (sched.id,))
                        conn.commit()
                        continue

                    ctx = self.context_builder.build_context(thread.business_id)
                    recipient_email = ctx.get("contact_email", "")

                    # F3 Signal 1: Check suppression / opt-out
                    is_suppressed = False
                    if recipient_email and self.optout.is_suppressed(recipient_email):
                        is_suppressed = True
                    cursor.execute("SELECT is_suppressed FROM businesses WHERE id = ?", (thread.business_id,))
                    b_row = cursor.fetchone()
                    if b_row and b_row["is_suppressed"]:
                        is_suppressed = True

                    if is_suppressed:
                        logger.info(f"[FollowupSequencer] Business {thread.business_id} ({recipient_email}) is suppressed. Cancelling remaining followups.")
                        cursor.execute(
                            "UPDATE followup_schedules SET status = 'CANCELLED', trigger_reason = 'BUSINESS_SUPPRESSED' WHERE thread_id = ? AND status = 'PENDING'",
                            (thread.id,),
                        )
                        conn.commit()
                        if thread.current_state != "UNSUBSCRIBED":
                            self.repo.update_thread_state(thread.id, "UNSUBSCRIBED")
                        continue

                    # F3 Signal 2: Check bounce signal
                    is_bounced = False
                    if not recipient_email:
                        is_bounced = True
                    cursor.execute(
                        "SELECT 1 FROM communication_messages WHERE thread_id = ? AND classification_label = 'BOUNCE'",
                        (thread.id,),
                    )
                    if cursor.fetchone():
                        is_bounced = True
                    cursor.execute(
                        "SELECT 1 FROM email_drafts ed JOIN opportunities o ON ed.opportunity_id = o.id WHERE o.business_id = ? AND ed.status = 'FAILED'",
                        (thread.business_id,),
                    )
                    if cursor.fetchone():
                        is_bounced = True

                    if is_bounced:
                        logger.info(f"[FollowupSequencer] Email address bounced for thread {thread.id}. Cancelling schedule {sched.id}.")
                        cursor.execute(
                            "UPDATE followup_schedules SET status = 'CANCELLED', trigger_reason = 'EMAIL_BOUNCED' WHERE thread_id = ? AND status = 'PENDING'",
                            (thread.id,),
                        )
                        conn.commit()
                        if thread.current_state != "FAILED":
                            self.repo.update_thread_state(thread.id, "FAILED")
                        continue

                    # F3 Signal 3: Check inbound messages (human reply received - human takes over)
                    cursor.execute(
                        "SELECT COUNT(*) FROM communication_messages WHERE thread_id = ? AND direction = 'INBOUND' AND (classification_label IS NULL OR classification_label != 'BOUNCE')",
                        (thread.id,),
                    )
                    inbound_count = cursor.fetchone()[0]
                    if inbound_count > 0:
                        logger.info(f"[FollowupSequencer] Inbound reply received on thread {thread.id}. Cancelling schedule {sched.id} (human takes over).")
                        cursor.execute(
                            "UPDATE followup_schedules SET status = 'CANCELLED', trigger_reason = 'INBOUND_REPLY_RECEIVED' WHERE thread_id = ? AND status = 'PENDING'",
                            (thread.id,),
                        )
                        conn.commit()
                        continue

                    # F3 Signal 4: Check thread awaiting state
                    if thread.current_state not in ("AWAITING_REPLY", "FOLLOWUP_PENDING", "OUTREACH_SENT"):
                        logger.info(f"[FollowupSequencer] Thread {thread.id} in non-awaiting state '{thread.current_state}'. Cancelling schedule {sched.id}.")
                        reason = f"THREAD_STATE_{thread.current_state}"
                        cursor.execute(
                            "UPDATE followup_schedules SET status = 'CANCELLED', trigger_reason = ? WHERE thread_id = ? AND status = 'PENDING'",
                            (reason, thread.id),
                        )
                        conn.commit()
                        continue

                    # Sequence cap check
                    current_touch = sched.sequence_step if sched.sequence_step in (2, 3) else (2 if sched.sequence_step == 1 else sched.sequence_step)
                    if current_touch > max_touches:
                        logger.info(f"[FollowupSequencer] Sequence step {current_touch} exceeds max touches {max_touches} for thread {thread.id}. Cancelling.")
                        cursor.execute(
                            "UPDATE followup_schedules SET status = 'CANCELLED', trigger_reason = 'MAX_TOUCHES_REACHED' WHERE thread_id = ? AND status = 'PENDING'",
                            (thread.id,),
                        )
                        conn.commit()
                        continue

                    # F4: Generate follow-up copy from campaign_routing.yaml
                    messages = self.repo.get_thread_messages(thread.id)
                    first_subject = None
                    first_body = None
                    first_msg_id = None
                    all_msg_ids = []
                    for m in messages:
                        if m.direction == "OUTBOUND":
                            if first_subject is None:
                                first_subject = m.subject
                                first_body = m.body_text
                                first_msg_id = getattr(m, "message_id_header", None)
                            if getattr(m, "message_id_header", None):
                                all_msg_ids.append(m.message_id_header)

                    subject, body = self.writer.generate_followup_draft(
                        ctx,
                        step=current_touch,
                        campaign_name=thread.campaign_name,
                        first_subject=first_subject,
                        first_body=first_body,
                    )

                    # Send email via deliverer if configured
                    is_configured = getattr(self.deliverer, "is_configured", True)
                    new_msg_id = None
                    if is_configured:
                        in_reply_to = first_msg_id
                        references = " ".join(all_msg_ids) if all_msg_ids else first_msg_id
                        new_msg_id = self.deliverer.send_email(
                            recipient_email,
                            subject,
                            body,
                            in_reply_to=in_reply_to,
                            references=references,
                        )
                    else:
                        logger.info(f"[FollowupSequencer] SMTP delivery simulated for {recipient_email}")

                    sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                    # Mark schedule executed
                    cursor.execute(
                        "UPDATE followup_schedules SET status = 'EXECUTED' WHERE id = ?",
                        (sched.id,),
                    )

                    # Record outbound message in communication_messages with message_id_header
                    from_email = getattr(self.deliverer, "from_email", "outreach@leadforge.ai") or "outreach@leadforge.ai"
                    header_val = new_msg_id if isinstance(new_msg_id, str) else None
                    cursor.execute(
                        """
                        INSERT INTO communication_messages (
                            id, thread_id, direction, message_id_header, sender_email, recipient_email, subject, body_text, prompt_version, created_at
                        ) VALUES (?, ?, 'OUTBOUND', ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (uuidv7(), thread.id, header_val, from_email, recipient_email or "prospect@business.com", subject, body, f"followup_v{current_touch}", sent_at),
                    )

                    # Record in email_drafts to ensure ramp & allowance metrics count it
                    opp_id = thread.opportunity_id
                    if not opp_id:
                        cursor.execute(
                            "SELECT id FROM opportunities WHERE business_id = ? ORDER BY created_at DESC LIMIT 1",
                            (thread.business_id,),
                        )
                        opp_row = cursor.fetchone()
                        if opp_row:
                            opp_id = opp_row["id"]
                        else:
                            opp_id = uuidv7()
                            cursor.execute(
                                "INSERT INTO opportunities (id, business_id, title, pipeline_stage) VALUES (?, ?, 'Outreach Opportunity', 'PROSPECTING')",
                                (opp_id, thread.business_id),
                            )

                    draft_id = uuidv7()
                    cursor.execute(
                        """
                        INSERT INTO email_drafts (
                            id, opportunity_id, campaign_name, recipient_email, subject, body, status, sent_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'SENT', ?, ?, ?)
                        """,
                        (draft_id, opp_id, thread.campaign_name, recipient_email, subject, body, sent_at, sent_at, sent_at),
                    )

                    # Update thread timestamps and state
                    cursor.execute(
                        """
                        UPDATE communication_threads 
                        SET current_state = 'AWAITING_REPLY', last_activity_at = ?, updated_at = ? 
                        WHERE id = ?
                        """,
                        (sent_at, sent_at, thread.id),
                    )

                    # Schedule Touch 3 if within max_touches limit
                    next_touch = current_touch + 1
                    if next_touch <= max_touches:
                        cursor.execute(
                            "SELECT 1 FROM followup_schedules WHERE thread_id = ? AND status = 'PENDING'",
                            (thread.id,),
                        )
                        if not cursor.fetchone():
                            step_delay = settings_cache.get_int(
                                f"outreach.followup_step{next_touch}_delay_days",
                                6 if next_touch == 3 else 3,
                            )
                            sched_dt = datetime.now(timezone.utc) + timedelta(days=step_delay)
                            sched_for = sched_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                            sched_id = uuidv7()
                            cursor.execute(
                                """
                                INSERT INTO followup_schedules (
                                    id, thread_id, sequence_step, scheduled_for, status, trigger_reason, created_at
                                ) VALUES (?, ?, ?, ?, 'PENDING', 'AWAITING_REPLY', ?)
                                """,
                                (sched_id, thread.id, next_touch, sched_for, sent_at),
                            )
                            append_event(
                                event_type="FOLLOWUP_SCHEDULED",
                                entity_type="FollowupSchedule",
                                entity_id=sched_id,
                                payload={"thread_id": thread.id, "sequence_step": next_touch, "scheduled_for": sched_for},
                                conn=conn,
                            )

                    append_event(
                        event_type="FOLLOWUP_SENT",
                        entity_type="FollowupSchedule",
                        entity_id=sched.id,
                        payload={"thread_id": thread.id, "step": current_touch, "recipient_email": recipient_email},
                        conn=conn,
                    )
                    conn.commit()

                    processed_ids.append(sched.id)
                    allowance -= 1
                    logger.info(f"[FollowupSequencer] Successfully executed follow-up schedule {sched.id} (step {current_touch}) for thread {thread.id}")
                except Exception as e:
                    conn.rollback()
                    logger.error(f"[FollowupSequencer] Failed to process follow-up schedule {sched.id}: {e}")

            return processed_ids
        finally:
            conn.close()
