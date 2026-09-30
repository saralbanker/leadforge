#!/usr/bin/env python3
"""Re-renders approved draft subjects using the 50-character ceiling,
1-3 word compressed topics, and reduced closing-noun template shapes.
Guarantees zero recipient duplication across approved drafts.
"""

import sys
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from leadforge.outreach.cleaning import clean_company_name
from leadforge.outreach.router import CampaignRouter
from leadforge.outreach.generator import compress_specific_topic
from leadforge.outreach.quality import EmailQualityEngine

# Pre-computed verified grounded topics from website scrapes (1-3 words)
VERIFIED_TOPICS = {
    '01a0b781-e8cf-7357-bf64-cab55c9c8359': 'precision instrumentation',
    '01a0b781-e8f0-7c77-b3fa-2bb17137288e': 'servo voltage stabilizers',
    '01a0b781-e910-7d8b-9786-5222623e1865': 'gold and silver',
    '01a0b781-e92c-7762-8859-3583ef6b0fa3': 'construction chemicals',
    '01a0b781-e94d-700c-a2d7-202714995e02': 'reactive dyes',
    '01a0b781-e96c-7eac-8e36-1f60fede53fb': 'steel pipes',
    '01a0b781-e98f-7548-8700-5181671ffda5': 'rubber liners',
    '01a0b781-e9ae-7a40-ad03-480f7fc39690': "women's clothing",
    '01a0b781-e9ce-71a0-b7c3-a317a833c465': 'transformer laminations',
    '01a0b781-e9ee-7140-97e9-3a2cce1608da': 'steel pipes',
    '01a0b782-d486-74aa-9191-79c7fc5bed4b': 'stents',
    '01a0b782-d4a4-7ab3-a909-990f7f68ab1b': 'hydraulic pumps',
    '01a0b782-d4c2-76ea-97b5-5e47d7e1d3f8': 'hdpe tarpaulins',
    '01a0b782-d4e0-7a02-b022-c1897b557f0a': 'textiles',
    '01a0b782-d501-7f29-b7e9-31e3d36e9a0e': 'dietary supplements',
    '01a0b782-d521-7153-b3e9-050e61ca6fe4': 'cpvc upvc pipes',
    '01a0b782-d542-71c9-b693-203de17a3e05': 'bangles',
    '01a0b782-d55e-7824-a094-5bda037ae9d6': 'aromatherapy products',
    '01a0b782-d581-77cf-975d-649c1069f21d': 'fire extinguishers',
    '01a0b782-d5a5-7cf2-914a-6e511a382e90': 'tea',
    '01a0b783-c066-74d1-9fd2-4f1fa8989115': 'jewelry',
    '01a0b783-c086-7bb4-ab1e-e4f8257b37b2': 'process equipment',
    '01a0b783-c0a3-7ce7-a8fd-cf1079b3d03d': 'engineering plastics',
    '01a0b783-c0c4-7fc9-a40f-a3dd33bb6cc3': 'sheet metal components',
    '01a0b783-c0e4-7b62-8239-6351d3c11b80': 'v belt pulleys',
    '01a0b783-c105-7feb-b209-918765cd6b86': 'tarpaulins',
    '01a0b783-c144-7336-8c12-0b7b9c620da4': 'industrial springs',
    '01a0b783-c165-7573-a2d2-4cb45940e144': 'textile machinery',
    '01a0b783-c183-7d8b-b702-a615b4d747db': 'dairy machinery',
    '01a0b784-ac2d-7f68-8c2c-5e5918e5d8c3': 'colour changing pigments',
    '01a0b784-ac4e-7f72-b398-1c8925c7e651': 'ceramics',
    '01a0b784-ac70-753f-bca9-4ea46facc2d5': 'cassia tora gum',
    '01a0b784-ac8d-73ad-9fc4-073a41be140e': 'industrial valves',
    '01a0b784-acae-7580-a79f-2d9c8ec2e1ba': 'cz gold jewelry',
    '01a0b784-acd0-70fe-ae82-7e2e93ec99dd': 'gold jewellery',
    '01a0b784-acf2-7dd7-a4f4-839a03a0351c': 'dyes intermediates',
    '01a0b784-ad37-7b13-8b8e-c7c4356405b7': 'caps and hats',
    '01a0b784-ad57-7ebe-bb48-8b99265a3433': 'sodium silicate',
    '01a0b785-982c-7422-b03f-27883044f15a': 'elevators and escalators',
}

