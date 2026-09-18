"""Autonomous 24/7 Background Daemon for Orvion (LeadForge).

Runs unattended 24/7 to:
1. Harvest local businesses based on campaign_targets.yaml (Vatva & Odhav clusters).
2. Deep-enrich contact info and verify MX records.
3. Generate evidence-bound observation hooks via local Ollama.
4. Auto-approve drafts passing the strict 100-point quality check.
5. Dispatch emails via personal Gmail SMTP during business hours (9:30 - 17:30 IST) with human delays.
6. Auto-dispatch multi-touch follow-ups (Touch 2 on Day 3, Touch 3 on Day 7).
7. Poll IMAP inbox every 15 minutes and dispatch instant Telegram alerts on positive replies.
"""

import asyncio
import os
import random
import time
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

from leadforge.config import BASE_DIR, OLLAMA_API_URL, DEFAULT_LLM_MODEL
from leadforge.database import get_db_connection, append_event, uuidv7
from leadforge.repositories.settings import SettingsCache
from leadforge.outreach.deliverer import SMTPEmailDeliverer
from leadforge.outreach.ramp import delivery_allowance
from leadforge.outreach.router import CampaignRouter
from leadforge.outreach.generator import OllamaHookGenerator
from leadforge.outreach.quality import EmailQualityEngine
from leadforge.communication.sequencer import FollowupSequencer
from leadforge.communication.inbox import IMAPInboxMonitor
from leadforge.communication.telegram_notifier import send_telegram_alert
from leadforge.utils import get_logger

logger = get_logger()

TARGETS_FILE = BASE_DIR / "campaign_targets.yaml"
IST_OFFSET = timedelta(hours=5, minutes=30)


class SafeDict(dict):
    """Dictionary that returns empty string for missing keys during string formatting."""

    def __missing__(self, key: str) -> str:
        return ""


def get_ist_now() -> datetime:
    """Returns current time in Indian Standard Time (IST)."""
    return datetime.now(timezone.utc) + IST_OFFSET


def is_daylight_sending_window() -> bool:
    """True if current IST time is between 09:30 and 17:30 on weekdays (Mon-Fri)."""
    now_ist = get_ist_now()
    # 0 = Monday, 4 = Friday, 5 = Saturday, 6 = Sunday
    if now_ist.weekday() >= 5:
        return False
    hour = now_ist.hour
    minute = now_ist.minute
    current_minutes = hour * 60 + minute
    start_minutes = 9 * 60 + 30   # 09:30 AM
    end_minutes = 17 * 60 + 30    # 05:30 PM
    return start_minutes <= current_minutes <= end_minutes


