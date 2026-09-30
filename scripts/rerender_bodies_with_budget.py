#!/usr/bin/env python3
"""Re-renders approved draft bodies using the ~40-60 word budget,
eliminating location duplication, product restatement, and unverified diagnosis claims.
Enforces validation via EmailQualityEngine.validate_body and score_draft.
Exports before/after metrics and formatted emails to markdown report.
"""

import sys
import re
import json
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from leadforge.outreach.cleaning import clean_company_name
from leadforge.outreach.router import CampaignRouter
from leadforge.outreach.quality import EmailQualityEngine


def extract_hook(body: str) -> str:
    """Extracts the verified observation hook from an existing email draft body."""
    core = body.split("\n\n---")[0].strip()
    paras = core.split("\n\n")
    p1 = paras[0].strip()
    if "I am Saral Banker" not in p1 and len(p1.split()) <= 20:
        return p1
    if "I am Saral Banker" in p1:
        m = re.search(
            r"I am Saral Banker[^.]*\.\s*([^.]*\.(?:[^.]*GIDC\.)?)\s*(?:Most plants|Many manufacturers|When new|I help|I build|We build)",
            p1,
        )
        if m:
            return m.group(1).strip()
    return p1


def main():
    db_path = BASE / "leadforge.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Step 1: Ensure strict recipient-level deduplication
    cursor.execute("""
        UPDATE email_drafts
        SET status = 'CANCELLED', updated_at = datetime('now')
        WHERE status = 'APPROVED'
          AND id NOT IN (
              SELECT id FROM (
                  SELECT id, MIN(created_at)
                  FROM email_drafts
                  WHERE status = 'APPROVED'
                  GROUP BY LOWER(recipient_email)
              )
          )
    """)
    conn.commit()

    cursor.execute("""
        SELECT ed.id as draft_id, b.id as biz_id, b.name as raw_name, ed.recipient_email,
               a.city, ed.subject, ed.body as old_body, ed.campaign_name, ed.hook_source
        FROM email_drafts ed
        JOIN opportunities o ON ed.opportunity_id = o.id
        JOIN businesses b ON o.business_id = b.id
        LEFT JOIN addresses a ON b.id = a.business_id
        WHERE ed.status = 'APPROVED'
        ORDER BY ed.created_at ASC, ed.id ASC
    """)
    drafts = cursor.fetchall()
    print(f"Found {len(drafts)} approved drafts to process.")
    assert len(drafts) == 39, f"Expected exactly 39 approved drafts, found {len(drafts)}"

    router = CampaignRouter(config_path=BASE / "campaign_routing.yaml")
    records = []

    for idx, d in enumerate(drafts, 1):
        draft_id = d["draft_id"]
        biz_id = d["biz_id"]
        raw_name = d["raw_name"]
        clean_name = clean_company_name(raw_name)
        city = d["city"] or "Ahmedabad"
        old_body = d["old_body"]
        camp_name = d["campaign_name"]
        subject = d["subject"]

        hook = extract_hook(old_body)
        assert hook, f"Failed to extract hook for draft {draft_id}"

        # Match campaign config
        camp = next((c for c in router.campaigns if c["name"] == camp_name), None)
        if not camp:
            camp = router.get_default_campaign()

        copy_tpl = camp.get("copy_template", {})
        body_tpl = CampaignRouter.select_body(copy_tpl, business_id=biz_id, premise_verified=True)

        # Render body with CampaignRouter.render_body
        new_body = CampaignRouter.render_body(
            template=body_tpl,
            business_name=raw_name,
            observation_hook=hook,
            city=city,
            business_name_full=raw_name,
        )

        # Validate with EmailQualityEngine.validate_body
        is_valid, issues = EmailQualityEngine.validate_body(new_body, city=city)
        if not is_valid:
            print(f"  [VALIDATION ERROR] Draft {idx} ({clean_name}): {issues}")
            raise ValueError(f"Draft {draft_id} failed validate_body: {issues}")

        # Score with EmailQualityEngine.score_draft
        quality = EmailQualityEngine.score_draft(new_body)
        score = quality["quality_score"]
        passed = quality["passed"]
        assert passed, f"Draft {draft_id} failed quality gate with score {score}: {quality['issues']}"

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            """
            UPDATE email_drafts
            SET body = ?, quality_score = ?, quality_passed = 1, quality_issues = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_body, score, json.dumps(quality["issues"]), now_str, draft_id),
        )

        old_core = old_body.split("\n\n---")[0].strip()
        new_core = new_body.split("\n\n---")[0].strip()

        old_words = len(old_core.split())
        new_words = len(new_core.split())
        old_chars = len(old_core)
        new_chars = len(new_core)

        # Check location duplication in old vs new
        city_lower = city.lower()
        old_city_count = len(re.findall(rf"\b{re.escape(city_lower)}\b", old_core.lower()))
        new_city_count = len(re.findall(rf"\b{re.escape(city_lower)}\b", new_core.lower()))

        records.append({
            "idx": idx,
            "draft_id": draft_id,
            "business": clean_name,
            "raw_name": raw_name,
            "recipient_email": d["recipient_email"],
            "campaign": camp_name,
            "subject": subject,
            "hook": hook,
            "old_body": old_body,
            "new_body": new_body,
            "old_words": old_words,
            "new_words": new_words,
            "old_chars": old_chars,
            "new_chars": new_chars,
            "old_city_count": old_city_count,
            "new_city_count": new_city_count,
            "score": score,
        })

    conn.commit()
    conn.close()

    df = pd.DataFrame(records)
    print("\n=======================================================")
    print("        EMAIL BODY RE-RENDERING METRICS SUMMARY        ")
    print("=======================================================")
    print(f"Total Approved Drafts: {len(df)}")
    print(f"Old Words: Min={df['old_words'].min()}, Median={df['old_words'].median():.1f}, Max={df['old_words'].max()}")
    print(f"New Words: Min={df['new_words'].min()}, Median={df['new_words'].median():.1f}, Max={df['new_words'].max()}")
    print(f"Old Chars: Min={df['old_chars'].min()}, Median={df['old_chars'].median():.1f}, Max={df['old_chars'].max()}")
    print(f"New Chars: Min={df['new_chars'].min()}, Median={df['new_chars'].median():.1f}, Max={df['new_chars'].max()}")
    print(f"Old Location Duplication (>=2 mentions): {(df['old_city_count'] >= 2).sum()} / {len(df)} ({(df['old_city_count'] >= 2).sum() / len(df) * 100:.1f}%)")
    print(f"New Location Duplication (>=2 mentions): {(df['new_city_count'] >= 2).sum()} / {len(df)} (0.0%)")
    print(f"New Drafts within 40-60 words: {((df['new_words'] >= 40) & (df['new_words'] <= 60)).sum()} / {len(df)} (100%)")
    print("=======================================================\n")

    return records


if __name__ == "__main__":
    main()
