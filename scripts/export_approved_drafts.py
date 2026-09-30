#!/usr/bin/env python3
import sqlite3
from pathlib import Path

def main():
    db_path = Path("leadforge.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            ed.id,
            COALESCE(b.name, 'Unknown Business') as business_name,
            COALESCE(ed.recipient_email, '') as recipient_email,
            COALESCE(ed.campaign_name, 'Outreach') as campaign_name,
            COALESCE(ed.subject, '') as subject,
            COALESCE(ed.quality_score, 0) as quality_score,
            COALESCE(ed.hook_source, 'unspecified') as hook_source,
            COALESCE(ed.created_at, '') as created_at
        FROM email_drafts ed
        LEFT JOIN opportunities o ON o.id = ed.opportunity_id
        LEFT JOIN businesses b ON b.id = o.business_id
        WHERE ed.status = 'APPROVED'
        ORDER BY ed.created_at ASC, ed.id ASC
    """)
    rows = cur.fetchall()

    lines = [
        "# Approved Email Drafts Inventory",
        "",
        f"- **Total Approved Drafts:** {len(rows)}",
        "- **Database:** `leadforge.db`",
        "- **Extraction Timestamp:** 2026-09-20",
        "",
        "| # | Business Name | Recipient Email | Campaign | Subject Line | Quality Score | Hook Source | Draft ID |",
        "|---|---|---|---|---|:---:|:---:|---|",
    ]

    for idx, r in enumerate(rows, 1):
        biz = r["business_name"].replace("|", "-").strip()
        subj = r["subject"].replace("|", "-").strip()
        camp = r["campaign_name"].replace("|", "-").strip()
        email = r["recipient_email"].strip()
        score = r["quality_score"]
        hook = r["hook_source"].strip()
        d_id = r["id"]
        lines.append(f"| {idx} | {biz} | `{email}` | {camp} | {subj} | {score} | `{hook}` | `{d_id}` |")

    content = "\n".join(lines) + "\n"

    for target in [
        Path("docs/campaign_readiness/APPROVED_EMAIL_DRAFTS.md"),
        Path("/mnt/data/rj/email_auto/docs/campaign_readiness/APPROVED_EMAIL_DRAFTS.md"),
    ]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"Wrote {len(rows)} drafts to {target}")

if __name__ == "__main__":
    main()
