"""Daily outreach run: lead supply -> drafts -> quality gate -> bounded send.

Every stage below already existed and was driven by hand. This script is the
missing scheduler: it runs them in order, refuses to continue when a dependency
is unhealthy, and never sends more than the ramp allows.

It is deliberately boring and deterministic. Judgement calls (copy changes,
whether to widen the ramp, what to do about a reply) are left to a human or to
the Claude session that launches this.

Usage:
    python scripts/daily_outreach.py                # full run
    python scripts/daily_outreach.py --no-send      # everything except delivery
    python scripts/daily_outreach.py --pairs 6      # widen lead discovery
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Deliberately not 8000: that port is taken by an unrelated service on this
# machine, and older orphaned LeadForge servers are still listening on 8010 and
# 8099. Talking to the wrong app, or to a stale build, is worse than not running.
LEADFORGE_PORT = int(os.environ.get("LEADFORGE_PORT", "8123"))
API = os.environ.get("LEADFORGE_API", f"http://127.0.0.1:{LEADFORGE_PORT}")
SERVER_LOG = BASE / "logs" / "server.log"


def log(stage: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {stage:<9} {msg}", flush=True)


# ---------------------------------------------------------------- preflight

def ensure_ollama() -> bool:
    """Copy generation is refused outright when the hook falls back, so a dead
    Ollama means an entire run of rejected drafts. Check it before doing work."""
    try:
        httpx.get("http://localhost:11434/api/tags", timeout=10).raise_for_status()
        return True
    except Exception:
        log("preflight", "ollama down, starting user service ...")
        subprocess.run(["systemctl", "--user", "start", "ollama"], capture_output=True)
        for _ in range(20):
            time.sleep(3)
            try:
                httpx.get("http://localhost:11434/api/tags", timeout=5).raise_for_status()
                log("preflight", "ollama recovered")
                return True
            except Exception:
                continue
        return False


def _is_leadforge() -> bool:
    """Confirms the thing answering is actually LeadForge, not a namesake."""
    try:
        r = httpx.get(f"{API}/api/outreach/campaigns", timeout=10)
        return r.status_code == 200 and isinstance(r.json(), (list, dict))
    except Exception:
        return False


def _kill_stale_server() -> None:
    """Stop anything already holding our port.

    A long-lived uvicorn keeps the code and campaign_routing.yaml it imported at
    startup. A server left running from before a copy or routing change will
    happily serve the OLD logic against the NEW config - which is exactly how a
    whole batch once failed with "Invalid format specifier". A daily batch job is
    cheap to restart, so always start from current code.
    """
    subprocess.run(
        ["pkill", "-f", f"uvicorn main:app --host 127.0.0.1 --port {LEADFORGE_PORT}"],
        capture_output=True,
    )
    for _ in range(10):
        if not _is_leadforge():
            return
        time.sleep(1)


def ensure_server() -> bool:
    if _is_leadforge():
        log("preflight", "stopping server left over from an earlier run ...")
        _kill_stale_server()
    log("preflight", "starting uvicorn ...")
    SERVER_LOG.parent.mkdir(exist_ok=True)
    with SERVER_LOG.open("ab") as fh:
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(LEADFORGE_PORT)],
            cwd=str(BASE), stdout=fh, stderr=fh, start_new_session=True,
        )
    for _ in range(20):
        time.sleep(3)
        if _is_leadforge():
            log("preflight", f"api up on :{LEADFORGE_PORT}")
            return True
    return False


DEFAULT_SCHEDULED_SEND_CAP = 3  # Sized conservatively for unattended runs (max 3 leads per morning)


def ensure_compliance() -> bool:
    """Refuse to send commercial mail without a valid, genuine physical postal address.

    US CAN-SPAM and Canadian CASL both require one, and the enabled markets are
    US, UK and Canada. A home address satisfies this; an empty footer does not.
    Framing the mail as personal does not exempt it - what matters is that the
    message's purpose is commercial.
    """
    from leadforge.repositories.settings import SettingsCache
    from leadforge.outreach.compliance import validate_postal_address
    postal = SettingsCache().get_str("outreach.footer_postal_address", "").strip()
    is_valid, reason = validate_postal_address(postal)
    if not is_valid:
        log("preflight", f"CAN-SPAM compliance check failed: {reason}")
        return False
    log("preflight", f"CAN-SPAM physical postal address verified: {postal[:30]}...")
    return True


def ensure_content_circuit_breaker() -> bool:
    """Refuse to proceed if the content circuit breaker has been tripped."""
    from leadforge.database import get_db_connection
    from leadforge.repositories.settings import SettingsCache
    from leadforge.outreach.circuit_breaker import is_content_circuit_breaker_tripped
    conn = get_db_connection()
    try:
        tripped, reason = is_content_circuit_breaker_tripped(conn, SettingsCache())
        if tripped:
            log("abort", f"CONTENT CIRCUIT BREAKER TRIPPED: {reason}")
            log("abort", "Automated sending halted. Human inspection required. Clear via 'python scripts/daily_outreach.py --clear-breaker'")
            return False
        return True
    finally:
        conn.close()


def ensure_smtp() -> bool:
    """Authenticate without sending. A dead credential should stop the run
    before drafts are approved, not after."""
    import smtplib
    import ssl
    from leadforge.config import get_smtp_config
    cfg = get_smtp_config()
    if not cfg.get("host") or not cfg.get("password"):
        log("preflight", "SMTP not configured")
        return False
    try:
        server = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=20)
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(cfg["username"], cfg["password"])
        server.quit()
        return True
    except Exception as exc:
        log("preflight", f"SMTP login failed: {type(exc).__name__}")
        return False


# ------------------------------------------------------------------ stages

def stage_leads(pairs: int) -> None:
    log("leads", f"running {pairs} city/category pair(s) ...")
    proc = subprocess.run(
        [sys.executable, "scripts/run_lead_matrix.py", "--pairs", str(pairs)],
        cwd=str(BASE), capture_output=True, text=True, timeout=7200,
    )
    for line in (proc.stdout or "").splitlines():
        if line.strip().startswith(("Matrix:", "Done in", "    Qualified", "    New Leads")):
            log("leads", line.strip())
    if proc.returncode != 0:
        log("leads", f"runner exited {proc.returncode} (continuing with existing leads)")


def pending_targets(limit: int) -> list[str]:
    """Opportunities with a real email address and no draft yet, best score first."""
    from leadforge.database import get_db_connection
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT o.id FROM opportunities o
        JOIN businesses b ON b.id = o.business_id
        LEFT JOIN email_drafts d ON d.opportunity_id = o.id
        WHERE b.contact_email IS NOT NULL AND b.contact_email != ''
          AND b.is_suppressed = 0 AND b.deleted_at IS NULL AND o.deleted_at IS NULL
          AND d.id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM email_drafts ed
              WHERE LOWER(ed.recipient_email) = LOWER(b.contact_email)
                AND ed.status IN ('PENDING_APPROVAL', 'APPROVED', 'QUEUED', 'SENT', 'FAILED')
          )
        ORDER BY o.score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def stage_drafts(budget: int) -> int:
    targets = pending_targets(budget)
    if not targets:
        log("drafts", "no un-drafted emailable opportunities")
        return 0
    log("drafts", f"generating up to {len(targets)} draft(s) ...")
    made = 0
    for opp_id in targets:
        try:
            r = httpx.post(f"{API}/api/outreach/drafts/generate",
                           json={"opportunity_id": opp_id}, timeout=180)
            if r.status_code == 200:
                made += 1
            elif r.status_code == 409:
                pass  # already contacted; the dedup guard is doing its job
            else:
                log("drafts", f"{opp_id[:8]} -> {r.status_code} {r.text[:110]}")
        except Exception as exc:
            log("drafts", f"{opp_id[:8]} -> {type(exc).__name__}")
    log("drafts", f"{made} generated")
    return made


def stage_followups() -> int:
    """Dispatches follow-ups that have come due.

    Runs before new first-touches because a second or third touch to someone who
    already got the first email converts better than a cold approach to a stranger,
    and both draw on the same daily allowance. The sequencer cancels the rest of a
    sequence on any reply, bounce, or opt-out, so this never chases someone who has
    already answered.
    """
    try:
        from leadforge.communication.sequencer import FollowupSequencer
        sent = FollowupSequencer().process_due_followups()
        log("followup", f"{len(sent)} follow-up(s) dispatched")
        return len(sent)
    except Exception as exc:
        log("followup", f"error: {type(exc).__name__}: {str(exc)[:140]}")
        return 0


def stage_approve() -> int:
    r = httpx.post(f"{API}/api/outreach/drafts/bulk-approve", json={}, timeout=180)
    if r.status_code != 200:
        log("approve", f"failed {r.status_code} {r.text[:140]}")
        return 0
    data = r.json()
    log("approve", str(data)[:220])
    return int(data.get("approved_count", data.get("approved", 0)) or 0)


def stage_replies() -> dict:
    log("replies", "polling IMAP inbox for new replies and bounces ...")
    try:
        r = httpx.post(f"{API}/api/outreach/poll-replies", timeout=120)
        if r.status_code != 200:
            log("replies", f"failed {r.status_code} {r.text[:140]}")
            return {}
        data = r.json()
        counts = data.get("counts", {})
        processed = data.get("processed_count", 0)
        log("replies", f"processed={processed} {counts}")
        return data
    except Exception as exc:
        log("replies", f"error polling replies: {type(exc).__name__}")
        return {}


def stage_send(max_sends: Optional[int] = None) -> int:
    params = {"wait": "true"}
    if max_sends is not None:
        params["max_sends"] = max_sends
    r = httpx.post(f"{API}/api/outreach/deliver", params=params, timeout=1800)
    if r.status_code != 200:
        log("send", f"failed {r.status_code} {r.text[:140]}")
        return 0
    data = r.json()
    sent_cnt = int(data.get("sent_count", data.get("sent", 0)) or 0)
    log("send", f"successfully delivered {sent_cnt} email(s) (capped at {max_sends})")
    return sent_cnt


def report() -> None:
    from leadforge.database import get_db_connection
    from leadforge.repositories.settings import SettingsCache
    from leadforge.outreach.ramp import delivery_allowance
    from leadforge.repositories.whatsapp_reporting import get_whatsapp_summary
    conn = get_db_connection()
    biz, emails = conn.execute(
        "SELECT COUNT(*), COUNT(NULLIF(contact_email,'')) FROM businesses "
        "WHERE deleted_at IS NULL"
    ).fetchone()
    rows = dict(conn.execute(
        "SELECT status, COUNT(*) FROM email_drafts GROUP BY status").fetchall())
    replies = conn.execute("SELECT COUNT(*) FROM communication_messages").fetchone()[0]
    allowance, reason = delivery_allowance(conn, SettingsCache())
    conn.close()
    log("report", f"businesses={biz} emailable={emails} drafts={rows} replies={replies}")
    log("report", f"allowance: {reason}")
    wa = get_whatsapp_summary()
    if wa:
        log(
            "report",
            f"whatsapp: total={wa['total_contacts']} pending={wa['pending']} "
            f"sent_today={wa['sent_today']} total_sent={wa['total_sent']} replies={wa['replied']}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", type=int, default=4)
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--skip-leads", action="store_true")
    ap.add_argument(
        "--max-sends",
        type=int,
        default=None,
        help="Hard maximum sends for this run (overrides outreach.scheduled_send_cap)",
    )
    ap.add_argument(
        "--clear-breaker",
        action="store_true",
        help="Clear the content circuit breaker after human review",
    )
    args = ap.parse_args()

    if args.clear_breaker:
        from leadforge.database import get_db_connection
        from leadforge.outreach.circuit_breaker import clear_content_circuit_breaker
        conn = get_db_connection()
        try:
            clear_content_circuit_breaker(conn, cleared_by="cli_operator")
            log("breaker", "Content circuit breaker cleared by operator.")
            return 0
        finally:
            conn.close()

    log("start", f"daily outreach run ({time.strftime('%Y-%m-%d %H:%M')})")

    if not ensure_ollama():
        log("abort", "Ollama unavailable - every hook would fall back and be refused.")
        return 2
    if not ensure_server():
        log("abort", "API unavailable.")
        return 2
    if not args.no_send and not ensure_content_circuit_breaker():
        return 4
    if not args.no_send and not ensure_compliance():
        log("abort", "Refusing to send: invalid or missing physical postal address in the compliance "
                     "footer. Set outreach.footer_postal_address, then rerun.")
        return 3
    if not args.no_send and not ensure_smtp():
        log("abort", "SMTP credentials rejected.")
        return 2

    # Ingest and classify replies & bounces before calculating allowance and drafting
    stage_replies()

    from leadforge.database import get_db_connection
    from leadforge.repositories.settings import SettingsCache
    from leadforge.outreach.ramp import delivery_allowance
    conn = get_db_connection()
    settings_cache = SettingsCache()
    allowance, reason = delivery_allowance(conn, settings_cache)
    conn.close()

    scheduled_cap = settings_cache.get_int("outreach.scheduled_send_cap", DEFAULT_SCHEDULED_SEND_CAP)
    configured_run_cap = args.max_sends if args.max_sends is not None else scheduled_cap
    effective_run_cap = min(configured_run_cap, allowance)
    log("budget", f"daily allowance: {reason}")
    log("budget", f"per-run send cap: {effective_run_cap} (cap={configured_run_cap}, allowance={allowance})")

    if not args.skip_leads:
        stage_leads(args.pairs)

    # Follow-ups first: they are real sends against the same allowance
    followed_up = 0
    if args.no_send:
        log("followup", "skipped (--no-send)")
    elif effective_run_cap <= 0:
        log("followup", f"skipped: run cap or allowance is zero ({reason})")
    else:
        followed_up = stage_followups()

    # Bounded by per-run cap remaining
    remaining = max(effective_run_cap - followed_up, 0)
    stage_drafts(max(remaining * 2, 10))
    stage_approve()

    if args.no_send:
        log("send", "skipped (--no-send)")
    elif remaining <= 0:
        log("send", f"skipped: per-run cap ({effective_run_cap}) satisfied by follow-ups or allowance zero ({reason})")
    else:
        stage_send(max_sends=remaining)

    report()
    log("done", "run complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