class AutonomousOrvionEngine:
    """Autonomous coordinator managing discovery, email generation, delivery, and replies."""

    def __init__(self):
        self.settings = SettingsCache()
        self.deliverer = SMTPEmailDeliverer()
        self.sequencer = FollowupSequencer()
        self.inbox_monitor = IMAPInboxMonitor()
        self.router = CampaignRouter()
        self.generator = OllamaHookGenerator()
        self._last_imap_poll: float = 0.0
        self._last_discovery_run: float = 0.0

    def load_targets(self) -> List[Dict[str, Any]]:
        """Loads target clusters from campaign_targets.yaml."""
        if not TARGETS_FILE.exists():
            return []
        try:
            with open(TARGETS_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                clusters = data.get("priority_clusters", []) + data.get("secondary_clusters", [])
                return clusters
        except Exception as e:
            logger.error(f"[Daemon] Failed to load campaign_targets.yaml: {e}")
            return []

    async def run_discovery_step(self):
        """Runs the next unharvested target cluster from campaign_targets.yaml."""
        clusters = self.load_targets()
        if not clusters:
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        # Find next target category to search
        selected_cluster = None
        selected_category = None

        for cluster in clusters:
            area = cluster.get("area", "Vatva GIDC")
            city = cluster.get("city", "Ahmedabad")
            for cat in cluster.get("categories", []):
                cat_name = cat.get("name")
                im_query = f"IndiaMART: {cat_name} in {area} {city}"
                
                # Check when this IndiaMART query was last executed
                cursor.execute(
                    "SELECT finished_at FROM search_history WHERE search_query = ? AND city = ? ORDER BY finished_at DESC LIMIT 1",
                    (im_query, city)
                )
                row = cursor.fetchone()
                if not row or not row[0]:
                    selected_cluster = cluster
                    selected_category = cat
                    break
                else:
                    # Check recrawl days
                    try:
                        last_date = datetime.strptime(row[0][:10], "%Y-%m-%d").date()
                        if (datetime.now(timezone.utc).date() - last_date).days >= 30:
                            selected_cluster = cluster
                            selected_category = cat
                            break
                    except Exception:
                        pass
            if selected_cluster:
                break

        conn.close()

        if not selected_cluster or not selected_category:
            logger.info("[Daemon] All target clusters have been crawled recently. Skipping discovery.")
            return

        area = selected_cluster.get("area")
        city = selected_cluster.get("city", "Ahmedabad")
        cat_name = selected_category.get("name")
        search_query = selected_category.get("search_query", f"{cat_name} in {area} {city}")

        logger.info(f"[Daemon] Starting discovery run for: '{search_query}' (Area: {area})")
        from leadforge.indiamart_playwright import scrape_indiamart_suppliers
        conn = get_db_connection()
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        added_count = 0

        try:
            im_suppliers = await scrape_indiamart_suppliers(city, cat_name, limit=25)
            for s in im_suppliers:
                cursor.execute("SELECT id FROM businesses WHERE LOWER(name) = LOWER(?)", (s["name"],))
                if cursor.fetchone():
                    continue

                biz_id = uuidv7()
                domain = s.get("website_domain")
                cursor.execute(
                    """
                    INSERT INTO businesses (
                        id, name, normalized_name, website_domain, display_phone, 
                        primary_platform, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'indiamart', ?, ?)
                    """,
                    (biz_id, s["name"], s["name"].lower().strip(), domain, s.get("phone"), now_iso, now_iso),
                )

                opp_id = uuidv7()
                cursor.execute(
                    """
                    INSERT INTO opportunities (
                        id, business_id, title, pipeline_stage, score, created_at, updated_at
                    ) VALUES (?, ?, ?, 'PROSPECTING', 85.0, ?, ?)
                    """,
                    (opp_id, biz_id, f"B2B Outreach - {cat_name}", now_iso, now_iso),
                )
                added_count += 1

            cursor.execute(
                """
                INSERT INTO search_history (id, city, category, search_query, results_count, status, created_at, finished_at)
                VALUES (?, ?, ?, ?, ?, 'COMPLETED', ?, ?)
                """,
                (uuidv7(), city, cat_name, f"IndiaMART: {cat_name} in {area} {city}", added_count, now_iso, now_iso),
            )
            conn.commit()
            logger.info(f"[Daemon] IndiaMART discovery complete: {added_count} industrial manufacturers added.")
        except Exception as e:
            logger.error(f"[Daemon] IndiaMART discovery failed for {cat_name}: {e}")
        finally:
            conn.close()

    async def run_enrichment_step(self):
        """Audits websites of newly discovered businesses to extract and verify direct contact emails."""
        from leadforge.outreach.discovery import WebsiteAuditor
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, website_domain FROM businesses
            WHERE website_domain IS NOT NULL 
              AND website_domain != ''
              AND (contact_email IS NULL OR contact_email = '')
              AND (
                  last_scraped_at IS NULL 
                  OR last_scraped_at = ''
                  OR last_scraped_at < datetime('now', '-7 days')
              )
              AND is_suppressed = 0
            ORDER BY (CASE WHEN LOWER(name) LIKE '%pvt%ltd%' OR LOWER(name) LIKE '%private%limited%' THEN 1 ELSE 0 END) DESC, id ASC
            LIMIT 20
            """
        )
        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return

        logger.info(f"[Daemon] Enriching emails for {len(rows)} businesses with websites...")
        enriched_count = 0
        for row in rows:
            biz_id = row["id"]
            name = row["name"]
            domain = row["website_domain"]
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                audit = await asyncio.to_thread(WebsiteAuditor.audit_website, domain)
                emails = audit.get("discovered_emails", [])
                if emails:
                    email = emails[0].strip().lower()
                    cursor.execute(
                        "UPDATE businesses SET contact_email = ?, last_scraped_at = ?, updated_at = ? WHERE id = ?",
                        (email, now_str, now_str, biz_id),
                    )
                    append_event(
                        event_type="EMAIL_DISCOVERED",
                        entity_type="Business",
                        entity_id=biz_id,
                        payload={"discovered_email": email, "domain": domain},
                        conn=conn,
                    )
                    conn.commit()
                    enriched_count += 1
                    logger.info(f"[Daemon] Enriched email for '{name}': {email}")
                else:
                    cursor.execute(
                        "UPDATE businesses SET last_scraped_at = ?, updated_at = ? WHERE id = ?",
                        (now_str, now_str, biz_id),
                    )
                    conn.commit()
            except Exception as enrich_err:
                logger.debug(f"[Daemon] Enrichment skipped for {domain}: {enrich_err}")
                cursor.execute(
                    "UPDATE businesses SET last_scraped_at = ?, updated_at = ? WHERE id = ?",
                    (now_str, now_str, biz_id),
                )
                conn.commit()
        conn.close()
        if enriched_count > 0:
            logger.info(f"[Daemon] Successfully enriched {enriched_count} new emails.")

    async def run_email_generation_step(self):
        """Finds leads with contact emails that don't have drafts yet, generates and auto-approves."""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Find opportunities for businesses that have an email but no approved/sent draft
        cursor.execute(
            """
            SELECT o.id as opportunity_id, b.id as business_id, b.name,
                   b.website_domain, b.contact_email, b.display_phone, b.rating, b.review_count,
                   b.is_suppressed, bt.name as category, a.city, a.area
            FROM opportunities o
            JOIN businesses b ON o.business_id = b.id
            LEFT JOIN business_types bt ON b.business_type_id = bt.id
            LEFT JOIN addresses a ON b.id = a.business_id
            WHERE b.contact_email IS NOT NULL 
              AND b.contact_email != ''
              AND b.is_suppressed = 0
              AND NOT EXISTS (
                  SELECT 1 FROM email_drafts ed 
                  JOIN opportunities opp2 ON ed.opportunity_id = opp2.id
                  WHERE opp2.business_id = b.id 
                    AND ed.status IN ('APPROVED', 'SENT', 'PENDING_APPROVAL', 'QUEUED')
              )
            GROUP BY b.id
            ORDER BY (CASE WHEN LOWER(b.name) LIKE '%pvt%ltd%' OR LOWER(b.name) LIKE '%private%limited%' THEN 1 ELSE 0 END) DESC, o.score DESC
            LIMIT 10
            """
        )
        opps = cursor.fetchall()

        if not opps:
            conn.close()
            return

        logger.info(f"[Daemon] Found {len(opps)} opportunities ready for email draft generation.")
        seen_biz_ids = set()
        seen_emails = set()

        for opp in opps:
            opp_id = opp["opportunity_id"]
            biz_id = opp["business_id"]
            name = opp["name"]
            category = opp["category"] or "Manufacturing"
            area = opp["area"] or "Ahmedabad"
            city = opp["city"] or "Ahmedabad"
            email = opp["contact_email"].strip().lower()
            website = opp["website_domain"] or ""
            rating = opp["rating"]
            review_count = opp["review_count"]

            if biz_id in seen_biz_ids or email in seen_emails:
                continue
            seen_biz_ids.add(biz_id)
            seen_emails.add(email)

            # 1. Route to Orvion Campaign
            campaign = self.router.route_lead(
                category=category,
                has_website=bool(website),
            )
            if not campaign:
                continue

            # 2. Generate Observation Hook via Ollama
            hook = self.generator.generate_hook(
                business_name=name,
                category=category,
                city=city,
                area=area,
                has_website=bool(website),
                scraped_text=f"{category} in {area}",
                rating=rating,
                review_count=review_count,
            )

            # 3. Assemble Body
            copy_tpl = campaign.get("copy_template", {})
            subject_tpl = CampaignRouter.select_subject(copy_tpl, business_id=biz_id)
            body_tpl = CampaignRouter.select_body(copy_tpl, business_id=biz_id)

            vars_dict = SafeDict({
                "business_name": name,
                "city": city,
                "area": area,
                "category": category,
                "observation_hook": hook or f"I noticed {name} operates in {area}.",
            })
            subject = subject_tpl.format_map(vars_dict)
            body = body_tpl.format_map(vars_dict)

            # 4. Quality Gate
            quality = EmailQualityEngine.score_draft(body)
            quality_score = quality["quality_score"]
            quality_passed = quality["passed"]

            # Auto-approval: If score is 100, approve automatically!
            status = "APPROVED" if quality_score == 100 else "PENDING_APPROVAL"
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            draft_id = uuidv7()

            cursor.execute(
                """
                INSERT INTO email_drafts (
                    id, opportunity_id, campaign_name, recipient_email, subject, body, status,
                    quality_score, quality_passed, quality_issues, hook_source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ollama_autonomous', ?, ?)
                """,
                (draft_id, opp_id, campaign["name"], email, subject, body, status,
                 quality_score, 1 if quality_passed else 0, "", now_str, now_str)
            )
            append_event(
                event_type="EMAIL_DRAFT_AUTO_APPROVED" if status == "APPROVED" else "EMAIL_DRAFT_GENERATED",
                entity_type="EmailDraft",
                entity_id=draft_id,
                payload={"business_name": name, "recipient_email": email, "quality_score": quality_score},
                conn=conn,
            )
            conn.commit()
            logger.info(f"[Daemon] Generated draft for '{name}' -> Status: {status} (Quality: {quality_score})")

        conn.close()

    def run_delivery_step(self):
        """Sends approved drafts within daylight window with randomized delays."""
        if not is_daylight_sending_window():
            logger.debug("[Daemon] Outside daylight window (09:30 - 17:30 IST Mon-Fri). Skipping dispatch.")
            return

        conn = get_db_connection()
        allowance, reason = delivery_allowance(conn, self.settings)
        conn.close()

        if allowance <= 0:
            logger.info(f"[Daemon] Daily send allowance exhausted: {reason}")
            return

        logger.info(f"[Daemon] Daylight window active. Sending approved drafts (Allowance: {allowance})...")
        sent = self.deliverer.send_approved_drafts()
        if sent > 0:
            logger.info(f"[Daemon] Dispatched {sent} emails via Gmail SMTP.")

    def run_followup_step(self):
        """Processes due follow-up emails (Touch 2 on Day 3, Touch 3 on Day 7)."""
        if not is_daylight_sending_window():
            return
        processed = self.sequencer.process_due_followups(max_batch=10)
        if processed:
            logger.info(f"[Daemon] Processed {len(processed)} automated follow-up steps.")

    def run_imap_poll_step(self):
        """Polls IMAP inbox every 15 minutes for prospect replies."""
        now = time.time()
        if now - self._last_imap_poll < 900:  # 15 minutes
            return
        self._last_imap_poll = now
        logger.info("[Daemon] Polling IMAP inbox for replies and bounces...")
        try:
            result = self.inbox_monitor.poll_inbox()
            logger.info(f"[Daemon] IMAP Poll: Ingested {result.get('ingested', 0)} messages.")
        except Exception as e:
            logger.error(f"[Daemon] IMAP poll error: {e}")

    async def run_loop(self, once: bool = False):
        """Main autonomous loop."""
        logger.info("=== Orvion Autonomous Lead & Cold Email Daemon Started ===")
        logger.info("Operating 24/7 | Gmail SMTP | Telegram Alerts Enabled")

        while True:
            try:
                # 1. Poll IMAP replies frequently
                self.run_imap_poll_step()

                # 2. Nightly / Periodic Discovery (Run once every 12 hours)
                now = time.time()
                if now - self._last_discovery_run > 43200:  # 12 hours
                    self._last_discovery_run = now
                    await self.run_discovery_step()

                # 3. Deep Enrichment (Extract emails from websites)
                await self.run_enrichment_step()

                # 4. Generate and auto-approve email drafts
                await self.run_email_generation_step()

                # 4. Dispatch approved emails (Daylight window only)
                self.run_delivery_step()

                # 5. Send automated follow-ups (Daylight window only)
                self.run_followup_step()

            except Exception as e:
                logger.error(f"[Daemon] Unexpected error in main loop: {e}", exc_info=True)

            if once:
                logger.info("[Daemon] Single run complete (--once). Exiting.")
                break

            # Sleep 60 seconds before next check
            await asyncio.sleep(60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Orvion Autonomous Daemon")
    parser.add_argument("--once", action="store_true", help="Run one full pass and exit")
    args = parser.parse_args()

    engine = AutonomousOrvionEngine()
    asyncio.run(engine.run_loop(once=args.once))
