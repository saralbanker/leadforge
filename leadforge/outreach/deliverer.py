import smtplib
import ssl
import socket
import threading
import time
import random
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import Optional, Union
from leadforge.config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    SMTP_FROM_NAME,
    SMTP_FROM_EMAIL,
    SMTP_USE_TLS,
    SMTP_REPLY_TO,
    SMTP_TIMEOUT,
    SMTP_CONFIGURED,
)
from leadforge.database import get_db_connection, append_event, uuidv7
from leadforge.utils import get_logger

logger = get_logger()


class SMTPEmailDeliverer:
    """Assembles and delivers outreach emails via SMTP with retry and rate-limit guardrails."""

    _delivery_lock = threading.Lock()

    def __init__(self) -> None:
        self.refresh_config()

    def refresh_config(self) -> dict:
        """Dynamically reloads SMTP settings from process environment and SQLite settings table,
        while honoring monkeypatched module variables in test suites.
        """
        from leadforge.config import get_smtp_config
        import leadforge.outreach.deliverer as deliv_mod
        cfg = get_smtp_config()

        module_configured = getattr(deliv_mod, "SMTP_CONFIGURED", False)

        self.host = cfg["host"] or getattr(deliv_mod, "SMTP_HOST", "") or ""
        self.port = cfg["port"] or getattr(deliv_mod, "SMTP_PORT", 587) or 587
        self.username = cfg["username"] or getattr(deliv_mod, "SMTP_USERNAME", "") or ""
        self.password = cfg["password"] or getattr(deliv_mod, "SMTP_PASSWORD", "") or ""
        self.from_name = cfg["from_name"] or getattr(deliv_mod, "SMTP_FROM_NAME", "Orvion") or "Orvion"
        self.from_email = cfg["from_email"] or getattr(deliv_mod, "SMTP_FROM_EMAIL", "") or ""
        use_tls_mod = getattr(deliv_mod, "SMTP_USE_TLS", None)
        self.use_tls = cfg["use_tls"] if cfg["is_configured"] else (use_tls_mod if use_tls_mod is not None else True)
        self.reply_to = cfg["reply_to"] or getattr(deliv_mod, "SMTP_REPLY_TO", "") or ""
        self.timeout = cfg["timeout"] or getattr(deliv_mod, "SMTP_TIMEOUT", 30) or 30

        self.is_configured = bool(cfg["is_configured"] or module_configured)
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "from_name": self.from_name,
            "from_email": self.from_email,
            "use_tls": self.use_tls,
            "reply_to": self.reply_to,
            "timeout": self.timeout,
            "is_configured": self.is_configured,
        }

    def _connect_and_send(self, msg: Union[MIMEText, MIMEMultipart], to_email: str) -> None:
        """Helper to manage single raw SMTP socket connection and sendmail execution."""
        logger.info(f"Connecting to SMTP server {self.host}:{self.port} (TLS: {self.use_tls})...")
        if self.use_tls:
            context = ssl.create_default_context()
            server = smtplib.SMTP(self.host, int(self.port), timeout=self.timeout)
            try:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(self.username, self.password)
                server.sendmail(self.from_email, to_email, msg.as_string())
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
        else:
            if int(self.port) == 465:
                server = smtplib.SMTP_SSL(self.host, int(self.port), timeout=self.timeout)
                try:
                    server.login(self.username, self.password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
                finally:
                    try:
                        server.quit()
                    except Exception:
                        pass
            else:
                server = smtplib.SMTP(self.host, int(self.port), timeout=self.timeout)
                try:
                    server.login(self.username, self.password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
                finally:
                    try:
                        server.quit()
                    except Exception:
                        pass

    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
    ) -> str:
        """Assembles and transmits a single outreach email securely with retry logic for 4xx errors.

        Returns:
            The RFC-compliant Message-ID header string.
        """
        cfg = self.refresh_config()
        if not cfg["is_configured"]:
            raise ValueError("SMTP is not configured. Please define SMTP environment variables or configure Settings.")

        # Assemble clean, RFC-compliant plain-text email envelope
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = to_email
        msg["Date"] = formatdate(localtime=True)
        msg["MIME-Version"] = "1.0"

        domain = self.from_email.split("@")[-1] if "@" in self.from_email else "leadforge.ai"
        msg_id = make_msgid(domain=domain)
        msg["Message-ID"] = msg_id

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        if self.reply_to:
            msg["Reply-To"] = self.reply_to

        unsub_contact = self.reply_to or self.from_email
        if unsub_contact:
            msg["List-Unsubscribe"] = f"<mailto:{unsub_contact}?subject=unsubscribe>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        max_attempts = 3
        backoff_base = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                self._connect_and_send(msg, to_email)
                logger.info(f"Email successfully delivered to {to_email}")
                return str(msg_id)
            except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused) as permanent_err:
                # Permanent non-retryable failures
                logger.error(f"Permanent SMTP failure for {to_email}: {permanent_err}")
                raise permanent_err
            except smtplib.SMTPResponseException as resp_err:
                code = getattr(resp_err, "smtp_code", 500)
                if 500 <= code < 600:
                    # 5xx permanent error: do not retry
                    logger.error(f"Permanent 5xx SMTP error ({code}) for {to_email}: {resp_err}")
                    raise resp_err
                # 4xx temporary error: retry up to max_attempts
                if attempt == max_attempts:
                    logger.error(f"Temporary 4xx SMTP error ({code}) for {to_email} exhausted {max_attempts} attempts: {resp_err}")
                    raise resp_err
                sleep_time = backoff_base * (2 ** (attempt - 1))
                logger.warning(f"Temporary 4xx SMTP error ({code}) for {to_email}. Retrying attempt {attempt + 1}/{max_attempts} in {sleep_time}s...")
                time.sleep(sleep_time)
            except (smtplib.SMTPException, socket.error, OSError, TimeoutError) as net_err:
                # Transient network/socket error: retry up to max_attempts
                if attempt == max_attempts:
                    logger.error(f"Transient network error for {to_email} exhausted {max_attempts} attempts: {net_err}")
                    raise net_err
                sleep_time = backoff_base * (2 ** (attempt - 1))
                logger.warning(f"Transient network error for {to_email}: {net_err}. Retrying attempt {attempt + 1}/{max_attempts} in {sleep_time}s...")
                time.sleep(sleep_time)

    def send_approved_drafts(
        self,
        max_sends: Optional[int] = None,
        enforce_content_validation: Optional[bool] = None,
    ) -> int:
        """Finds 'APPROVED' drafts in SQLite, checks daily limit and per-run cap, sends them, and updates statuses.

        Args:
            max_sends: Optional hard maximum number of emails to deliver in this single run.
            enforce_content_validation: Whether to run post-send content validation and trip breaker. Defaults to outreach.enforce_content_validation setting.

        Returns:
            Count of successfully delivered emails.
        """
        if not self._delivery_lock.acquire(blocking=False):
            logger.warning("SMTP email delivery is already in progress. Skipping duplicate execution.")
            return 0

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            from leadforge.repositories.settings import SettingsCache
            settings_cache = SettingsCache()

            if enforce_content_validation is None:
                enforce_content_validation = settings_cache.get_bool(
                    "outreach.enforce_content_validation", False
                )

            # Preflight safety: reject dispatch immediately if content circuit breaker is tripped
            from leadforge.outreach.circuit_breaker import is_content_circuit_breaker_tripped
            tripped, trip_reason = is_content_circuit_breaker_tripped(conn)
            if tripped:
                logger.critical(f"Content circuit breaker is TRIPPED: {trip_reason}. Halting dispatch.")
                conn.close()
                return 0

            # If max_sends not passed, check if a global max_batch_sends setting exists
            if max_sends is None:
                configured_batch_cap = settings_cache.get_int("outreach.max_batch_sends", 0)
                if configured_batch_cap > 0:
                    max_sends = configured_batch_cap

            # PH-002: Check daily send limit before starting batch.
            # The ceiling is the lower of the configured limit and the warm-up
            # ramp, and drops to zero outright if recent mail is bouncing.
            from leadforge.outreach.ramp import delivery_allowance

            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            cursor.execute(
                """
                SELECT COUNT(*) FROM email_drafts
                WHERE status = 'SENT' AND substr(sent_at, 1, 10) = ?
                """,
                (today_str,),
            )
            sent_today = cursor.fetchone()[0]

            allowance, allowance_reason = delivery_allowance(conn, settings_cache)
            logger.info(f"Delivery allowance: {allowance_reason}")
            # Express the allowance as an absolute ceiling so the per-item guard
            # below keeps working unchanged.
            daily_limit = sent_today + allowance

            if sent_today >= daily_limit:
                logger.warning(f"Outreach dispatch halted: {allowance_reason}")
                append_event(
                    event_type="DAILY_SEND_LIMIT_REACHED",
                    entity_type="System",
                    entity_id="outreach",
                    payload={"sent_today": sent_today, "daily_limit": daily_limit,
                             "reason": allowance_reason},
                    conn=conn,
                )
                conn.commit()
                conn.close()
                return 0

            cursor.execute(
                """
                SELECT ed.id, ed.recipient_email, ed.subject, ed.body, ed.campaign_name, ed.opportunity_id, o.business_id 
                FROM email_drafts ed
                LEFT JOIN opportunities o ON ed.opportunity_id = o.id
                WHERE ed.status = 'APPROVED'
                ORDER BY ed.created_at ASC
                """
            )
            drafts = cursor.fetchall()

            if not drafts:
                conn.close()
                return 0

            cap_msg = f" (capped to {max_sends} this run)" if max_sends is not None else ""
            logger.info(f"Found {len(drafts)} APPROVED email drafts to dispatch (sent today: {sent_today}/{daily_limit}){cap_msg}.")
            sent_count = 0
            delay = settings_cache.get_float("outreach.smtp_delay_seconds", 2.0)

            for idx, draft in enumerate(drafts):
                # Check per-run send cap
                if max_sends is not None and sent_count >= max_sends:
                    logger.info(f"Per-run send cap reached ({sent_count}/{max_sends}). Halting remaining sends.")
                    break

                # Check daily limit per item
                if sent_today >= daily_limit:
                    logger.warning(f"Daily send safety limit reached during dispatch ({sent_today}/{daily_limit}). Halting remaining sends.")
                    append_event(
                        event_type="DAILY_SEND_LIMIT_REACHED",
                        entity_type="System",
                        entity_id="outreach",
                        payload={"sent_today": sent_today, "daily_limit": daily_limit},
                        conn=conn,
                    )
                    conn.commit()
                    break

                if idx > 0 and delay > 0:
                    jitter = random.uniform(0, delay * 0.5)
                    total_delay = delay + jitter
                    logger.info(f"Throttling SMTP delivery: sleeping for {total_delay:.2f} seconds...")
                    time.sleep(total_delay)

                draft_id = draft["id"]
                to_email = draft["recipient_email"]
                subject = draft["subject"]
                body = draft["body"]
                campaign_name = draft["campaign_name"] or "Outreach"
                opp_id = draft["opportunity_id"]
                biz_id = draft["business_id"]

                # Suppression is a pre-dispatch gate.  Do this before opening an
                # SMTP connection, and check both the business record and the
                # address-level list because old drafts may not have an
                # opportunity/business join.
                is_suppressed = False
                if biz_id:
                    cursor.execute("SELECT is_suppressed FROM businesses WHERE id = ?", (biz_id,))
                    b_supp_row = cursor.fetchone()
                    is_suppressed = bool(b_supp_row and b_supp_row["is_suppressed"])
                if not is_suppressed and to_email:
                    cursor.execute(
                        "SELECT 1 FROM unsubscribe_suppressions WHERE LOWER(email) = ?",
                        (to_email.strip().lower(),),
                    )
                    is_suppressed = cursor.fetchone() is not None
                if is_suppressed:
                    logger.warning(f"Skipping draft {draft_id}: recipient {to_email} is suppressed. Marking CANCELLED.")
                    cursor.execute(
                        "UPDATE email_drafts SET status = 'CANCELLED', error_message = 'Recipient suppressed before dispatch', updated_at = ? WHERE id = ?",
                        (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), draft_id),
                    )
                    conn.commit()
                    continue

                # Deduplication guard: Never send if this recipient already received an email
                cursor.execute(
                    "SELECT 1 FROM email_drafts WHERE LOWER(recipient_email) = ? AND status = 'SENT' AND id != ?",
                    (to_email.strip().lower(), draft_id)
                )
                if cursor.fetchone():
                    logger.warning(f"Skipping draft {draft_id}: recipient {to_email} already received an email. Marking CANCELLED.")
                    cursor.execute("UPDATE email_drafts SET status = 'CANCELLED', error_message = 'Duplicate recipient already sent', updated_at = ? WHERE id = ?",
                                   (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), draft_id))
                    conn.commit()
                    continue

                try:
                    msg_id = self.send_email(to_email, subject, body)

                    # Update SQLite to SENT
                    sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    cursor.execute(
                        """
                        UPDATE email_drafts 
                        SET status = 'SENT', sent_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (sent_at, sent_at, draft_id),
                    )

                    # Resolve business_id if missing from opportunity join
                    if not biz_id and to_email:
                        cursor.execute(
                            "SELECT id FROM businesses WHERE LOWER(contact_email) = ? ORDER BY created_at DESC LIMIT 1",
                            (to_email.strip().lower(),),
                        )
                        b_row = cursor.fetchone()
                        if b_row:
                            biz_id = b_row["id"]

                    if biz_id:
                        # Find or create communication thread (reuse if existing, never create a second)
                        cursor.execute(
                            "SELECT id, current_state FROM communication_threads WHERE business_id = ? ORDER BY created_at DESC LIMIT 1",
                            (biz_id,),
                        )
                        t_row = cursor.fetchone()
                        if t_row:
                            thread_id = t_row["id"]
                            cursor.execute(
                                """
                                UPDATE communication_threads 
                                SET current_state = 'AWAITING_REPLY', last_activity_at = ?, updated_at = ? 
                                WHERE id = ?
                                """,
                                (sent_at, sent_at, thread_id),
                            )
                        else:
                            thread_id = uuidv7()
                            cursor.execute(
                                """
                                INSERT INTO communication_threads (
                                    id, business_id, opportunity_id, campaign_name, current_state, last_activity_at, created_at, updated_at
                                ) VALUES (?, ?, ?, ?, 'AWAITING_REPLY', ?, ?, ?)
                                """,
                                (thread_id, biz_id, opp_id, campaign_name, sent_at, sent_at, sent_at),
                            )

                        # Record outbound message in communication_messages with RFC Message-ID
                        header_id = str(msg_id) if msg_id is not None else None
                        cursor.execute(
                            """
                            INSERT INTO communication_messages (
                                id, thread_id, direction, message_id_header, sender_email, recipient_email, subject, body_text, prompt_version, created_at
                            ) VALUES (?, ?, 'OUTBOUND', ?, ?, ?, ?, ?, 'initial_v1', ?)
                            """,
                            (uuidv7(), thread_id, header_id, self.from_email or "outreach@leadforge.ai", to_email, subject, body, sent_at),
                        )

                        # Schedule Touch 2 follow-up if business is not suppressed
                        if not is_suppressed:
                            max_touches = settings_cache.get_int(
                                "outreach.max_sequence_touches",
                                settings_cache.get_int("outreach.max_touches", settings_cache.get_int("outreach.followup_max_touches", 3)),
                            )
                            if max_touches >= 2:
                                cursor.execute(
                                    "SELECT 1 FROM followup_schedules WHERE thread_id = ? AND status = 'PENDING'",
                                    (thread_id,),
                                )
                                if not cursor.fetchone():
                                    step2_delay = settings_cache.get_int(
                                        "outreach.followup_step2_delay_days",
                                        settings_cache.get_int("outreach.followup_delay_days_step2", 3),
                                    )
                                    sched_dt = datetime.now(timezone.utc) + timedelta(days=step2_delay)
                                    sched_for = sched_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                                    sched_id = uuidv7()
                                    cursor.execute(
                                        """
                                        INSERT INTO followup_schedules (
                                            id, thread_id, sequence_step, scheduled_for, status, trigger_reason, created_at
                                        ) VALUES (?, ?, 2, ?, 'PENDING', 'AWAITING_REPLY', ?)
                                        """,
                                        (sched_id, thread_id, sched_for, sent_at),
                                    )
                                    append_event(
                                        event_type="FOLLOWUP_SCHEDULED",
                                        entity_type="FollowupSchedule",
                                        entity_id=sched_id,
                                        payload={"thread_id": thread_id, "sequence_step": 2, "scheduled_for": sched_for},
                                        conn=conn,
                                    )

                    append_event(
                        event_type="EMAIL_SENT",
                        entity_type="EmailDraft",
                        entity_id=draft_id,
                        payload={"recipient_email": to_email, "sent_at": sent_at},
                        conn=conn,
                    )
                    conn.commit()
                    sent_count += 1
                    sent_today += 1

                    # Immediate post-send content validation & circuit breaker check
                    if enforce_content_validation:
                        try:
                            from leadforge.outreach.circuit_breaker import (
                                validate_draft_content,
                                trip_content_circuit_breaker,
                            )
                            biz_city = ""
                            biz_website = ""
                            biz_name = ""
                            if biz_id:
                                cursor.execute(
                                    """
                                    SELECT b.name, b.website_domain, a.city
                                    FROM businesses b
                                    LEFT JOIN addresses a ON a.business_id = b.id
                                    WHERE b.id = ?
                                    LIMIT 1
                                    """,
                                    (biz_id,),
                                )
                                bz_row = cursor.fetchone()
                                if bz_row:
                                    biz_name = bz_row["name"] or ""
                                    biz_city = bz_row["city"] or ""
                                    biz_website = bz_row["website_domain"] or ""

                            content_valid, content_issues = validate_draft_content(
                                body=body,
                                subject=subject,
                                city=biz_city,
                                has_website=bool(biz_website),
                                business_name=biz_name,
                            )
                            if not content_valid:
                                reason = f"Draft {draft_id} to {to_email} violated content standards post-dispatch: {'; '.join(content_issues)}"
                                logger.critical(f"TRIPPING CONTENT CIRCUIT BREAKER: {reason}")
                                trip_content_circuit_breaker(conn, reason=reason, draft_id=draft_id)
                                break
                        except Exception as cb_err:
                            logger.warning(f"Error during post-send circuit breaker check: {cb_err}")
                except Exception as e:
                    err_msg = str(e)
                    logger.error(f"Failed SMTP send for draft {draft_id} to {to_email}: {err_msg}")

                    # Update SQLite to FAILED
                    failed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    cursor.execute(
                        """
                        UPDATE email_drafts 
                        SET status = 'FAILED', error_message = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (err_msg, failed_at, draft_id),
                    )
                    append_event(
                        event_type="EMAIL_SEND_FAILED",
                        entity_type="EmailDraft",
                        entity_id=draft_id,
                        payload={"recipient_email": to_email, "error_message": err_msg},
                        conn=conn,
                    )
                    conn.commit()

            conn.close()
            return sent_count
        finally:
            self._delivery_lock.release()
