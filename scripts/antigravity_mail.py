#!/usr/bin/env python3
"""Antigravity Mail: Direct Terminal Copilot Outreach CLI.

Zero-friction interface for Antigravity (Gemini) and terminal users to inspect leads,
craft bespoke B2B outreach emails, review drafts, and dispatch them via Gmail SMTP.
"""

import sys
import os
import argparse
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from leadforge.database import get_db_connection, append_event, uuidv7
from leadforge.outreach.deliverer import SMTPEmailDeliverer
from leadforge.outreach.quality import EmailQualityEngine
from leadforge.repositories.settings import SettingsCache
from leadforge.outreach.generator import compile_compliance_footer
from leadforge.config import get_smtp_config


def print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  ⚡ {title}")
    print("=" * 70)


def cmd_status(args) -> None:
    """Shows comprehensive outreach pipeline status."""
    print_header("ANTIGRAVITY OUTREACH PIPELINE STATUS")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        cursor.execute("SELECT count(*) as count FROM businesses")
        total_biz = cursor.fetchone()["count"]

        cursor.execute("SELECT count(*) as count FROM businesses WHERE contact_email IS NOT NULL AND contact_email != ''")
        biz_with_email = cursor.fetchone()["count"]

        cursor.execute("SELECT count(*) as count FROM opportunities")
        total_opps = cursor.fetchone()["count"]

        cursor.execute("SELECT status, count(*) as count FROM email_drafts GROUP BY status")
        draft_status = {row["status"]: row["count"] for row in cursor.fetchall()}

        total_sent = draft_status.get("SENT", 0)

        smtp_cfg = get_smtp_config()
        print(f"  🏢 Total Businesses Scraped:     {total_biz}")
        print(f"  📧 Businesses with Direct Email: {biz_with_email}")
        print(f"  🎯 Total Opportunities:          {total_opps}")
        print(f"  📝 Drafts (PENDING_APPROVAL):    {draft_status.get('PENDING_APPROVAL', 0)}")
        print(f"  ✅ Drafts (APPROVED / Ready):    {draft_status.get('APPROVED', 0)}")
        print(f"  🚀 Total Sent Emails:            {total_sent}")
        print(f"  ❌ Drafts (REJECTED/FAILED):     {draft_status.get('REJECTED', 0) + draft_status.get('FAILED', 0)}")

        print("-" * 70)
        print(f"  📡 SMTP Sender Identity:         {smtp_cfg['from_name']} <{smtp_cfg['from_email']}>")
        print(f"  🔒 SMTP Server:                  {smtp_cfg['host']}:{smtp_cfg['port']} (TLS: {smtp_cfg['use_tls']})")
        print("=" * 70 + "\n")
    finally:
        conn.close()


def cmd_leads(args) -> None:
    """Lists uncontacted qualified businesses with verified emails ready for outreach."""
    limit = args.limit or 10
    print_header(f"TOP {limit} UNCONTACTED LEADS WITH VERIFIED EMAILS")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT o.id as opp_id, b.id as biz_id, b.name as biz_name, b.contact_email,
                   b.display_phone as phone_number, bt.name as category, a.city, a.area,
                   b.website_domain, o.score as opp_score
            FROM opportunities o
            JOIN businesses b ON o.business_id = b.id
            LEFT JOIN business_types bt ON b.business_type_id = bt.id
            LEFT JOIN addresses a ON b.id = a.business_id
            WHERE b.contact_email IS NOT NULL AND b.contact_email != ''
              AND b.is_suppressed = 0
              AND o.id NOT IN (SELECT opportunity_id FROM email_drafts WHERE status = 'SENT')
            ORDER BY o.score DESC, b.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        leads = cursor.fetchall()
        if not leads:
            print("  No uncontacted leads found. Scrape new businesses first!\n")
            return

        for idx, lead in enumerate(leads, start=1):
            website = lead["website_domain"] or "None (No Website)"
            area = lead["area"] or "Industrial Zone"
            print(f"[{idx}] {lead['biz_name']} (Score: {lead['opp_score']}/100)")
            print(f"    • Opp ID:   {lead['opp_id']}")
            print(f"    • Email:    {lead['contact_email']}")
            print(f"    • Phone:    {lead['phone_number'] or 'N/A'}")
            print(f"    • Category: {lead['category'] or 'Manufacturing'}")
            print(f"    • Location: {area}, {lead['city'] or 'Ahmedabad'}")
            print(f"    • Website:  {website}")
            print()
    finally:
        conn.close()


