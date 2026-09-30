#!/usr/bin/env python3
"""Read-Only Live Outreach Status Dashboard.

Displays live, read-only system metrics:
- Process status of leadforge daemons / background workers
- Database draft counts by status
- Daily send limits, remaining allowance, and sent today
- Live pre-send safety checks (MX, suppression, dedup, dispatch eligibility)
- Full inventory table of approved drafts ready for dispatch

This tool is strictly READ-ONLY. It never writes to the database,
never opens SMTP connections, and never triggers outreach actions.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from leadforge.database import get_db_connection
from leadforge.repositories.settings import SettingsCache
from leadforge.outreach.ramp import delivery_allowance
from leadforge.outreach.dry_run import build_dry_run_report
from leadforge.outreach.quality import EmailQualityEngine


def check_running_processes() -> List[Dict[str, Any]]:
    """Checks for active LeadForge-related processes via ps."""
    try:
        res = subprocess.run(
            ["ps", "-eo", "pid,user,etime,command"],
            capture_output=True,
            text=True,
            check=True,
        )
        procs = []
        for line in res.stdout.splitlines()[1:]:
            cmd = line.strip()
            # Look for active daemon or runner processes
            if re.search(r"leadforge\.(?:daemon|server)|daily_outreach\.py|morning_launch\.sh", cmd):
                if not re.search(r"grep|outreach_dashboard|pytest", cmd):
                    parts = cmd.split(None, 3)
                    if len(parts) >= 4:
                        procs.append({
                            "pid": parts[0],
                            "user": parts[1],
                            "elapsed": parts[2],
                            "command": parts[3],
                        })
        return procs
    except Exception as e:
        return [{"pid": "ERR", "user": "", "elapsed": "", "command": f"Error: {e}"}]


def check_scheduled_automation(
    conn: Optional[sqlite3.Connection] = None,
    settings_cache: Any = None,
) -> Dict[str, Any]:
    """Checks systemd user timers, crontab, per-run caps, and circuit breaker states."""
    timer_name = "leadforge-daily.timer"

    if settings_cache is None:
        from leadforge.repositories.settings import SettingsCache
        settings_cache = SettingsCache()

    scheduled_cap = settings_cache.get_int("outreach.scheduled_send_cap", 3)
    daily_limit = settings_cache.get_int("outreach.daily_send_limit", 10)

    cb_tripped = False
    cb_reason = ""
    bounce_status = "ARMED (0% bounce rate)"
    if conn is not None:
        try:
            from leadforge.outreach.circuit_breaker import is_content_circuit_breaker_tripped
            cb_tripped, cb_reason = is_content_circuit_breaker_tripped(conn, settings_cache)
        except Exception as e:
            cb_reason = f"Error checking content breaker: {e}"

        try:
            from leadforge.outreach.ramp import bounce_rate
            rate, bad, total = bounce_rate(conn, 50)
            bounce_status = f"ARMED ({bad}/{total} bounced, {rate:.0%})"
        except Exception as e:
            bounce_status = f"Error checking bounce rate: {e}"

    info = {
        "timer_name": timer_name,
        "is_active": False,
        "is_enabled": False,
        "active_state": "unknown",
        "sub_state": "unknown",
        "unit_file_state": "unknown",
        "schedule": "*-*-* 08:00:00 (daily at 08:00 IST)",
        "next_run": "n/a",
        "scheduled_cap": scheduled_cap,
        "daily_limit": daily_limit,
        "cb_tripped": cb_tripped,
        "cb_reason": cb_reason,
        "content_breaker_status": f"TRIPPED ({cb_reason})" if cb_tripped else "ARMED & CLEAN (Strict 40-60w, grounded bridge)",
        "bounce_breaker_status": bounce_status,
        "status_banner": f"AUTOMATIC SENDING: DISABLED (Cap: {scheduled_cap} sends/run, Breaker: ARMED)",
        "is_danger": False,
        "details": "",
    }
    try:
        res = subprocess.run(
            [
                "systemctl", "--user", "show", timer_name,
                "--property=ActiveState,SubState,UnitFileState,TimersCalendar,NextElapseUSecRealtime"
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        props = {}
        for line in res.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()

        active_state = props.get("ActiveState", "inactive")
        sub_state = props.get("SubState", "dead")
        unit_state = props.get("UnitFileState", "disabled")
        calendar = props.get("TimersCalendar", "")

        info["active_state"] = active_state
        info["sub_state"] = sub_state
        info["unit_file_state"] = unit_state
        if calendar:
            info["schedule"] = calendar
        info["is_active"] = (active_state == "active")
        info["is_enabled"] = (unit_state == "enabled")

        if info["is_active"]:
            # Query next elapse from systemctl
            lt_res = subprocess.run(
                ["systemctl", "--user", "list-timers", timer_name, "--no-legend"],
                capture_output=True,
                text=True,
                check=False,
            )
            lt_line = lt_res.stdout.strip()
            if lt_line:
                parts = lt_line.split()
                if len(parts) >= 2:
                    info["next_run"] = f"{parts[0]} {parts[1]}"
            if cb_tripped:
                info["status_banner"] = f"AUTOMATIC SENDING: HALTED BY CIRCUIT BREAKER (Per-Run Cap: {scheduled_cap})"
                info["is_danger"] = True
                info["details"] = (
                    f"CRITICAL: {timer_name} is active, but automated dispatch is LOCKED by the content "
                    f"circuit breaker ({cb_reason}). Human inspection required before sending can proceed!"
                )
            else:
                info["status_banner"] = f"AUTOMATIC SENDING: ENABLED (Capped: {scheduled_cap} sends/run, Breakers: ARMED) — next run at {info['next_run']}"
                info["is_danger"] = False
                info["details"] = (
                    f"{timer_name} is active and protected by per-run cap ({scheduled_cap} sends) & content circuit breaker."
                )
        elif info["is_enabled"]:
            info["status_banner"] = f"AUTOMATIC SENDING: DISABLED (INACTIVE BUT ENABLED IN SYSTEMD) — Cap: {scheduled_cap} sends/run"
            info["is_danger"] = True
            info["details"] = (
                f"WARNING: {timer_name} is inactive now, but still enabled. "
                "It will re-arm on next login/reboot!"
            )
        else:
            if cb_tripped:
                info["status_banner"] = f"AUTOMATIC SENDING: DISABLED & BREAKER TRIPPED ({cb_reason})"
                info["is_danger"] = True
                info["details"] = f"{timer_name} is inactive. Content circuit breaker is TRIPPED: {cb_reason}"
            else:
                info["status_banner"] = f"AUTOMATIC SENDING: DISABLED (Per-Run Cap: {scheduled_cap} sends/run, Breaker: ARMED)"
                info["is_danger"] = False
                info["details"] = (
                    f"{timer_name} is inactive and disabled (zero automated sends). "
                    f"Safety controls: per-run cap {scheduled_cap} sends, content breaker armed."
                )
    except Exception as e:
        info["details"] = f"Could not inspect systemd timer: {e}"

    return info



def get_status_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """Queries draft counts grouped by status."""
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM email_drafts GROUP BY status")
    counts = {row[0]: row[1] for row in cur.fetchall()}
    return counts


def get_approved_batch(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Retrieves all currently APPROVED drafts with lead details."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ed.id as draft_id, b.name as business_name, ed.recipient_email,
               ed.subject, ed.body, ed.quality_score, ed.quality_passed,
               ed.created_at, ed.updated_at
        FROM email_drafts ed
        JOIN opportunities o ON ed.opportunity_id = o.id
        JOIN businesses b ON o.business_id = b.id
        WHERE ed.status = 'APPROVED'
        ORDER BY ed.created_at ASC, ed.id ASC
    """)
    rows = cur.fetchall()
    items = []
    for r in rows:
        body = r["body"] or ""
        core = EmailQualityEngine._core_body(body)
        paras = [p.strip() for p in core.split("\n\n") if p.strip()]
        hook = paras[0] if paras else ""
        p2 = paras[1] if len(paras) > 1 else ""
        bridge = p2.split(". ")[0].strip()
        if bridge and not bridge.endswith("."):
            bridge += "."

        words = len(core.split())
        items.append({
            "draft_id": r["draft_id"],
            "business_name": r["business_name"],
            "recipient_email": r["recipient_email"],
            "subject": r["subject"],
            "subject_len": len(r["subject"] or ""),
            "core_words": words,
            "quality_score": r["quality_score"],
            "quality_passed": bool(r["quality_passed"]),
            "hook": hook,
            "bridge": bridge,
            "body": body,
            "updated_at": r["updated_at"],
        })
    return items


