import smtplib
import ssl
import socket
import threading
import time
import random
from datetime import datetime, timezone
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
from leadforge.database import get_db_connection, append_event
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

    def send_email(self, to_email: str, subject: str, body: str) -> None:
        """Assembles and transmits a single outreach email securely with retry logic for 4xx errors."""
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
        msg["Message-ID"] = make_msgid(domain=domain)

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
                return
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

    def send_approved_drafts(self) -> int:
        """Finds 'APPROVED' drafts in SQLite, checks daily limit, sends them, and updates statuses.

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
            daily_limit = settings_cache.get_int("outreach.daily_send_limit", 20)

            # PH-002: Check daily send limit before starting batch
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            cursor.execute(
                """
                SELECT COUNT(*) FROM email_drafts
                WHERE status = 'SENT' AND substr(sent_at, 1, 10) = ?
                """,
                (today_str,),
            )
            sent_today = cursor.fetchone()[0]

            if sent_today >= daily_limit:
                logger.warning(f"Daily send safety limit reached ({sent_today}/{daily_limit}). Halting outreach dispatch.")
                append_event(
                    event_type="DAILY_SEND_LIMIT_REACHED",
                    entity_type="System",
                    entity_id="outreach",
                    payload={"sent_today": sent_today, "daily_limit": daily_limit},
                    conn=conn,
                )
                conn.commit()
                conn.close()
                return 0

            cursor.execute(
                """
                SELECT id, recipient_email, subject, body 
                FROM email_drafts 
                WHERE status = 'APPROVED'
                ORDER BY created_at ASC
                """
            )
            drafts = cursor.fetchall()

            if not drafts:
                conn.close()
                return 0

            logger.info(f"Found {len(drafts)} APPROVED email drafts to dispatch (sent today: {sent_today}/{daily_limit}).")
            sent_count = 0
            delay = settings_cache.get_float("outreach.smtp_delay_seconds", 2.0)

            for idx, draft in enumerate(drafts):
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

                try:
                    self.send_email(to_email, subject, body)

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
