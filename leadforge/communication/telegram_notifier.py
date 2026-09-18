"""Telegram Bot Alert Notification Service for LeadForge.

Sends real-time push alerts to the founder's phone whenever an inbound
email is classified as POSITIVE (interested prospect / hot lead).
"""

import os
import requests
from typing import Optional
from leadforge.utils import get_logger

logger = get_logger()


def send_telegram_alert(
    business_name: str,
    sender_email: str,
    phone: Optional[str] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> bool:
    """Dispatches an instant markdown alert to the configured Telegram chat."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.info(
            f"[TelegramNotifier] Skipping alert: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment. "
            f"Hot lead arrived from '{business_name}' ({sender_email})."
        )
        return False

    clean_subject = (subject or "No Subject").strip()
    clean_phone = (phone or "Not listed").strip()
    preview_body = (body or "").strip()
    if len(preview_body) > 400:
        preview_body = preview_body[:397] + "..."

    # Escape markdown special characters
    def _escape_md(text: str) -> str:
        for char in ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
            text = text.replace(char, f"\\{char}")
        return text

    message = (
        f"🚨 *HOT LEAD DETECTED — ORVION*\n\n"
        f"🏢 *Company:* {business_name}\n"
        f"✉️ *Email:* {sender_email}\n"
        f"📞 *Phone:* {clean_phone}\n"
        f"📌 *Subject:* {clean_subject}\n\n"
        f"💬 *Their Reply:*\n\"{preview_body}\"\n\n"
        f"👉 *Action:* Reply directly from your Gmail app on your phone!"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info(f"[TelegramNotifier] Successfully dispatched Telegram alert for lead '{business_name}'.")
            return True
        else:
            logger.warning(
                f"[TelegramNotifier] Telegram API error {resp.status_code}: {resp.text}"
            )
            return False
    except Exception as exc:
        logger.error(f"[TelegramNotifier] Failed to send Telegram alert: {exc}")
        return False
