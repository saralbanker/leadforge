"""Read-only pre-send eligibility report for approved outreach drafts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable, Optional

from leadforge.config import get_smtp_config
from leadforge.database import get_db_connection
from leadforge.enrichment.aggregator import EmailCandidateAggregator
from leadforge.normalizer import is_valid_recipient_email
from leadforge.outreach.ramp import delivery_allowance
from leadforge.repositories.settings import SettingsCache


async def build_dry_run_report(draft_ids: Optional[Iterable[str]] = None) -> dict:
    """Return dispatch eligibility counts without updating drafts or sending SMTP.

    MX checks are deliberately performed anew so this can be run immediately
    before a real batch, rather than trusting a historical enrichment result.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        ids = list(draft_ids or [])
        query = """
            SELECT ed.id, ed.recipient_email, o.business_id
            FROM email_drafts ed
            LEFT JOIN opportunities o ON o.id = ed.opportunity_id
            WHERE ed.status = 'APPROVED'
        """
        params: list[str] = []
        if ids:
            query += " AND ed.id IN ({})".format(",".join("?" for _ in ids))
            params = ids
        rows = cursor.execute(query, params).fetchall()

        mx_checker = EmailCandidateAggregator(verify_mx=True)
        domains = {
            (row["recipient_email"] or "").strip().lower().rsplit("@", 1)[-1]
            for row in rows if "@" in (row["recipient_email"] or "")
        }

        async def check_domain(domain: str) -> tuple[str, bool]:
            try:
                # A dry-run must finish even when a recursive DNS server is
                # unavailable.  A timeout is conservatively treated as fail.
                return domain, await asyncio.wait_for(mx_checker._check_domain_has_mx(domain), timeout=5)
            except (asyncio.TimeoutError, Exception):
                return domain, False

        mx_by_domain = dict(await asyncio.gather(*(check_domain(domain) for domain in domains)))
        counts = {"approved": len(rows), "mx_pass": 0, "mx_failed": 0, "deduplicated": 0, "suppressed": 0, "malformed": 0}
        eligible = 0
        for row in rows:
            raw_email = row["recipient_email"] or ""
            is_valid, _ = is_valid_recipient_email(raw_email)
            if not is_valid:
                counts["malformed"] += 1
                continue

            email = raw_email.strip().lower()
            domain = email.rsplit("@", 1)[-1] if "@" in email else ""
            if not mx_by_domain.get(domain, False):
                counts["mx_failed"] += 1
                continue
            counts["mx_pass"] += 1

            suppressed = False
            if row["business_id"]:
                business = cursor.execute(
                    "SELECT is_suppressed FROM businesses WHERE id = ?", (row["business_id"],)
                ).fetchone()
                suppressed = bool(business and business["is_suppressed"])
            if not suppressed:
                suppressed = cursor.execute(
                    "SELECT 1 FROM unsubscribe_suppressions WHERE LOWER(email) = ?", (email,)
                ).fetchone() is not None
            if suppressed:
                counts["suppressed"] += 1
                continue

            duplicate = cursor.execute(
                "SELECT 1 FROM email_drafts WHERE LOWER(recipient_email) = ? AND status = 'SENT' AND id != ?",
                (email, row["id"]),
            ).fetchone() is not None
            if duplicate:
                counts["deduplicated"] += 1
                continue
            eligible += 1

        settings = SettingsCache()
        allowance, allowance_reason = delivery_allowance(conn, settings)
        smtp = get_smtp_config(settings)
        counts.update({
            "eligible": eligible,
            "effective_send_count": min(eligible, allowance),
            "daily_remaining": allowance,
            "daily_limit": settings.get_int("outreach.daily_send_limit", 20),
            "allowance_reason": allowance_reason,
            "smtp_from_email": smtp["from_email"],
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        return counts
    finally:
        conn.close()


def format_dry_run_report(report: dict) -> str:
    """Stable human-readable CLI output, intentionally excluding credentials."""
    return "\n".join([
        "Outreach pre-send dry run (no email sent)",
        f"Generated: {report['generated_at']}",
        f"Resolved SMTP from-address: {report['smtp_from_email'] or '(not configured)'}",
        f"Approved drafts inspected: {report['approved']}",
        f"MX: {report['mx_pass']} pass, {report['mx_failed']} fail",
        f"Suppressed: {report['suppressed']}",
        f"Deduplicated (already sent): {report['deduplicated']}",
        f"Eligible to dispatch: {report['eligible']}",
        f"Daily limit: {report['daily_limit']}; remaining allowance: {report['daily_remaining']}",
        f"Effective send count: {report['effective_send_count']}",
        f"Allowance detail: {report['allowance_reason']}",
    ])