# Baseline uncompacted subjects recorded prior to length budget fix
BASELINE_SUBJECTS = {
    '01a0b781-e8cf-7357-bf64-cab55c9c8359': 'inquiry re: temperature & pressure instruments at Aavad Instrument', # 64
    '01a0b781-e8f0-7c77-b3fa-2bb17137288e': 'note on servo voltage stabilizers at ProtekG Power Electronics', # 63
    '01a0b781-e910-7d8b-9786-5222623e1865': 'an idea for gold and silver inquiries for Suvidhi Gold', # 54
    '01a0b781-e92c-7762-8859-3583ef6b0fa3': 'construction chemicals workflow at Konkem Industries', # 53
    '01a0b781-e94d-700c-a2d7-202714995e02': 'question regarding reactive dyes at JAY Chemical Industries', # 60
    '01a0b781-e96c-7eac-8e36-1f60fede53fb': 'regarding steel pipes catalog for Asian Tubes', # 46
    '01a0b781-e98f-7548-8700-5181671ffda5': 'brief thought on rubber liners at Kedar Rubber Products', # 56
    '01a0b781-e9ae-7a40-ad03-480f7fc39690': "inquiry re: women's clothing requirements at VLF TRENDS", # 55
    '01a0b781-e9ce-71a0-b7c3-a317a833c465': 'transformer laminations specs for Vardhaman Stampings', # 53
    '01a0b781-e9ee-7140-97e9-3a2cce1608da': 'note on steel pipes inquiries at Rajsagar Steel', # 48
    '01a0b782-d486-74aa-9191-79c7fc5bed4b': 'stents operations at Sahajanand Medical Technologies', # 52
    '01a0b782-d4a4-7ab3-a909-990f7f68ab1b': 'online catalog for Shivam Hydraulic Pumps & Cylinders', # 53
    '01a0b782-d4c2-76ea-97b5-5e47d7e1d3f8': 'quick thought on hdpe tarpaulins specs for Noble Brothers', # 57
    '01a0b782-d4e0-7a02-b022-c1897b557f0a': 'quick note on textiles production at K. Rudra Textiles', # 54
    '01a0b782-d501-7f29-b7e9-31e3d36e9a0e': 'inquiry re: dietary supplements at Marudhar Impex', # 49
    '01a0b782-d521-7153-b3e9-050e61ca6fe4': 'question regarding cpvc upvc pipes inquiries at BHAGVAT PIPE', # 60
    '01a0b782-d542-71c9-b693-203de17a3e05': 'brief note on bangles workflow at NAKODA BANGLES', # 48
    '01a0b782-d55e-7824-a094-5bda037ae9d6': 'inquiry re: aromatherapy products inquiries at Sanju sales', # 58
    '01a0b782-d581-77cf-975d-649c1069f21d': 'note on fire extinguishers specs for Firestop', # 45
    '01a0b782-d5a5-7cf2-914a-6e511a382e90': 'checking in on tea inquiries at HASMUKH TEA DEPOT', # 49
    '01a0b783-c066-74d1-9fd2-4f1fa8989115': 'checking in on jewelry catalog for Y K PEARLS', # 46
    '01a0b783-c086-7bb4-ab1e-e4f8257b37b2': 'question regarding process equipment inquiries at Mazda', # 56
    '01a0b783-c0a3-7ce7-a8fd-cf1079b3d03d': 'an idea for engineering plastics at Krish Plastic Industries', # 60
    '01a0b783-c0c4-7fc9-a40f-a3dd33bb6cc3': 'a thought on sheet metal components inquiries at Khyati Industries Sheet Metal Parts manufacturer', # 97
    '01a0b783-c0e4-7b62-8239-6351d3c11b80': 'question regarding v belt pulleys at Dhara Industries', # 54
    '01a0b783-c105-7feb-b209-918765cd6b86': 're: tarpaulins inquiries at Shri Ambica Tripal', # 47
    '01a0b783-c144-7336-8c12-0b7b9c620da4': 'regarding industrial springs workflow at SPRING MANUFACTURING CO', # 65
    '01a0b783-c165-7573-a2d2-4cb45940e144': 'textile machinery inquiries at Bhagwati engineering corporation', # 63
    '01a0b783-c183-7d8b-b702-a615b4d747db': 'dairy machinery specs for Creamtech Industries', # 46
    '01a0b784-ac2d-7f68-8c2c-5e5918e5d8c3': 'regarding colour changing pigments at Americos industries Inc', # 62
    '01a0b784-ac4e-7f72-b398-1c8925c7e651': 'an idea for ceramics production at Crystal Ceramic Industries', # 61
    '01a0b784-ac70-753f-bca9-4ea46facc2d5': 'details on cassia tora gum powder for DWARKESH INDUSTRIES', # 57
    '01a0b784-ac8d-73ad-9fc4-073a41be140e': 'regarding industrial valves catalog for Allied Valves', # 53
    '01a0b784-acae-7580-a79f-2d9c8ec2e1ba': 'note on cz gold jewelry requirements at KALA GOLD', # 50
    '01a0b784-acd0-70fe-ae82-7e2e93ec99dd': 'regarding gold jewellery inquiries at Ashish Jewellery Mart', # 59
    '01a0b784-acf2-7dd7-a4f4-839a03a0351c': 'dyes intermediates workflow at Rohan Dyes & Intermediates Limited', # 66
    '01a0b784-ad37-7b13-8b8e-c7c4356405b7': 'details on caps and hats catalog for Bombay Hosiery House', # 57
    '01a0b784-ad57-7ebe-bb48-8b99265a3433': 'sodium silicate operations at SAHAJANAND INDUSTRIES LIMITED', # 59
    '01a0b785-982c-7422-b03f-27883044f15a': 'elevators and escalators specs for Orbis Elevator Co. Ltd.', # 58
}


