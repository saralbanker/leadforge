"""IMAP Inbox Monitor & Inbound Message Ingestion Engine."""

import email
import imaplib
import re
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from typing import Any, Dict, List, Optional, Tuple

from leadforge.communication.base import CommunicationMessage
from leadforge.communication.classifier import LLMReplyClassifier, VALID_CLASSIFICATIONS, classify_bounce_severity
from leadforge.communication.optout import OptOutManager
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.database import append_event, get_db_connection
from leadforge.utils import get_logger

logger = get_logger()


def _decode_header_str(val: Optional[str]) -> str:
    """Decodes MIME encoded header strings safely."""
    if not val:
        return ""
    try:
        return str(make_header(decode_header(val))).strip()
    except Exception:
        return str(val).strip()


def _clean_email_address(addr: str) -> str:
    """Extracts raw email address from header string like 'Name <name@domain.com>'."""
    if not addr:
        return ""
    _, clean = parseaddr(addr)
    if clean:
        return clean.strip().lower()
    if "<" in addr and ">" in addr:
        return addr.split("<")[1].split(">")[0].strip().lower()
    return addr.strip().lower()


class IMAPInboxMonitor:
    """Monitors incoming emails over IMAP SSL, parses threading headers,
    classifies reply intent, executes compliance & CRM side effects, and ingests
    into communication repository idempotently.
    """

    def __init__(
        self,
        repository: Optional[SQLiteCommunicationRepository] = None,
        classifier: Optional[LLMReplyClassifier] = None,
        optout_manager: Optional[OptOutManager] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.repo = repository or SQLiteCommunicationRepository()
        self.classifier = classifier or LLMReplyClassifier()
        self.optout = optout_manager or OptOutManager(repository=self.repo)
        self._explicit_host = host
        self._explicit_port = port
        self._explicit_username = username
        self._explicit_password = password

    def _get_imap_credentials(self) -> Tuple[str, int, str, str]:
        """Resolves IMAP connection parameters from SMTP config / settings."""
        from leadforge.config import get_smtp_config
        smtp_cfg = get_smtp_config()
        host = self._explicit_host or "imap.gmail.com"
        port = self._explicit_port or 993
        username = self._explicit_username or smtp_cfg.get("username", "")
        password = self._explicit_password or smtp_cfg.get("password", "")
        return host, int(port), username, password

    # Bounces arrive from the mail system, not from the prospect, so the
    # allow-list has to admit them or the circuit breaker never sees a bounce.
    _BOUNCE_SENDERS = ("mailer-daemon", "postmaster", "mail-delivery", "no-reply@dns")

    def _outreach_senders(self) -> set:
        """Addresses this system has actually emailed.

        The inbox being polled is a real person's mailbox. Only mail from someone
        we contacted - or from the mail system reporting on that mail - may be
        read, classified or acted upon. Everything else is left untouched and
        unread.
        """
        from leadforge.database import get_db_connection
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT lower(trim(recipient_email)) FROM email_drafts "
                "WHERE status IN ('SENT', 'FAILED') AND recipient_email IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows if r and r[0]}

    @staticmethod
    def _sender_of(raw_bytes: bytes) -> str:
        from email.utils import parseaddr
        try:
            msg = email.message_from_bytes(raw_bytes)
        except Exception:
            return ""
        return (parseaddr(msg.get("From", ""))[1] or "").strip().lower()

    def _is_relevant(self, sender: str, known: set) -> bool:
        if not sender:
            return False
        if sender in known:
            return True
        return any(tag in sender for tag in self._BOUNCE_SENDERS)

    def poll_inbox(self, client: Optional[Any] = None) -> Dict[str, Any]:
        """Polls the IMAP inbox for UNSEEN messages, ingests & classifies them,
        marks each message as SEEN only after it is successfully persisted,
        and logs and skips unparseable messages without aborting the batch.

        Args:
            client: Optional faked/mocked IMAP client for testing.

        Returns:
            Dict containing processed_count, counts per classification label, and list of message summaries.
        """
        counts = {label: 0 for label in VALID_CLASSIFICATIONS}
        processed_messages: List[Dict[str, Any]] = []
        known_senders = self._outreach_senders()
        skipped_foreign = 0

        imap = client
        should_close = False

        if imap is None:
            host, port, username, password = self._get_imap_credentials()
            if not username or not password:
                logger.warning("[IMAPInboxMonitor] IMAP credentials not configured. Skipping poll.")
                return {
                    "status": "skipped",
                    "reason": "credentials_not_configured",
                    "processed_count": 0,
                    "counts": counts,
                    "messages": [],
                }

            try:
                imap = imaplib.IMAP4_SSL(host, port)
                imap.login(username, password)
                should_close = True
            except Exception as conn_err:
                logger.error(f"[IMAPInboxMonitor] IMAP connection / login failed: {conn_err}")
                return {
                    "status": "error",
                    "error": str(conn_err),
                    "processed_count": 0,
                    "counts": counts,
                    "messages": [],
                }

        try:
            # 1. Select INBOX
            imap.select("INBOX")

            # 2. Search for UNSEEN messages only
            status, search_data = imap.search(None, "UNSEEN")
            if status != "OK" or not search_data or not search_data[0]:
                logger.info("[IMAPInboxMonitor] No unseen messages in INBOX.")
                return {
                    "status": "success",
                    "processed_count": 0,
                    "counts": counts,
                    "messages": [],
                }

            raw_ids = search_data[0]
            if isinstance(raw_ids, bytes):
                msg_ids = raw_ids.split()
            elif isinstance(raw_ids, str):
                msg_ids = raw_ids.split()
            elif isinstance(raw_ids, (list, tuple)):
                msg_ids = raw_ids
            else:
                msg_ids = []

            logger.info(f"[IMAPInboxMonitor] Found {len(msg_ids)} unseen message(s) to fetch.")

            for msg_id in msg_ids:
                id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                try:
                    # Phase 1: Header pre-filter using BODY.PEEK[HEADER.FIELDS (FROM)]
                    # Downloads only sender headers to skip non-outreach personal email without pulling heavy attachments.
                    sender = ""
                    try:
                        hdr_status, hdr_data = imap.fetch(id_str, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
                        if hdr_status == "OK" and hdr_data:
                            for part in hdr_data:
                                if isinstance(part, tuple) and len(part) >= 2:
                                    sender = self._sender_of(part[1])
                                    break
                                elif isinstance(part, bytes):
                                    sender = self._sender_of(part)
                                    break
                    except Exception as hdr_err:
                        logger.debug(f"[IMAPInboxMonitor] Header pre-fetch fallback for {id_str}: {hdr_err}")

                    if sender and not self._is_relevant(sender, known_senders):
                        skipped_foreign += 1
                        continue

                    # Phase 2: Full payload fetch via (BODY.PEEK[]) for relevant outreach replies or bounces
                    fetch_status, msg_data = imap.fetch(id_str, "(BODY.PEEK[])")
                    if fetch_status != "OK" or not msg_data:
                        logger.warning(f"[IMAPInboxMonitor] Failed to fetch message ID {id_str}.")
                        continue

                    raw_bytes = None
                    for part in msg_data:
                        if isinstance(part, tuple) and len(part) >= 2:
                            raw_bytes = part[1]
                            break
                        elif isinstance(part, bytes):
                            raw_bytes = part
                            break

                    if not raw_bytes:
                        logger.warning(f"[IMAPInboxMonitor] Empty payload for message ID {id_str}.")
                        continue

                    if not sender:
                        sender = self._sender_of(raw_bytes)
                        if not self._is_relevant(sender, known_senders):
                            skipped_foreign += 1
                            continue

                    # Process raw email bytes: parse, resolve thread, classify, persist, execute side effects
                    persisted_msg = self.process_inbound_raw_email(raw_bytes)
                    if persisted_msg is not None:
                        # Strictly mark seen AFTER successful persist
                        imap.store(id_str, "+FLAGS", "\\Seen")
                        label = persisted_msg.classification_label or "NEUTRAL"
                        counts[label] = counts.get(label, 0) + 1
                        processed_messages.append({
                            "id": persisted_msg.id,
                            "thread_id": persisted_msg.thread_id,
                            "sender_email": persisted_msg.sender_email,
                            "subject": persisted_msg.subject,
                            "classification_label": label,
                        })
                    else:
                        logger.warning(f"[IMAPInboxMonitor] Message ID {id_str} was not persisted. Skipping mark-seen.")
                except Exception as item_err:
                    # Resilient: A single bad message is logged and skipped, never aborting the batch
                    logger.error(f"[IMAPInboxMonitor] Error processing message ID {id_str}: {item_err}")
                    continue

        finally:
            if should_close:
                try:
                    imap.close()
                except Exception:
                    pass
                try:
                    imap.logout()
                except Exception:
                    pass

        logger.info(
            f"[IMAPInboxMonitor] Inbox poll complete. Processed: {len(processed_messages)}, "
            f"Counts: {counts}, Left untouched (not our outreach): {skipped_foreign}"
        )
        return {
            "status": "success",
            "processed_count": len(processed_messages),
            "skipped_foreign": skipped_foreign,
            "counts": counts,
            "messages": processed_messages,
        }

    def fetch_and_process_inbound_messages(self, client: Optional[Any] = None) -> Dict[str, Any]:
        """Alias for poll_inbox for backward/forward naming compatibility."""
        return self.poll_inbox(client=client)

    def process_inbound_raw_email(
        self, raw_email_bytes: bytes, thread_id: Optional[str] = None
    ) -> Optional[CommunicationMessage]:
        """Parses raw MIME email bytes, deduplicates, matches thread, classifies intent,
        persists inbound message, and applies CRM / compliance side effects.

        Args:
            raw_email_bytes: Bytes of the raw email message.
            thread_id: Optional explicit thread ID if known.

        Returns:
            Created or existing CommunicationMessage, or None if processing fails.
        """
        try:
            msg: Message = email.message_from_bytes(raw_email_bytes)

            raw_sender = msg.get("From", "")
            raw_recipient = msg.get("To", "")
            raw_subject = msg.get("Subject", "")
            message_id = msg.get("Message-ID", "").strip()

            sender = _clean_email_address(raw_sender)
            recipient = _clean_email_address(raw_recipient)
            subject = _decode_header_str(raw_subject)

            # Idempotency check 1: Has this exact message-id header already been ingested?
            if message_id:
                existing_by_header = self.repo.find_message_by_header(message_id)
                if existing_by_header:
                    logger.info(f"[IMAPInboxMonitor] Duplicate message ignored (Message-ID: {message_id})")
                    return existing_by_header

            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition") or "")
                    if "attachment" not in content_disposition:
                        if content_type in ("text/plain", "text/html", "message/rfc822", "message/delivery-status"):
                            payload = part.get_payload(decode=True)
                            if payload:
                                decoded = payload.decode(errors="ignore")
                                if content_type == "text/plain":
                                    body_text = decoded
                                    break
                                elif not body_text:
                                    body_text = decoded
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(errors="ignore")

            # Resolve thread ID if not provided explicitly
            target_thread_id = thread_id
            bounced_candidate_email = None

            if not target_thread_id and sender:
                matched_thread = self.repo.find_thread_by_email(sender)
                if matched_thread:
                    target_thread_id = matched_thread.id

            # Handle Bounces: If sender is mail daemon / bounce or thread not found, inspect body for failed email
            is_daemon_sender = any(daemon_kw in sender.lower() for daemon_kw in ("mailer-daemon", "postmaster", "mail-delivery", "noreply", "no-reply"))

            if not target_thread_id or is_daemon_sender:
                # Prefer the address a DSN actually reports as failed, rather than
                # any address that happens to appear in the body (which can include
                # an attached original message, headers, or signatures unrelated to
                # the failed recipient, causing misattribution to the wrong thread).
                reported_failures = re.findall(
                    r"(?:wasn'?t delivered to|delivery to the following recipient(?:s)? failed|"
                    r"final-recipient:\s*rfc822;|original-recipient:\s*rfc822;)\s*"
                    r"[<\s]*([\w.\-+]+@[\w.\-]+\.\w+)",
                    body_text,
                    re.IGNORECASE,
                )
                candidates = [e.strip().lower() for e in reported_failures]
                if not candidates:
                    # Fall back to any address in the body, excluding sender/recipient.
                    candidates = [
                        e.strip().lower() for e in re.findall(r"[\w.\-]+@[\w.\-]+\.\w+", body_text)
                        if e.strip().lower() not in (sender.lower(), recipient.lower())
                    ]
                for cand_clean in candidates:
                    if cand_clean in (sender.lower(), recipient.lower()):
                        continue
                    cand_thread = self.repo.find_thread_by_email(cand_clean)
                    if cand_thread:
                        target_thread_id = cand_thread.id
                        bounced_candidate_email = cand_clean
                        break

            if not target_thread_id:
                logger.warning(f"[IMAPInboxMonitor] Unable to resolve thread for inbound message from '{sender}'")
                return None

            # Classification
            full_text_for_class = f"Subject: {subject}\n\n{body_text}" if subject else body_text
            label = self.classifier.classify_reply(full_text_for_class)
            if label not in VALID_CLASSIFICATIONS:
                label = "NEUTRAL"

            # If sender was a daemon or subject has delivery failure, force BOUNCE classification
            if is_daemon_sender or any(b_kw in subject.lower() for b_kw in ("failure", "undelivered", "delivery status", "returned to sender", "failed")):
                label = "BOUNCE"

            # Idempotency check 2: Deduplicate by (thread_id, sender_email, subject, body_text)
            existing_duplicate = self.repo.find_duplicate_inbound_message(
                thread_id=target_thread_id,
                sender_email=sender,
                subject=subject,
                body_text=body_text,
            )
            if existing_duplicate:
                logger.info(f"[IMAPInboxMonitor] Inbound message already exists in thread {target_thread_id}")
                return existing_duplicate

            # Persist message
            inbound_msg = self.repo.add_message(
                thread_id=target_thread_id,
                direction="INBOUND",
                sender_email=sender,
                recipient_email=recipient or "outreach@leadforge.ai",
                subject=subject,
                body_text=body_text,
                message_id_header=message_id or None,
                classification_label=label,
            )

            # Apply classification side effects (Opt-out, Bounce clearing, Prominent positive flagging)
            self._apply_classification_side_effects(
                msg=inbound_msg,
                target_thread_id=target_thread_id,
                label=label,
                sender_email=sender,
                bounced_email=bounced_candidate_email,
            )

            logger.info(
                f"[IMAPInboxMonitor] Successfully ingested inbound message {inbound_msg.id} "
                f"for thread {target_thread_id} with classification '{label}'"
            )
            return inbound_msg
        except Exception as e:
            logger.error(f"[IMAPInboxMonitor] Failed to process raw email: {e}")
            return None

    def _apply_classification_side_effects(
        self,
        msg: CommunicationMessage,
        target_thread_id: str,
        label: str,
        sender_email: str,
        bounced_email: Optional[str] = None,
    ) -> None:
        """Executes CRM, compliance suppression, bounce clearing, and thread state changes based on intent."""
        now_str = msg.created_at or "2026-08-21T00:00:00Z"
        thread = self.repo.get_thread(target_thread_id)
        if not thread:
            return

        business_id = thread.business_id

        if label == "UNSUBSCRIBE":
            # Suppress business immediately and permanently via OptOutManager
            suppress_target = sender_email if sender_email else ""
            self.optout.process_opt_out(email_address=suppress_target, thread_id=target_thread_id, reason="PROSPECT_UNSUBSCRIBE")

            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE businesses SET is_suppressed = 1, updated_at = ? WHERE id = ?",
                    (now_str, business_id),
                )
                append_event(
                    event_type="UNSUBSCRIBED",
                    entity_type="Business",
                    entity_id=business_id,
                    payload={"sender_email": sender_email, "thread_id": target_thread_id},
                    conn=conn,
                )
                conn.commit()
            finally:
                conn.close()

        elif label == "BOUNCE":
            # Record it so bounce_rate in ramp.py counts it (done via classification_label = 'BOUNCE')
            dead_addr = bounced_email or sender_email
            severity = classify_bounce_severity(f"{msg.subject or ''}\n{msg.body_text or ''}")
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                if severity == "hard":
                    # The address itself is invalid (5.x.x / user unknown /
                    # does not exist) - clear it so it is never retried, and
                    # cancel anything still queued against it.
                    cursor.execute(
                        "UPDATE businesses SET contact_email = NULL, updated_at = ? WHERE id = ?",
                        (now_str, business_id),
                    )
                    cursor.execute(
                        """
                        UPDATE email_drafts
                        SET status = 'CANCELLED', error_message = 'Bounced address cleared and suppressed', updated_at = ?
                        WHERE opportunity_id IN (SELECT id FROM opportunities WHERE business_id = ?)
                          AND status IN ('PENDING_APPROVAL', 'APPROVED')
                        """,
                        (now_str, business_id),
                    )
                # Soft bounces (4.x.x / mailbox full / deferred) are temporary:
                # the address may still be good, so it is left in place and
                # nothing queued against it is cancelled - only recorded.
                append_event(
                    event_type="EMAIL_BOUNCED",
                    entity_type="Business",
                    entity_id=business_id,
                    payload={"dead_address": dead_addr, "thread_id": target_thread_id, "severity": severity},
                    conn=conn,
                )
                conn.commit()
            finally:
                conn.close()

            # Only a hard bounce is terminal for the thread; a soft bounce may
            # still be delivered on retry, so the thread stays active.
            if severity == "hard" and thread.current_state != "FAILED":
                try:
                    self.repo.update_thread_state(target_thread_id, "FAILED")
                except Exception:
                    pass

        elif label == "POSITIVE":
            # Flag prominently for human follow-up. Do NOT auto-reply and do NOT auto-book.
            logger.info(
                f"[IMAPInboxMonitor] ******************************************************************\n"
                f"[IMAPInboxMonitor] *** POSITIVE REPLY RECEIVED from {sender_email} (Business ID: {business_id}) ***\n"
                f"[IMAPInboxMonitor] *** Subject: {msg.subject}\n"
                f"[IMAPInboxMonitor] *** Action Required: Human sales follow-up needed.\n"
                f"[IMAPInboxMonitor] ******************************************************************"
            )
            # Update thread state to REPLIED_POSITIVE
            try:
                self.repo.update_thread_state(target_thread_id, "REPLIED_POSITIVE")
            except Exception:
                pass

            # Cancel automated followups since human follow-up is now required
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE followup_schedules SET status = 'CANCELLED' WHERE thread_id = ? AND status = 'PENDING'",
                    (target_thread_id,),
                )
                append_event(
                    event_type="PROSPECT_REPLIED_POSITIVE",
                    entity_type="CommunicationThread",
                    entity_id=target_thread_id,
                    payload={
                        "sender_email": sender_email,
                        "business_id": business_id,
                        "subject": msg.subject,
                        "flagged_for_human": True,
                    },
                    conn=conn,
                )
                conn.commit()

                # Dispatch real-time Telegram push notification to founder's phone
                try:
                    cursor.execute("SELECT name, phone FROM businesses WHERE id = ?", (business_id,))
                    b_row = cursor.fetchone()
                    biz_name = b_row["name"] if b_row else "Unknown Business"
                    biz_phone = b_row["phone"] if b_row else ""
                    from leadforge.communication.telegram_notifier import send_telegram_alert
                    send_telegram_alert(
                        business_name=biz_name,
                        sender_email=sender_email,
                        phone=biz_phone,
                        subject=msg.subject,
                        body=msg.body_text,
                        thread_id=target_thread_id,
                    )
                except Exception as t_err:
                    logger.debug(f"[IMAPInboxMonitor] Telegram notification skipped/failed: {t_err}")
            finally:
                conn.close()

        elif label == "NEGATIVE":
            try:
                self.repo.update_thread_state(target_thread_id, "REPLIED_NEGATIVE")
            except Exception:
                pass
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE followup_schedules SET status = 'CANCELLED' WHERE thread_id = ? AND status = 'PENDING'",
                    (target_thread_id,),
                )
                append_event(
                    event_type="PROSPECT_REPLIED_NEGATIVE",
                    entity_type="CommunicationThread",
                    entity_id=target_thread_id,
                    payload={"sender_email": sender_email, "business_id": business_id},
                    conn=conn,
                )
                conn.commit()
            finally:
                conn.close()

        elif label == "NEUTRAL":
            try:
                self.repo.update_thread_state(target_thread_id, "REPLIED_NEUTRAL")
            except Exception:
                pass

        elif label == "OUT_OF_OFFICE":
            # Record only, do not change thread to terminal state or cancel followups
            logger.info(f"[IMAPInboxMonitor] Recorded OUT_OF_OFFICE notification from {sender_email}")
