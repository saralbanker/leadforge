#!/usr/bin/env python3
"""Rerenders all 39 approved drafts in leadforge/leadforge.db with grounded per-business
contact bridge sentences, validating compliance with the ~40-60 word budget,
zero location collisions, and zero diagnosis claims.
"""

import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(BASE))

from leadforge.outreach.cleaning import clean_company_name, shorten_company_name
from leadforge.outreach.content_classifier import classify_scraped_content
from leadforge.outreach.generator import generate_contact_bridge
from leadforge.outreach.router import CampaignRouter
from leadforge.outreach.quality import EmailQualityEngine


def extract_hook(body: str) -> str:
    """Extracts the grounded observation hook (Paragraph 1)."""
    core = (body or "").split("\n\n---")[0].strip()
    paras = [p.strip() for p in core.split("\n\n") if p.strip()]
    return paras[0] if paras else ""


def main():
    db_path = BASE / "leadforge.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ed.id as draft_id, b.id as biz_id, b.name as raw_name, ed.recipient_email,
               a.city, a.area, ed.subject, ed.body as old_body, ed.campaign_name,
               ed.hook_source, ed.quality_score
        FROM email_drafts ed
        JOIN opportunities o ON ed.opportunity_id = o.id
        JOIN businesses b ON o.business_id = b.id
        LEFT JOIN addresses a ON b.id = a.business_id
        WHERE ed.status = 'APPROVED'
          AND ed.id IN (
              SELECT id FROM (
                  SELECT id, MIN(created_at)
                  FROM email_drafts
                  WHERE status = 'APPROVED'
                  GROUP BY LOWER(recipient_email)
              )
          )
        ORDER BY ed.created_at ASC, ed.id ASC
    """)
    drafts = cursor.fetchall()
    print(f"Loaded {len(drafts)} deduplicated approved drafts from {db_path}.")
    assert len(drafts) == 39, f"Expected 39 drafts, found {len(drafts)}"

    router = CampaignRouter(config_path=BASE / "campaign_routing.yaml")
    results = []

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
        assert hook, f"Draft {draft_id} missing hook"

        # Load scraped text
        cursor.execute("""
            SELECT wa.issues_json FROM website_audits wa
            JOIN digital_presences dp ON wa.digital_presence_id = dp.id
            WHERE dp.business_id = ?
            ORDER BY wa.created_at DESC LIMIT 1
        """, (biz_id,))
        wa_row = cursor.fetchone()
        scraped_text = ""
        if wa_row and wa_row[0]:
            cached = json.loads(wa_row[0])
            scraped_text = cached.get("cleaned_text", "")

        classification = classify_scraped_content(scraped_text)

        # Generate contact bridge
        bridge, bridge_source = generate_contact_bridge(
            business_name=clean_name,
            raw_name=raw_name,
            city=city,
            hook=hook,
            specific_topic=subject,
            scraped_text=scraped_text,
            classification=classification,
            business_id=biz_id,
        )

        # Validate bridge standalone
        b_valid, b_issues = EmailQualityEngine.validate_bridge(
            bridge,
            is_usable=classification.is_usable,
            has_website=bool(classification.is_usable or scraped_text),
            observation_hook=hook,
            city=city,
        )
        assert b_valid, f"Bridge failed validation for draft {draft_id}: {b_issues}"

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
            contact_bridge=bridge,
            city=city,
            business_name_full=raw_name,
            specific_topic=subject,
            topic_focus=subject,
        )

        # Validate with EmailQualityEngine.validate_body
        is_valid, issues = EmailQualityEngine.validate_body(
            new_body,
            city=city,
            is_usable=classification.is_usable,
            has_website=bool(classification.is_usable or scraped_text),
        )
        if not is_valid:
            raise ValueError(f"Draft {draft_id} failed validate_body: {issues}")

        # Score with EmailQualityEngine.score_draft
        quality = EmailQualityEngine.score_draft(new_body)
        score = quality["quality_score"]
        passed = quality["passed"]
        assert passed, f"Draft {draft_id} failed score_draft: {quality['issues']}"

        # Save to database
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute("""
            UPDATE email_drafts
            SET body = ?, quality_score = ?, quality_passed = 1, quality_issues = ?, updated_at = ?
            WHERE id = ?
        """, (new_body, score, json.dumps(quality["issues"]), now_str, draft_id))

        words = len(new_body.split())
        chars = len(new_body)
        results.append({
            "idx": idx,
            "draft_id": draft_id,
            "clean_name": clean_name,
            "bridge": bridge,
            "bridge_source": bridge_source,
            "words": words,
            "chars": chars,
        })
        print(f"[{idx:2d}/39] {clean_name} ({words}w, {chars}c) [{bridge_source}] -> {bridge}")

    conn.commit()
    conn.close()

    bridges = [r["bridge"] for r in results]
    unique_bridges = len(set(bridges))
    words_list = [r["words"] for r in results]

    print("\n--- Summary Verification ---")
    print(f"Total drafts processed: {len(results)}")
    print(f"Unique bridges: {unique_bridges} / {len(results)} ({unique_bridges/len(results)*100:.1f}%)")
    print(f"Word count: min={min(words_list)}, median={sorted(words_list)[len(words_list)//2]}, max={max(words_list)}")
    print(f"Drafts in 40-60 range: {sum(1 for w in words_list if 40 <= w <= 60)} / {len(results)}")


if __name__ == "__main__":
    main()
