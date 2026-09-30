#!/usr/bin/env python3
"""Regenerates the approved email drafts in leadforge.db using updated templates,
cleaned company names, validated recipient emails, real scraped website content,
grounded product topics, and Ollama hook generation.
"""

import sys
import json
import uuid
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from leadforge.outreach.cleaning import clean_company_name
from leadforge.normalizer import normalize_email, is_valid_recipient_email
from leadforge.outreach.router import CampaignRouter
from leadforge.outreach.generator import OllamaHookGenerator
from leadforge.outreach.quality import EmailQualityEngine
from leadforge.outreach.discovery import WebsiteAuditor


class SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def get_website_text(biz_id: str, domain: str, cursor, conn) -> str:
    """Retrieves cached scraped text from website_audits or runs a fresh audit."""
    if not domain:
        return ""

    try:
        cursor.execute(
            """
            SELECT wa.issues_json FROM website_audits wa
            JOIN digital_presences dp ON wa.digital_presence_id = dp.id
            WHERE dp.business_id = ?
            ORDER BY wa.created_at DESC LIMIT 1
            """,
            (biz_id,),
        )
        row = cursor.fetchone()
        if row and row["issues_json"]:
            data = json.loads(row["issues_json"])
            if data.get("cleaned_text"):
                return data["cleaned_text"]
    except Exception:
        pass

    try:
        audit = WebsiteAuditor.audit_website(domain)
        cleaned_text = audit.get("cleaned_text", "")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor.execute("SELECT id FROM digital_presences WHERE business_id = ?", (biz_id,))
        dp_row = cursor.fetchone()
        if dp_row:
            presence_id = dp_row["id"]
        else:
            presence_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO digital_presences (id, business_id, website_url, has_website, platform, ssl_valid, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (presence_id, biz_id, domain, 1, audit.get("cms", "Custom"), 1 if audit.get("ssl_valid") else 0, now_str, now_str),
            )

        audit_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO website_audits (id, digital_presence_id, page_speed_ms, issues_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (audit_id, presence_id, int(audit.get("load_time_seconds", 0.0) * 1000), json.dumps(audit), now_str, now_str),
        )
        conn.commit()
        return cleaned_text
    except Exception as e:
        print(f"  [Audit Error for {domain}]: {e}")
        return ""


def main():
    db_path = BASE / "leadforge.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            ed.id as draft_id,
            ed.opportunity_id,
            b.id as business_id,
            b.name as business_name,
            COALESCE(b.contact_email, ed.recipient_email) as contact_email,
            COALESCE(b.website_domain, '') as website_domain,
            b.rating,
            b.review_count,
            COALESCE(bt.name, 'Manufacturing') as category,
            COALESCE(a.city, 'Ahmedabad') as city,
            COALESCE(a.area, 'Ahmedabad') as area
        FROM email_drafts ed
        JOIN opportunities o ON ed.opportunity_id = o.id
        JOIN businesses b ON o.business_id = b.id
        LEFT JOIN business_types bt ON b.business_type_id = bt.id
        LEFT JOIN addresses a ON b.id = a.business_id
        WHERE ed.status = 'APPROVED'
        ORDER BY ed.created_at ASC, ed.id ASC
    """)
    drafts = cursor.fetchall()
    print(f"Found {len(drafts)} approved drafts to regenerate.")

    router = CampaignRouter()
    generator = OllamaHookGenerator()

    for idx, d in enumerate(drafts, 1):
        draft_id = d["draft_id"]
        biz_id = d["business_id"]
        raw_name = d["business_name"]
        clean_name = clean_company_name(raw_name)
        category = d["category"] or "Manufacturing"
        area = d["area"] or "Ahmedabad"
        city = d["city"] or "Ahmedabad"
        email = normalize_email(d["contact_email"])
        website = d["website_domain"] or ""
        rating = d["rating"]
        review_count = d["review_count"]

        # Validate recipient email
        valid, email_err = is_valid_recipient_email(email)
        if not valid:
            print(f"[{idx}/{len(drafts)}] WARNING: Invalid email '{email}' for {clean_name}: {email_err}")

        # 1. Fetch real scraped website text
        scraped_text = get_website_text(biz_id, website, cursor, conn)
        print(f"[{idx}/{len(drafts)}] Processing '{clean_name}' (website: {website or 'None'}, text len: {len(scraped_text)})")

        # 2. Route campaign
        campaign = router.route_lead(
            category=category,
            has_website=bool(website),
        )
        if not campaign:
            campaign = router.get_default_campaign()

        premise_verified = campaign.get("premise_verified", True)

        # 3. Generate Hook & Specific Topic via Ollama
        hook, hook_source, specific_topic = generator.generate_hook_with_details(
            business_name=clean_name,
            category=category,
            city=city,
            area=area,
            has_website=bool(website),
            scraped_text=scraped_text,
            rating=rating,
            review_count=review_count,
            premise_verified=premise_verified,
        )

        # 4. Assemble Subject & Body
        copy_tpl = campaign.get("copy_template", {})
        subject_tpl = CampaignRouter.select_subject(copy_tpl, business_id=biz_id)
        body_tpl = CampaignRouter.select_body(copy_tpl, business_id=biz_id, premise_verified=premise_verified)

        topic_focus = specific_topic or (category.lower() if category else "manufacturing")
        vars_dict = SafeDict({
            "business_name": clean_name,
            "business_name_full": raw_name,
            "city": city,
            "area": area,
            "category": category,
            "observation_hook": hook or f"I noticed {clean_name} operates in {area}.",
            "rating": str(rating) if rating else "",
            "review_count": str(review_count) if review_count else "",
            "website_domain": website,
            "specific_topic": specific_topic,
            "topic_focus": topic_focus,
        })
        subject = CampaignRouter.render_subject(
            subject_tpl,
            **vars_dict,
        )
        body = body_tpl.format_map(vars_dict)

        # 5. Quality Score
        quality = EmailQualityEngine.score_draft(body)
        quality_score = quality["quality_score"]
        quality_passed = quality["passed"]
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cursor.execute(
            """
            UPDATE email_drafts
            SET campaign_name = ?, recipient_email = ?, subject = ?, body = ?,
                quality_score = ?, quality_passed = ?, quality_issues = ?, hook_source = ?, updated_at = ?
            WHERE id = ?
            """,
            (campaign["name"], email, subject, body, quality_score,
             1 if quality_passed else 0, json.dumps(quality["issues"]), hook_source, now_str, draft_id),
        )
        conn.commit()
        print(f"  -> Subject: '{subject}' | Topic: '{specific_topic}' | Source: {hook_source} | Score: {quality_score}")

    conn.close()
    print("All approved drafts regenerated.")


if __name__ == "__main__":
    main()