def render_terminal_dashboard(
    auto_info: Dict[str, Any],
    procs: List[Dict[str, Any]],
    counts: Dict[str, int],
    settings_data: Dict[str, Any],
    dry_run: Dict[str, Any],
    batch: List[Dict[str, Any]],
) -> str:
    """Formats human-readable terminal dashboard."""
    lines = []
    w = 78
    sep = "=" * w
    sub_sep = "-" * w

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines.append(sep)
    lines.append(f"  LEADFORGE OUTREACH STATUS DASHBOARD (READ-ONLY)  --  {now_utc}")
    lines.append(sep)

    # 0. Automation & Scheduled Sending Status (Unmissable visual)
    lines.append("0. AUTOMATIC SENDING & SAFETY CONTROLS MONITOR")
    lines.append(f"  *** {auto_info['status_banner']} ***")
    lines.append(f"  Systemd Timer:   {auto_info['timer_name']} (Active: {auto_info['active_state']}, UnitState: {auto_info['unit_file_state']})")
    lines.append(f"  Schedule:        {auto_info['schedule']}")
    lines.append(f"  Per-Run Send Cap: {auto_info['scheduled_cap']} sends/run (Max Unattended Blast Radius: {auto_info['scheduled_cap']}) [Manual Limit: {auto_info['daily_limit']}]")
    lines.append(f"  Content Breaker: {auto_info['content_breaker_status']}")
    lines.append(f"  Bounce Breaker:  {auto_info['bounce_breaker_status']}")
    lines.append(f"  Safety Details:  {auto_info['details']}")
    lines.append(sub_sep)

    # 1. Process Status
    lines.append("1. BACKGROUND PROCESS MONITOR")
    if procs:
        lines.append(f"  [!] ACTIVE PROCESSES DETECTED ({len(procs)}):")
        for p in procs:
            lines.append(f"      PID {p['pid']:<7} ({p['user']}) elapsed: {p['elapsed']:<10} {p['command'][:50]}")
    else:
        lines.append("  [OK] Zero leadforge daemon processes running (daemon is stopped).")
    lines.append(sub_sep)

    # 2. Drafts Summary & Daily Send Progress
    lines.append("2. DRAFT QUEUE & SEND ALLOWANCE")
    appr = counts.get("APPROVED", 0)
    pend = counts.get("PENDING_APPROVAL", 0)
    sent = counts.get("SENT", 0)
    canc = counts.get("CANCELLED", 0)
    fail = counts.get("FAILED", 0)
    rej = counts.get("REJECTED", 0)

    lines.append(f"  Drafts Queue:  APPROVED: {appr:<3} | PENDING: {pend:<3} | CANCELLED: {canc:<3} | REJECTED: {rej:<3} | SENT: {sent:<3}")
    lines.append(f"  Daily Cap:     {settings_data['daily_limit']} sends/day | Sent Today: {settings_data['sent_today']} | Remaining Today: {settings_data['allowance']}")
    lines.append(f"  Ramp Status:   {settings_data['allowance_reason']}")
    lines.append(sub_sep)

    # 3. Live Pre-Send Safety Check (Dry-Run)
    lines.append("3. LIVE PRE-SEND SAFETY AUDIT (Dry-Run)")
    lines.append(f"  From Address:          {dry_run.get('smtp_from_email', '(none)')}")
    lines.append(f"  Approved Inspected:    {dry_run.get('approved', 0)}")
    lines.append(f"  DNS MX Check:          {dry_run.get('mx_pass', 0)} passed, {dry_run.get('mx_failed', 0)} failed (NXDOMAIN safely blocked)")
    lines.append(f"  Opt-Out Suppressions:  {dry_run.get('suppressed', 0)}")
    lines.append(f"  Recipient Dedup:       {dry_run.get('deduplicated', 0)}")
    lines.append(f"  Eligible to Dispatch:  {dry_run.get('eligible', 0)}")
    lines.append(f"  Effective Next Send:   {dry_run.get('effective_send_count', 0)} (strictly capped by daily limit {settings_data['daily_limit']})")
    lines.append(sub_sep)

    # 4. Approved Batch Table
    lines.append(f"4. CURRENTLY APPROVED BATCH INVENTORY ({len(batch)} Leads)")
    header = f"  {'#':<3} {'Recipient':<28} {'Subj(L)':<9} {'Words':<6} {'Score':<6} {'Grounded Bridge Snippet':<22}"
    lines.append(header)
    lines.append("  " + "-" * (w - 2))

    for idx, b in enumerate(batch, 1):
        email_str = b['recipient_email'][:27]
        subj_stat = f"{b['subject_len']}c"
        words_str = f"{b['core_words']}w"
        score_str = f"{b['quality_score']}/100"
        bridge_str = b['bridge'][:20] + "..." if len(b['bridge']) > 23 else b['bridge']
        lines.append(f"  {idx:<3} {email_str:<28} {subj_stat:<9} {words_str:<6} {score_str:<6} {bridge_str:<22}")

    lines.append(sep)
    lines.append("  NOTE: This dashboard is completely read-only. No email was sent.")
    lines.append(sep)
    return "\n".join(lines)