def main():
    db_path = BASE / "leadforge.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Step 1: Ensure strict recipient-level deduplication
    # If any recipient_email has multiple approved drafts, keep the earliest and cancel duplicates.
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
        SELECT ed.id as draft_id, b.id as biz_id, b.name as raw_name, ed.subject as current_subject,
               ed.campaign_name, ed.body, b.website_domain, bt.name as category
        FROM email_drafts ed
        JOIN opportunities o ON ed.opportunity_id = o.id
        JOIN businesses b ON o.business_id = b.id
        LEFT JOIN business_types bt ON b.business_type_id = bt.id
        WHERE ed.status = 'APPROVED'
        ORDER BY ed.created_at ASC, ed.id ASC
    """)
    drafts = cursor.fetchall()
    print(f"Found {len(drafts)} approved drafts to re-render.")
    assert len(drafts) == 39, f"Expected exactly 39 approved drafts, found {len(drafts)}"

    router = CampaignRouter(config_path=BASE / "campaign_routing.yaml")
    records = []

    for idx, d in enumerate(drafts, 1):
        draft_id = d["draft_id"]
        biz_id = d["biz_id"]
        raw_name = d["raw_name"]
        clean_name = clean_company_name(raw_name)
        camp_name = d["campaign_name"]
        cat = d["category"] or "Manufacturing"

        topic = VERIFIED_TOPICS.get(draft_id)
        if not topic:
            topic = cat.lower()

        # Compress to 1-3 words
        compressed_topic = compress_specific_topic(topic, max_words=3)

        # Match campaign config
        camp = next((c for c in router.campaigns if c["name"] == camp_name), None)
        if not camp:
            camp = router.get_default_campaign()

        copy_tpl = camp.get("copy_template", {})
        subject_tpl = CampaignRouter.select_subject(copy_tpl, business_id=biz_id)

        # Render with 50-character ceiling cascade
        new_subject = CampaignRouter.render_subject(
            template=subject_tpl,
            business_name=raw_name,
            specific_topic=compressed_topic,
            topic_focus=compressed_topic,
            category=cat,
            max_chars=EmailQualityEngine.MAX_SUBJECT_LENGTH,
        )

        # Validate subject quality and length
        is_valid, issues = EmailQualityEngine.validate_subject(
            new_subject,
            max_chars=EmailQualityEngine.MAX_SUBJECT_LENGTH,
            business_name=raw_name,
        )
        if not is_valid:
            print(f"  [ERROR] Draft {draft_id} ({clean_name}) failed validation: {issues}")
            raise ValueError(f"Draft {draft_id} subject invalid: {issues}")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            "UPDATE email_drafts SET subject = ?, updated_at = ? WHERE id = ?",
            (new_subject, now_str, draft_id),
        )

        baseline_subj = BASELINE_SUBJECTS.get(draft_id, d["current_subject"])
        records.append({
            "idx": idx,
            "draft_id": draft_id,
            "business": clean_name,
            "topic": compressed_topic,
            "old_subject": baseline_subj,
            "old_len": len(baseline_subj),
            "new_subject": new_subject,
            "new_len": len(new_subject),
        })

    conn.commit()
    conn.close()

    df = pd.DataFrame(records)
    print("\n=======================================================")
    print("        SUBJECT LINE RE-RENDERING METRICS SUMMARY       ")
    print("=======================================================")
    print(f"Total Approved Drafts: {len(df)}")
    old_med = df["old_len"].median()
    old_min = df["old_len"].min()
    old_max = df["old_len"].max()
    old_gt60 = (df["old_len"] > 60).sum()
    old_gt50 = (df["old_len"] > 50).sum()
    old_pct60 = old_gt60 / len(df) * 100
    old_pct50 = old_gt50 / len(df) * 100

    new_med = df["new_len"].median()
    new_min = df["new_len"].min()
    new_max = df["new_len"].max()
    new_gt60 = (df["new_len"] > 60).sum()
    new_gt50 = (df["new_len"] > 50).sum()
    new_pct60 = new_gt60 / len(df) * 100
    new_pct50 = new_gt50 / len(df) * 100

    print(f"BASELINE (Pre-Budget): Median = {old_med:.1f} chars | Min = {old_min} | Max = {old_max} | >60 chars = {old_gt60}/{len(df)} ({old_pct60:.1f}%) | >50 chars = {old_gt50}/{len(df)} ({old_pct50:.1f}%)")
    print(f"COMPACTED (Post-Fix):  Median = {new_med:.1f} chars | Min = {new_min} | Max = {new_max} | >60 chars = {new_gt60}/{len(df)} ({new_pct60:.1f}%) | >50 chars = {new_gt50}/{len(df)} ({new_pct50:.1f}%)")
    print("=======================================================\n")

    for r in records:
        print(f"{r['idx']:2d}. [{r['new_len']:2d} chars] {r['business'][:25]:25s} | {r['new_subject']:48s}")


if __name__ == "__main__":
    main()
