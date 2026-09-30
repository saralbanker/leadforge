"""Post-dispatch content validation circuit breaker.

Protects against silent multi-week delivery of defective, ungrounded, or
misformatted cold email copy during unattended/scheduled runs.

If a scheduled run's dispatched draft fails EmailQualityEngine validation
(e.g. body outside 40-60 core words, duplicate city mentions, missing bridge,
or oversized subject), this circuit breaker trips immediately, aborts any
further sending in the batch, and locks future scheduled runs until a human
inspects and clears the breaker.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from leadforge.database import append_event, get_db_connection
from leadforge.outreach.quality import EmailQualityEngine
from leadforge.utils import get_logger

logger = get_logger()

SETTING_BREAKER_TRIPPED = "outreach.content_breaker_tripped"
SETTING_BREAKER_REASON = "outreach.content_breaker_reason"
SETTING_BREAKER_TRIPPED_AT = "outreach.content_breaker_tripped_at"
SETTING_BREAKER_CLEARED_AT = "outreach.content_breaker_cleared_at"


def validate_draft_content(
    body: str,
    subject: str,
    city: str = "",
    has_website: bool = True,
    scraped_text: str = "",
    business_name: str = "",
    is_usable: bool = True,
) -> Tuple[bool, List[str]]:
    """Validates an email draft against the strict five-stage content standards.

    Verifies:
      1. Core word count is within the 40-60 word budget.
      2. Subject line length is <= 50 characters.
      3. No duplicate location / city mentions in the opening sentences.
      4. Grounded bridge sentence is present and non-empty.
      5. EmailQualityEngine body and subject gates pass.
      6. The sent envelope (greeting, sender sign-off, compliance footer) is present.
    """
    issues: List[str] = []

    # 0. Envelope: this is the check that catches a body missing its greeting,
    # "Saral Banker, Orvion" sign-off, or CAN-SPAM footer before it is ever
    # approved or sent (see P0-3/P0-4 - 2026-09-24 sent mail had none of these).
    envelope_valid, envelope_issues = EmailQualityEngine.validate_envelope(body)
    if not envelope_valid:
        issues.extend(envelope_issues)

    # 1. Subject validation
    subj_valid, subj_issues = EmailQualityEngine.validate_subject(
        subject=subject,
        business_name=business_name,
    )
    if not subj_valid:
        issues.extend(subj_issues)

    if len(subject or "") > 50:
        issues.append(f"Subject length {len(subject)} exceeds 50-character budget.")

    # 2. Body validation
    body_valid, body_issues = EmailQualityEngine.validate_body(
        body=body,
        city=city,
        has_website=has_website,
    )
    if not body_valid:
        issues.extend(body_issues)

    core = EmailQualityEngine._core_body(body)
    word_count = len(core.split())
    if word_count < 40 or word_count > 60:
        issues.append(f"Core word count {word_count} is outside the strict 40-60 word budget.")

    # 3. Bridge validation
    paras = [p.strip() for p in core.split("\n\n") if p.strip()]
    if len(paras) < 2:
        issues.append("Missing second paragraph containing grounded contact bridge.")
    else:
        bridge_sentence = paras[1].split(". ")[0].strip()
        if not bridge_sentence:
            issues.append("Contact bridge sentence is empty.")
        else:
            bridge_valid, bridge_issues = EmailQualityEngine.validate_bridge(
                bridge=bridge_sentence,
                is_usable=is_usable,
                has_website=has_website,
                city=city,
            )
            if not bridge_valid:
                issues.extend(bridge_issues)

    return (len(issues) == 0, issues)


def trip_content_circuit_breaker(
    conn: sqlite3.Connection,
    reason: str,
    draft_id: Optional[str] = None,
) -> None:
    """Trips the content circuit breaker and persists failure state to settings."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, 'true', ?)
        ON CONFLICT(key) DO UPDATE SET value = 'true', updated_at = excluded.updated_at
        """,
        (SETTING_BREAKER_TRIPPED, now_iso),
    )
    cur.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (SETTING_BREAKER_REASON, reason, now_iso),
    )
    cur.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (SETTING_BREAKER_TRIPPED_AT, now_iso, now_iso),
    )

    try:
        append_event(
            event_type="CONTENT_CIRCUIT_BREAKER_TRIPPED",
            entity_type="System",
            entity_id=draft_id or "outreach",
            payload={"reason": reason, "tripped_at": now_iso, "draft_id": draft_id},
            conn=conn,
        )
    except Exception as e:
        logger.warning(f"Could not append event for circuit breaker: {e}")

    conn.commit()
    logger.critical(f"Content circuit breaker TRIPPED: {reason}")


def clear_content_circuit_breaker(
    conn: sqlite3.Connection,
    cleared_by: str = "human_operator",
) -> None:
    """Clears the tripped content circuit breaker, re-arming it for future runs."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, 'false', ?)
        ON CONFLICT(key) DO UPDATE SET value = 'false', updated_at = excluded.updated_at
        """,
        (SETTING_BREAKER_TRIPPED, now_iso),
    )
    cur.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, '', ?)
        ON CONFLICT(key) DO UPDATE SET value = '', updated_at = excluded.updated_at
        """,
        (SETTING_BREAKER_REASON, now_iso),
    )
    cur.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (SETTING_BREAKER_CLEARED_AT, now_iso, now_iso),
    )

    try:
        append_event(
            event_type="CONTENT_CIRCUIT_BREAKER_CLEARED",
            entity_type="System",
            entity_id="outreach",
            payload={"cleared_by": cleared_by, "cleared_at": now_iso},
            conn=conn,
        )
    except Exception as e:
        logger.warning(f"Could not append event for circuit breaker clear: {e}")

    conn.commit()
    logger.info("Content circuit breaker cleared by operator.")


def audit_recent_sent_drafts(
    conn: sqlite3.Connection,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Audits the most recent SENT drafts to verify content compliance."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ed.id, ed.recipient_email, ed.subject, ed.body, ed.sent_at,
               b.name as business_name, a.city, b.website_domain
        FROM email_drafts ed
        LEFT JOIN opportunities o ON ed.opportunity_id = o.id
        LEFT JOIN businesses b ON o.business_id = b.id
        LEFT JOIN addresses a ON a.business_id = b.id
        WHERE ed.status = 'SENT'
        ORDER BY COALESCE(ed.sent_at, ed.updated_at) DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    violations = []
    for r in rows:
        valid, issues = validate_draft_content(
            body=r["body"] or "",
            subject=r["subject"] or "",
            city=r["city"] or "",
            has_website=bool(r["website_domain"]),
            business_name=r["business_name"] or "",
        )
        if not valid:
            violations.append({
                "draft_id": r["id"],
                "recipient": r["recipient_email"],
                "sent_at": r["sent_at"],
                "issues": issues,
            })
    return violations


def is_content_circuit_breaker_tripped(
    conn: sqlite3.Connection,
    settings_cache: Any = None,
) -> Tuple[bool, str]:
    """Checks whether the content circuit breaker is currently tripped.

    Returns (is_tripped, reason).
    """
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (SETTING_BREAKER_TRIPPED,))
    row = cur.fetchone()
    is_tripped = bool(row and str(row[0]).strip().lower() in ("true", "1", "yes"))

    if is_tripped:
        cur.execute("SELECT value FROM settings WHERE key = ?", (SETTING_BREAKER_REASON,))
        reason_row = cur.fetchone()
        reason = reason_row[0] if reason_row and reason_row[0] else "Content quality violation detected."
        return True, reason

    return False, ""