def cmd_drafts(args) -> None:
    """Shows all existing email drafts with their approval status and copy preview."""
    status_filter = args.status
    print_header(f"EMAIL DRAFTS (Filter: {status_filter or 'ALL'})")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT ed.id, ed.opportunity_id, ed.recipient_email, ed.subject,
                   ed.body, ed.status, ed.campaign_name, b.name as biz_name, o.score as opp_score
            FROM email_drafts ed
            JOIN opportunities o ON ed.opportunity_id = o.id
            JOIN businesses b ON o.business_id = b.id
        """
        params = []
        if status_filter:
            query += " WHERE ed.status = ?"
            params.append(status_filter.upper())
        query += " ORDER BY ed.updated_at DESC LIMIT ?"
        params.append(args.limit or 20)

        cursor.execute(query, tuple(params))
        drafts = cursor.fetchall()
        if not drafts:
            print("  No drafts found matching filter.\n")
            return

        for idx, d in enumerate(drafts, start=1):
            status_tag = f"[{d['status']}]"
            print(f"{idx}. {status_tag} To: {d['recipient_email']} | Business: {d['biz_name']}")
            print(f"   • Draft ID: {d['id']}")
            print(f"   • Subject:  {d['subject']}")
            preview = d['body'].replace('\n', ' ')
            if len(preview) > 120:
                preview = preview[:117] + "..."
            print(f"   • Body:     {preview}")
            print()
    finally:
        conn.close()


def save_antigravity_drafts(drafts_list: list) -> int:
    """Inserts or updates bespoke Antigravity AI-crafted drafts with APPROVED status."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        saved = 0
        settings_cache = SettingsCache()
        footer = compile_compliance_footer(settings_cache)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for item in drafts_list:
            opp_id = item["opp_id"]
            subject = item["subject"]
            body = item["body"]
            if footer and footer not in body:
                body = body + footer
            recipient_email = item.get("recipient_email")
            campaign_name = item.get("campaign_name", "Antigravity Bespoke B2B")

            if not recipient_email:
                cursor.execute(
                    "SELECT b.contact_email FROM opportunities o JOIN businesses b ON o.business_id = b.id WHERE o.id = ?",
                    (opp_id,),
                )
                row = cursor.fetchone()
                if row:
                    recipient_email = row["contact_email"]

            if not recipient_email:
                continue

            cursor.execute("SELECT id FROM email_drafts WHERE opportunity_id = ?", (opp_id,))
            existing = cursor.fetchone()
            if existing:
                draft_id = existing["id"]
                cursor.execute(
                    """
                    UPDATE email_drafts
                    SET campaign_name = ?, recipient_email = ?, subject = ?, body = ?, status = 'APPROVED', error_message = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (campaign_name, recipient_email, subject, body, now_str, draft_id),
                )
            else:
                draft_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'APPROVED', ?, ?)
                    """,
                    (draft_id, opp_id, campaign_name, recipient_email, subject, body, now_str, now_str),
                )
            saved += 1
        conn.commit()
        return saved
    finally:
        conn.close()


def cmd_send_one(args) -> None:
    """Sends a single draft by ID immediately."""
    draft_id = args.draft_id
    print_header(f"SENDING DRAFT {draft_id}")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM email_drafts WHERE id = ?", (draft_id,))
        draft = cursor.fetchone()
        if not draft:
            print(f"  ❌ Draft with ID '{draft_id}' not found.\n")
            return

        deliverer = SMTPEmailDeliverer()
        print(f"  Recipient: {draft['recipient_email']}")
        print(f"  Subject:   {draft['subject']}")
        print("  Transmitting via Gmail SMTP...")
        deliverer.send_email(
            to_email=draft["recipient_email"],
            subject=draft["subject"],
            body=draft["body"],
        )

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute("UPDATE email_drafts SET status = 'SENT', updated_at = ? WHERE id = ?", (now_str, draft_id))
        conn.commit()
        print("  🟢 SUCCESS: Email dispatched successfully!\n")
    except Exception as e:
        print(f"  🔴 FAILED to send email: {e}\n")
    finally:
        conn.close()


