"""Send-rate ramp and bounce circuit breaker.

Cold email from a fresh `@gmail.com` sender fails in two ways: volume that jumps
from nothing to hundreds looks like a compromised account, and a bad list burns
sender reputation faster than any copy change can repair it. Both failures are
silent - Gmail does not tell you it started spam-foldering you.

So delivery is bounded by two independent gates, and the lower one always wins:

  * a ramp, which raises the ceiling on a fixed schedule counted from the first
    real send, and
  * a circuit breaker, which drops the ceiling to zero when recent mail is
    bouncing above a threshold.

Both read their configuration from the `settings` table so they can be retuned
without a deploy.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Optional, Tuple

from leadforge.utils import get_logger

logger = get_logger()

# day-offset:ceiling pairs, counted from the first SENT draft (day 1).
# Deliberately conservative: this sender already carries 2 hard bounces from
# fabricated addresses, and has no custom domain to fall back on.
DEFAULT_RAMP_SCHEDULE = "1:10,8:20,15:30,22:40"

# Trailing sends inspected by the breaker, and the bounce fraction that trips it.
DEFAULT_BOUNCE_WINDOW = 50
DEFAULT_BOUNCE_THRESHOLD = 0.08  # 8%


def parse_ramp_schedule(raw: str) -> list[tuple[int, int]]:
    """Parses "1:10,8:20" into [(1, 10), (8, 20)], sorted by day, bad pairs dropped."""
    steps: list[tuple[int, int]] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        day_raw, limit_raw = chunk.split(":", 1)
        try:
            steps.append((int(day_raw), int(limit_raw)))
        except ValueError:
            logger.warning(f"Ignoring malformed ramp step {chunk!r}.")
    return sorted(steps)


def _first_send_date(conn: sqlite3.Connection) -> Optional[date]:
    row = conn.execute(
        "SELECT MIN(substr(sent_at, 1, 10)) FROM email_drafts "
        "WHERE status = 'SENT' AND sent_at IS NOT NULL"
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        return datetime.strptime(row[0], "%Y-%m-%d").date()
    except ValueError:
        return None


def ramp_ceiling(conn: sqlite3.Connection, schedule_raw: str, today: Optional[date] = None) -> int:
    """Ceiling permitted by the ramp today.

    Day 1 is the date of the first ever send. Before any send has happened the
    schedule's first step applies, so an untouched system starts at the bottom
    of the ramp rather than at the configured maximum.
    """
    steps = parse_ramp_schedule(schedule_raw)
    if not steps:
        return 0
    today = today or datetime.now(timezone.utc).date()
    first = _first_send_date(conn)
    day_index = 1 if first is None else (today - first).days + 1

    ceiling = steps[0][1]
    for start_day, limit in steps:
        if day_index >= start_day:
            ceiling = limit
        else:
            break
    return ceiling


def bounce_rate(conn: sqlite3.Connection, window: int) -> Tuple[float, int, int]:
    """Bounce fraction over the last `window` sends.

    Counts *addresses that went bad*, not bounce notifications. A single dead
    address can generate dozens of mailer-daemon replies - the live inbox held 25
    for one business - and counting those individually would peg the rate at
    several hundred percent and wedge the breaker shut forever.

    Two signals are combined, both scoped to the drafts in the window:
      * drafts SMTP rejected outright (status FAILED), and
      * drafts whose business has a BOUNCE-classified inbound message.
    A draft matching both is counted once.
    """
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(email_drafts)").fetchall()}
        has_updated_at = "updated_at" in cols
    except Exception:
        has_updated_at = False

    if has_updated_at:
        recent = conn.execute(
            "SELECT id, status FROM email_drafts "
            "WHERE status IN ('SENT', 'FAILED') AND (sent_at IS NOT NULL OR (status = 'FAILED' AND updated_at IS NOT NULL)) "
            "ORDER BY COALESCE(sent_at, updated_at) DESC LIMIT ?",
            (window,),
        ).fetchall()
    else:
        recent = conn.execute(
            "SELECT id, status FROM email_drafts "
            "WHERE status IN ('SENT', 'FAILED') AND sent_at IS NOT NULL "
            "ORDER BY sent_at DESC LIMIT ?",
            (window,),
        ).fetchall()
    if not recent:
        return 0.0, 0, 0

    ids = [r[0] for r in recent]
    total = len(ids)
    placeholders = ",".join("?" * total)

    bad_ids = {r[0] for r in recent if r[1] == "FAILED"}

    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT d.id FROM email_drafts d
            JOIN opportunities o ON o.id = d.opportunity_id
            JOIN communication_threads t ON t.business_id = o.business_id
            JOIN communication_messages m ON m.thread_id = t.id
            WHERE d.id IN ({placeholders})
              AND m.classification_label = 'BOUNCE'
            """,
            ids,
        ).fetchall()
        bad_ids.update(r[0] for r in rows)
    except sqlite3.Error:
        # Reply tables may not exist yet; SMTP failures alone still guard us.
        pass

    bad = len(bad_ids)
    return (bad / total if total else 0.0), bad, total


def delivery_allowance(conn: sqlite3.Connection, settings_cache) -> Tuple[int, str]:
    """Resolves how many emails may still go out today, and why.

    Returns (allowance, reason). An allowance of 0 means do not send.
    """
    configured = settings_cache.get_int("outreach.daily_send_limit", 20)
    schedule_raw = settings_cache.get_str("outreach.ramp_schedule", DEFAULT_RAMP_SCHEDULE)
    window = settings_cache.get_int("outreach.bounce_window", DEFAULT_BOUNCE_WINDOW)
    threshold = settings_cache.get_float("outreach.bounce_threshold", DEFAULT_BOUNCE_THRESHOLD)

    rate, bad, total = bounce_rate(conn, window)
    # Needs a meaningful sample and at least 2 failures to prevent an isolated single bounce from wedging the breaker forever
    if total >= 10 and bad >= 2 and rate > threshold:
        return 0, (
            f"circuit breaker open: {bad}/{total} recent sends bounced "
            f"({rate:.0%} > {threshold:.0%})"
        )

    ramp = ramp_ceiling(conn, schedule_raw)
    ceiling = min(configured, ramp)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent_today = conn.execute(
        "SELECT COUNT(*) FROM email_drafts "
        "WHERE status = 'SENT' AND substr(sent_at, 1, 10) = ?",
        (today_str,),
    ).fetchone()[0]

    remaining = max(0, ceiling - sent_today)
    limiter = "ramp" if ramp < configured else "configured limit"
    return remaining, (
        f"{remaining} left today (sent {sent_today}/{ceiling}, bound by {limiter}; "
        f"bounce {rate:.0%} of last {total})"
    )
