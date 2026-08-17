"""IMAP Inbox Monitor & Inbound Message Ingestion Engine."""

import email
from email.message import Message
from typing import Optional
from leadforge.communication.repository import SQLiteCommunicationRepository
from leadforge.communication.base import CommunicationMessage
from leadforge.utils import get_logger

logger = get_logger()


class IMAPInboxMonitor:
    """Monitors incoming emails, parses threading headers, and ingests into communication repository."""

    def __init__(self, repository: Optional[SQLiteCommunicationRepository] = None):
        self.repo = repository or SQLiteCommunicationRepository()

    def process_inbound_raw_email(
        self, raw_email_bytes: bytes, thread_id: Optional[str] = None
    ) -> Optional[CommunicationMessage]:
        """Parses raw MIME email bytes, matches thread, and persists inbound message.

        Args:
            raw_email_bytes: Bytes of the raw email message.
            thread_id: Optional explicit thread ID if known.

        Returns:
            Created CommunicationMessage or None if processing fails.
        """
        try:
            msg: Message = email.message_from_bytes(raw_email_bytes)

            sender = msg.get("From", "").strip()
            recipient = msg.get("To", "").strip()
            subject = msg.get("Subject", "").strip()
            message_id = msg.get("Message-ID", "").strip()

            # Clean email addresses
            if "<" in sender and ">" in sender:
                sender = sender.split("<")[1].split(">")[0].strip()
            if "<" in recipient and ">" in recipient:
                recipient = recipient.split("<")[1].split(">")[0].strip()

            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode(errors="ignore")
                            break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(errors="ignore")

            # Resolve thread ID if not provided explicitly
            target_thread_id = thread_id
            if not target_thread_id and sender:
                matched_thread = self.repo.find_thread_by_email(sender)
                if matched_thread:
                    target_thread_id = matched_thread.id

            if not target_thread_id:
                logger.warning(f"[IMAPInboxMonitor] Unable to resolve thread for inbound message from {sender}")
                return None

            inbound_msg = self.repo.add_message(
                thread_id=target_thread_id,
                direction="INBOUND",
                sender_email=sender,
                recipient_email=recipient,
                subject=subject,
                body_text=body_text,
                message_id_header=message_id,
            )

            logger.info(f"[IMAPInboxMonitor] Successfully ingested inbound message {inbound_msg.id} for thread {target_thread_id}")
            return inbound_msg
        except Exception as e:
            logger.error(f"[IMAPInboxMonitor] Failed to process raw email: {e}")
            return None