def cmd_approve_all(args) -> None:
    """Marks all PENDING_APPROVAL drafts as APPROVED."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute("UPDATE email_drafts SET status = 'APPROVED', updated_at = ? WHERE status = 'PENDING_APPROVAL'", (now_str,))
        count = cursor.rowcount
        conn.commit()
        print(f"\n✅ Approved {count} draft(s). Ready for terminal SMTP sending!\n")
    finally:
        conn.close()


def cmd_send_all(args) -> None:
    """Dispatches all APPROVED drafts via SMTP."""
    print_header("STARTING TERMINAL SMTP BATCH DISPATCH")
    deliverer = SMTPEmailDeliverer()
    cfg = deliverer.refresh_config()
    print(f"  Using Sender: {cfg['from_name']} <{cfg['from_email']}>")
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) as count FROM email_drafts WHERE status = 'APPROVED'")
        approved_count = cursor.fetchone()["count"]
        if approved_count == 0:
            print("  No APPROVED drafts found to send.")
            print("  Run `python3 scripts/antigravity_mail.py approve-all` or ask Antigravity to craft & approve drafts first.\n")
            return
        
        print(f"  Sending {approved_count} approved email(s)...")
        deliverer.send_approved_drafts()
        print("\n✅ SMTP batch delivery finished! Check `status` for summary.\n")
    finally:
        conn.close()


def cmd_test_smtp(args) -> None:
    """Verifies connection and authentication to Gmail SMTP."""
    import smtplib, ssl
    print_header("TESTING GMAIL SMTP CONNECTION")
    cfg = get_smtp_config()
    print(f"  Target Host: {cfg['host']}:{cfg['port']}")
    print(f"  User:        {cfg['username']}")
    try:
        context = ssl.create_default_context()
        server = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=10)
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(cfg["username"], cfg["password"])
        server.quit()
        print("  🟢 SUCCESS: Authenticated successfully with Gmail SMTP server!\n")
    except Exception as e:
        print(f"  🔴 FAILED: SMTP Connection/Auth Error: {e}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity Mail: Direct Terminal Outreach CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("status", help="Show pipeline & SMTP status")
    
    leads_parser = subparsers.add_parser("leads", help="List uncontacted leads with verified emails")
    leads_parser.add_argument("--limit", type=int, default=10, help="Number of leads to display")

    drafts_parser = subparsers.add_parser("drafts", help="List and preview email drafts")
    drafts_parser.add_argument("--status", type=str, help="Filter by status (e.g. APPROVED, PENDING_APPROVAL, SENT)")
    drafts_parser.add_argument("--limit", type=int, default=20, help="Number of drafts to display")

    send_one_parser = subparsers.add_parser("send-one", help="Send a single draft immediately")
    send_one_parser.add_argument("draft_id", type=str, help="The ID of the draft to send")

    subparsers.add_parser("approve-all", help="Approve all pending drafts")
    subparsers.add_parser("send-all", help="Deliver all approved drafts via SMTP")
    subparsers.add_parser("test-smtp", help="Test Gmail SMTP connection")

    args = parser.parse_args()
    if not args.command or args.command == "status":
        cmd_status(args)
    elif args.command == "leads":
        cmd_leads(args)
    elif args.command == "drafts":
        cmd_drafts(args)
    elif args.command == "send-one":
        cmd_send_one(args)
    elif args.command == "approve-all":
        cmd_approve_all(args)
    elif args.command == "send-all":
        cmd_send_all(args)
    elif args.command == "test-smtp":
        cmd_test_smtp(args)



if __name__ == "__main__":
    main()
