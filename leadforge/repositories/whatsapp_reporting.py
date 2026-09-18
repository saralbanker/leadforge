"""WhatsApp Outreach Reporting Repository (Read-Only Bridge).

Allows LeadForge CLI reports and server APIs to inspect WhatsApp outreach status
without mutating or interfering with either database.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, Optional

# Default path to whatsapp_outreach.db within leadforge repository
DEFAULT_WA_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "whatsapp_auto"
    / "whatsapp_outreach.db"
)


def get_whatsapp_db_path() -> Path:
    """Resolves WhatsApp outreach database path."""
    env_path = os.environ.get("WHATSAPP_OUTREACH_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_WA_DB_PATH


def get_whatsapp_summary(db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Reads summary metrics from whatsapp_outreach.db in read-only mode.

    Returns None gracefully if the database does not exist or cannot be read.
    """
    target_path = db_path or get_whatsapp_db_path()
    if not target_path.exists():
        return None

    try:
        # Use read-only URI mode to ensure zero lock contention
        uri = f"file:{target_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Check if wa_contacts table exists
        cur.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='wa_contacts'"
        )
        if cur.fetchone()[0] == 0:
            conn.close()
            return None

        # Total contacts and status breakdown
        status_rows = cur.execute(
            "SELECT status, COUNT(*) FROM wa_contacts GROUP BY status"
        ).fetchall()
        status_counts = {row[0]: row[1] for row in status_rows}
        total_contacts = sum(status_counts.values())

        # Dispatches today and total dispatches
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='wa_dispatch_logs'"
        )
        has_logs = cur.fetchone()[0] > 0

        sent_today = 0
        total_sent = 0
        total_replies = 0
        if has_logs:
            cur.execute(
                "SELECT COUNT(*) FROM wa_dispatch_logs WHERE dispatch_status = 'SENT' AND substr(dispatched_at, 1, 10) = ?",
                (today_prefix,),
            )
            sent_today = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM wa_dispatch_logs WHERE dispatch_status = 'SENT'"
            )
            total_sent = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM wa_dispatch_logs WHERE response_received = 1"
            )
            total_replies = cur.fetchone()[0]

        conn.close()

        return {
            "total_contacts": total_contacts,
            "pending": status_counts.get("PENDING", 0),
            "sent": status_counts.get("SENT", total_sent),
            "sent_today": sent_today,
            "total_sent": total_sent,
            "replied": max(status_counts.get("REPLIED", 0), total_replies),
            "opt_outs": status_counts.get("OPT_OUT", 0),
            "invalid": status_counts.get("INVALID", 0),
            "status_counts": status_counts,
        }
    except Exception:
        return None