def render_html_dashboard(
    auto_info: Dict[str, Any],
    procs: List[Dict[str, Any]],
    counts: Dict[str, int],
    settings_data: Dict[str, Any],
    dry_run: Dict[str, Any],
    batch: List[Dict[str, Any]],
) -> str:
    """Generates a responsive, modern HTML visual dashboard."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if auto_info.get("is_danger"):
        auto_status_html = f"""
        <div class="alert alert-danger" style="background:#fee2e2; color:#991b1b; border:2px solid #ef4444; margin-bottom:20px; padding:16px;">
            <div style="font-size:18px; font-weight:700;">🚨 {html.escape(auto_info['status_banner'])}</div>
            <div style="margin-top:6px; font-size:13px;">{html.escape(auto_info['details'])}</div>
            <div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">
                <span class="badge badge-secondary" style="font-size:12px; padding:4px 10px;">Per-Run Cap: {auto_info.get('scheduled_cap', 3)} sends/run</span>
                <span class="badge badge-secondary" style="font-size:12px; padding:4px 10px;">Daily Manual Cap: {auto_info.get('daily_limit', 10)}</span>
                <span class="badge badge-secondary" style="background:#f87171; color:#fff; font-size:12px; padding:4px 10px;">Breaker: {html.escape(auto_info.get('content_breaker_status', 'TRIPPED'))}</span>
                <span class="badge badge-info" style="font-size:12px; padding:4px 10px;">Bounce Breaker: {html.escape(auto_info.get('bounce_breaker_status', 'ARMED'))}</span>
            </div>
        </div>
        """
    else:
        auto_status_html = f"""
        <div class="alert alert-success" style="background:#def7ec; color:#03543f; border:2px solid #31c48d; margin-bottom:20px; padding:16px;">
            <div style="font-size:18px; font-weight:700;">🛡️ {html.escape(auto_info['status_banner'])}</div>
            <div style="margin-top:6px; font-size:13px;">{html.escape(auto_info['details'])} &bull; Schedule: <code>{html.escape(auto_info['schedule'])}</code></div>
            <div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">
                <span class="badge badge-secondary" style="font-size:12px; padding:4px 10px;">Per-Run Cap: {auto_info.get('scheduled_cap', 3)} sends/run</span>
                <span class="badge badge-secondary" style="font-size:12px; padding:4px 10px;">Daily Manual Cap: {auto_info.get('daily_limit', 10)}</span>
                <span class="badge badge-success" style="font-size:12px; padding:4px 10px;">Content Breaker: {html.escape(auto_info.get('content_breaker_status', 'ARMED'))}</span>
                <span class="badge badge-info" style="font-size:12px; padding:4px 10px;">Bounce Breaker: {html.escape(auto_info.get('bounce_breaker_status', 'ARMED'))}</span>
            </div>
        </div>
        """

    proc_status_html = ""
    if procs:
        proc_status_html = f'<div class="alert alert-warning"><strong>Warning:</strong> {len(procs)} daemon/runner process(es) running.</div>'
    else:
        proc_status_html = '<div class="alert alert-success"><strong>OK:</strong> No leadforge background daemon running (clean manual state).</div>'

    rows_html = []
    for idx, b in enumerate(batch, 1):
        score_badge = '<span class="badge badge-success">100</span>' if b['quality_score'] == 100 else f'<span class="badge badge-info">{b["quality_score"]}</span>'
        rows_html.append(f"""
        <tr>
            <td>{idx}</td>
            <td><strong>{html.escape(b['business_name'])}</strong><br><small class="text-muted">{html.escape(b['recipient_email'])}</small></td>
            <td><code>{html.escape(b['subject'])}</code> <span class="badge badge-secondary">{b['subject_len']}c</span></td>
            <td><span class="badge badge-secondary">{b['core_words']}w</span></td>
            <td>{score_badge}</td>
            <td><small>{html.escape(b['bridge'])}</small></td>
        </tr>
        """)

    table_body = "\n".join(rows_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="60">
    <title>LeadForge Outreach Status Dashboard (Read-Only)</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #f4f6f9;
            color: #212529;
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #dee2e6;
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        h1 {{ margin: 0; font-size: 24px; font-weight: 700; color: #1a202c; }}
        .timestamp {{ font-size: 14px; color: #718096; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .card {{
            background: #ffffff;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            border-left: 4px solid #4299e1;
        }}
        .card.success {{ border-left-color: #48bb78; }}
        .card.warning {{ border-left-color: #ecc94b; }}
        .card.purple {{ border-left-color: #9f7aea; }}
        .card h3 {{ margin: 0 0 8px 0; font-size: 13px; color: #718096; text-transform: uppercase; letter-spacing: 0.5px; }}
        .card .value {{ font-size: 28px; font-weight: 700; color: #2d3748; }}
        .card .subtitle {{ font-size: 13px; color: #a0aec0; margin-top: 4px; }}
        .alert {{
            padding: 12px 16px;
            border-radius: 6px;
            margin-bottom: 24px;
            font-size: 14px;
        }}
        .alert-success {{ background: #def7ec; color: #03543f; border: 1px solid #bcf0da; }}
        .alert-warning {{ background: #fef08a; color: #713f12; border: 1px solid #fde047; }}
        .alert-danger {{ background: #fee2e2; color: #991b1b; border: 1px solid #f87171; }}
        .section-title {{ font-size: 18px; font-weight: 600; margin: 24px 0 12px 0; color: #2d3748; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        th, td {{
            padding: 12px 14px;
            text-align: left;
            font-size: 13px;
            border-bottom: 1px solid #e2e8f0;
        }}
        th {{ background: #edf2f7; font-weight: 600; color: #4a5568; }}
        tr:hover {{ background: #f7fafc; }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 600;
            border-radius: 9999px;
        }}
        .badge-success {{ background: #c6f6d5; color: #22543d; }}
        .badge-info {{ background: #bee3f8; color: #2b6cb0; }}
        .badge-secondary {{ background: #edf2f7; color: #4a5568; }}
        .text-muted {{ color: #718096; }}
        code {{ font-family: ui-monospace, Menlo, Monaco, monospace; font-size: 12px; }}
        .footer {{
            margin-top: 32px;
            text-align: center;
            font-size: 12px;
            color: #a0aec0;
            border-top: 1px solid #e2e8f0;
            padding-top: 16px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>LeadForge Outreach Status Dashboard</h1>
                <div class="timestamp">Generated: {now_str} (Auto-refreshes every 60s)</div>
            </div>
            <div>
                <span class="badge badge-secondary" style="font-size:13px; padding: 6px 12px;">READ-ONLY MONITOR</span>
            </div>
        </div>

        {auto_status_html}

        {proc_status_html}

        <div class="grid">
            <div class="card success">
                <h3>Approved Ready Batch</h3>
                <div class="value">{counts.get("APPROVED", 0)}</div>
                <div class="subtitle">{dry_run.get('eligible', 0)} eligible for dispatch</div>
            </div>
            <div class="card purple">
                <h3>Daily Send Cap</h3>
                <div class="value">{settings_data['daily_limit']} <span style="font-size:16px;font-weight:400;color:#718096;">/ day</span></div>
                <div class="subtitle">{settings_data['allowance']} remaining allowance today</div>
            </div>
            <div class="card">
                <h3>Sent Today</h3>
                <div class="value">{settings_data['sent_today']}</div>
                <div class="subtitle">Effective next send: {dry_run.get('effective_send_count', 0)}</div>
            </div>
            <div class="card warning">
                <h3>Safety Gates (Pre-Send)</h3>
                <div class="value">{dry_run.get('mx_pass', 0)} <span style="font-size:14px;color:#718096;">MX pass</span></div>
                <div class="subtitle">{dry_run.get('mx_failed', 0)} MX fail | {dry_run.get('suppressed', 0)} suppressed</div>
            </div>
        </div>

        <div class="section-title">Approved Batch Inventory ({len(batch)} Leads)</div>
        <table>
            <thead>
                <tr>
                    <th style="width:30px;">#</th>
                    <th>Recipient & Company</th>
                    <th>Subject Line</th>
                    <th>Words</th>
                    <th>Score</th>
                    <th>Grounded Contact Bridge</th>
                </tr>
            </thead>
            <tbody>
                {table_body}
            </tbody>
        </table>

        <div class="footer">
            LeadForge Autonomous Cold Email System &bull; Strictly Read-Only Status Surface &bull; Zero Emails Sent
        </div>
    </div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="LeadForge Outreach Status Dashboard (Read-Only)")
    parser.add_argument("--html", action="store_true", help="Generate HTML dashboard to leadforge/outreach_dashboard.html")
    parser.add_argument("--open", action="store_true", help="Open HTML dashboard in browser")
    parser.add_argument("--out", type=str, default="", help="Custom output path for HTML dashboard")
    args = parser.parse_args()

    conn = get_db_connection()
    try:
        settings = SettingsCache()
        auto_info = check_scheduled_automation(conn=conn, settings_cache=settings)
        procs = check_running_processes()
        counts = get_status_counts(conn)

        daily_limit = settings.get_int("outreach.daily_send_limit", 10)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM email_drafts WHERE status = 'SENT' AND substr(sent_at, 1, 10) = ?", (today_str,))
        sent_today = cur.fetchone()[0]
        allowance, allowance_reason = delivery_allowance(conn, settings)

        settings_data = {
            "daily_limit": daily_limit,
            "sent_today": sent_today,
            "allowance": allowance,
            "allowance_reason": allowance_reason,
        }

        dry_run = asyncio.run(build_dry_run_report())
        batch = get_approved_batch(conn)

    finally:
        conn.close()

    # Terminal report
    term_report = render_terminal_dashboard(auto_info, procs, counts, settings_data, dry_run, batch)

    # HTML output path
    html_out = Path(args.out) if args.out else BASE_DIR / "outreach_dashboard.html"
    html_content = render_html_dashboard(auto_info, procs, counts, settings_data, dry_run, batch)
    html_out.write_text(html_content, encoding="utf-8")

    if args.html:
        print(f"HTML dashboard generated: file://{html_out.resolve()}")
    else:
        print(term_report)
        print(f"\n[Dashboard HTML exported to: file://{html_out.resolve()}]")

    if args.open:
        try:
            subprocess.run(["xdg-open", str(html_out.resolve())], check=False)
        except Exception:
            pass


if __name__ == "__main__":
    main()
