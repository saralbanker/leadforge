"""WhatsApp-Auto: Queue Manager & Semi-Automated Dispatcher.

Handles:
1. SQLite database initialization & migrations.
2. Direct ingestion from LeadForge database (`leadforge.db`).
3. CLI interactive dispatch loop.
4. Single-file HTML dashboard generation for 1-click browser dispatch.
"""

import argparse
import html
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from foundation.config import (
    DAILY_SEND_LIMIT,
    DB_PATH,
    DEFAULT_AREA,
    DEFAULT_CITY,
    DEFAULT_PRODUCTS,
    LEADFORGE_DB_PATH,
    SCHEMA_PATH,
)
from foundation.generator import WhatsAppHookGenerator
from foundation.phone_utils import format_display_phone, normalize_indian_phone
from foundation.templates import render_template_a, render_template_b, render_template_c
from foundation.url_builder import build_whatsapp_link


class WhatsAppQueueManager:
    """Manages prospect queue, templates, and dispatch status."""

    def __init__(self, db_path: Path = DB_PATH, hook_generator: Optional[WhatsAppHookGenerator] = None):
        self.db_path = db_path
        self.hook_generator = hook_generator or WhatsAppHookGenerator()
        self._init_db()

    def _render_message(self, contact: Dict[str, Any], template_name: str = "template_a") -> str:
        """Builds the exact queued message, retaining static copy on LM fallback."""
        hook, source = self.hook_generator.generate_hook_with_source(
            company_name=contact["company_name"],
            products=contact.get("products"),
            area=contact.get("area"),
        )
        # Each template's former opening is its deterministic fallback.  In
        # particular B and C have different evidence-bound wording than A.
        # Do not replace that proven fallback with a generic generator clause.
        injected_hook = hook if source == "llm" else None
        if template_name == "template_b":
            return render_template_b(contact["company_name"], contact.get("products"), contact.get("area"), hook=injected_hook)
        if template_name == "template_c":
            return render_template_c(contact["company_name"], contact.get("products"), contact.get("area"), hook=injected_hook)
        return render_template_a(contact["company_name"], contact.get("products"), contact.get("area"), hook=injected_hook)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes database schema if not present."""
        if not SCHEMA_PATH.exists():
            return
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn = self._get_connection()
        conn.executescript(schema_sql)
        conn.commit()
        conn.close()

    def import_from_leadforge(self, leadforge_db_path: Path = LEADFORGE_DB_PATH) -> int:
        """Imports verified Ahmedabad manufacturing leads with phones from leadforge.db."""
        if not leadforge_db_path.exists():
            print(f"[QueueManager] Error: LeadForge database not found at {leadforge_db_path}")
            return 0

        lf_conn = sqlite3.connect(leadforge_db_path)
        lf_conn.row_factory = sqlite3.Row
        lf_cur = lf_conn.cursor()

        lf_cur.execute(
            """
            SELECT b.name, b.display_phone, b.categories, b.is_suppressed,
                   a.area, a.city
            FROM businesses b
            LEFT JOIN addresses a ON b.id = a.business_id
            WHERE b.display_phone IS NOT NULL 
              AND b.display_phone != ''
              AND (b.is_suppressed IS NULL OR b.is_suppressed = 0)
            """
        )
        rows = lf_cur.fetchall()
        lf_conn.close()

        imported = 0
        conn = self._get_connection()
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for r in rows:
            raw_phone = r["display_phone"]
            clean_phone = normalize_indian_phone(raw_phone)
            if not clean_phone:
                continue

            # Resolve area
            area = r["area"] or DEFAULT_AREA
            city = r["city"] or DEFAULT_CITY

            # Clean product line
            categories = r["categories"] or DEFAULT_PRODUCTS
            products = categories.split(",")[0].strip().lower()

            try:
                cur.execute(
                    """
                    INSERT INTO wa_contacts (
                        id, company_name, area, city, products, raw_phone, normalized_phone, source, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'leadforge', 'PENDING', ?, ?)
                    ON CONFLICT(normalized_phone) DO NOTHING
                    """,
                    (str(uuid.uuid4()), r["name"], area, city, products, raw_phone, clean_phone, now_iso, now_iso),
                )
                if cur.rowcount > 0:
                    imported += 1
            except Exception:
                pass

        conn.commit()
        conn.close()
        return imported

    def get_pending_queue(self, limit: int = DAILY_SEND_LIMIT) -> List[Dict[str, Any]]:
        """Retrieves uncontacted leads up to the daily safety limit."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, company_name, area, city, products, raw_phone, normalized_phone, status
            FROM wa_contacts
            WHERE status = 'PENDING'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def mark_status(
        self,
        contact_id: str,
        status: str,
        notes: Optional[str] = None,
        template_name: str = "template_a",
        message_text: Optional[str] = None,
    ) -> None:
        """Updates contact status and records dispatch log."""
        conn = self._get_connection()
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cur.execute(
            "UPDATE wa_contacts SET status = ?, notes = ?, updated_at = ? WHERE id = ?",
            (status, notes, now_iso, contact_id),
        )

        # If message_text is not provided, generate from contact details
        if not message_text:
            cur.execute(
                "SELECT company_name, products, area FROM wa_contacts WHERE id = ?",
                (contact_id,),
            )
            row = cur.fetchone()
            if row:
                message_text = self._render_message(dict(row), template_name)
            else:
                message_text = f"Dispatched {template_name}"

        cur.execute(
            """
            INSERT INTO wa_dispatch_logs (
                id, contact_id, template_name, message_text, dispatch_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), contact_id, template_name, message_text, status, now_iso),
        )
        conn.commit()
        conn.close()

    def generate_html_queue(self, output_path: Optional[Path] = None, limit: int = DAILY_SEND_LIMIT) -> Path:
        """Generates a clean, standalone HTML dispatch dashboard."""
        if output_path is None:
            output_path = self.db_path.parent / "dispatch_queue.html"

        leads = self.get_pending_queue(limit=limit)
        cards_html = []

        for idx, lead in enumerate(leads, 1):
            phone = lead["normalized_phone"]
            msg = self._render_message(lead)
            link_web = build_whatsapp_link(phone, msg, mode="web")
            link_app = build_whatsapp_link(phone, msg, mode="universal")

            company_name_esc = html.escape(lead["company_name"])
            area_esc = html.escape(lead["area"])
            city_esc = html.escape(lead["city"])
            msg_esc = html.escape(msg).replace("\n", "<br>")

            cards_html.append(f"""
            <div class="card" id="card-{lead['id']}">
                <div class="card-header">
                    <span class="badge">#{idx} of {len(leads)}</span>
                    <h3>{company_name_esc}</h3>
                    <div class="meta">{area_esc}, {city_esc} &bull; {format_display_phone(phone)}</div>
                </div>
                <div class="card-body">
                    <div class="msg-box">{msg_esc}</div>
                    <div class="actions">
                        <a href="{link_web}" target="_blank" class="btn btn-primary" onclick="markSent('{lead['id']}')">
                            🟢 Open in WhatsApp Web
                        </a>
                        <a href="{link_app}" target="_blank" class="btn btn-secondary">
                            📲 Open in WhatsApp App
                        </a>
                        <button class="btn btn-outline" onclick="markSkip('{lead['id']}')">⏭️ Skip</button>
                    </div>
                </div>
            </div>
            """)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WhatsApp-Auto: Ahmedabad Dispatch Queue</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b141a; color: #e9edef; margin: 0; padding: 24px; }}
        .container {{ max-width: 760px; margin: 0 auto; }}
        header {{ margin-bottom: 24px; border-bottom: 1px solid #222d34; padding-bottom: 16px; }}
        h1 {{ margin: 0 0 8px 0; color: #25D366; font-size: 24px; }}
        p.subtitle {{ margin: 0; color: #8696a0; font-size: 14px; }}
        .card {{ background: #111b21; border: 1px solid #222d34; border-radius: 12px; margin-bottom: 20px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.2); }}
        .card-header {{ padding: 16px 20px; background: #202c33; border-bottom: 1px solid #222d34; }}
        .badge {{ background: #25D366; color: #111b21; font-weight: bold; font-size: 12px; padding: 2px 8px; border-radius: 6px; }}
        .card-header h3 {{ margin: 8px 0 4px 0; font-size: 18px; color: #fff; }}
        .meta {{ font-size: 13px; color: #8696a0; }}
        .card-body {{ padding: 20px; }}
        .msg-box {{ background: #0b141a; border-left: 4px solid #25D366; padding: 14px; border-radius: 6px; font-size: 14px; line-height: 1.5; color: #d1d7db; margin-bottom: 16px; white-space: pre-wrap; }}
        .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
        .btn {{ display: inline-flex; align-items: center; justify-content: center; padding: 10px 18px; font-size: 14px; font-weight: 600; border-radius: 8px; text-decoration: none; cursor: pointer; border: none; }}
        .btn-primary {{ background: #25D366; color: #0b141a; }}
        .btn-primary:hover {{ background: #20bd5a; }}
        .btn-secondary {{ background: #222d34; color: #e9edef; }}
        .btn-outline {{ background: transparent; border: 1px solid #3b4a54; color: #8696a0; }}
        .sent {{ opacity: 0.4; pointer-events: none; border-left: 6px solid #25D366; }}
        .skipped {{ opacity: 0.3; pointer-events: none; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⚡ WhatsApp-Auto Dispatch Queue</h1>
            <p class="subtitle">Ahmedabad B2B Industrial Outreach &bull; 1-Click Zero-Ban Queue &bull; {len(leads)} Leads Ready Today</p>
        </header>
        <div id="queue-container">
            {''.join(cards_html) if cards_html else '<p style="color:#8696a0">No pending leads in queue. Import more from LeadForge database!</p>'}
        </div>
    </div>
    <script>
        function markSent(id) {{
            const card = document.getElementById('card-' + id);
            if (card) card.classList.add('sent');
        }}
        function markSkip(id) {{
            const card = document.getElementById('card-' + id);
            if (card) card.classList.add('skipped');
        }}
    </script>
</body>
</html>
"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path


def main():
    parser = argparse.ArgumentParser(description="WhatsApp-Auto: Solo Outreach Dispatcher")
    parser.add_argument("--import-leadforge", action="store_true", help="Import leads from leadforge.db")
    parser.add_argument("--generate-html", action="store_true", help="Generate single-file dispatch_queue.html")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive CLI dispatch loop")
    parser.add_argument("--limit", "--daily-limit", type=int, default=DAILY_SEND_LIMIT, help="Queue limit (default: 25)")
    args = parser.parse_args()

    mgr = WhatsAppQueueManager()

    if args.import_leadforge:
        count = mgr.import_from_leadforge()
        print(f"[WhatsApp-Auto] Ingested {count} qualified Ahmedabad manufacturing leads with verified mobile numbers.")
        if not args.generate_html and not args.interactive:
            return

    if args.generate_html:
        out = mgr.generate_html_queue(limit=args.limit)
        print(f"[WhatsApp-Auto] Generated 1-click dispatch dashboard: {out}")
        return

    # Default: CLI Interactive Mode
    leads = mgr.get_pending_queue(limit=args.limit)
    print(f"\n=== WhatsApp-Auto Solo Dispatch Queue ({len(leads)} Leads) ===")
    if not leads:
        print("No pending leads found. Run with `--import-leadforge` to populate queue from LeadForge DB.")
        return

    for idx, lead in enumerate(leads, 1):
        phone = lead["normalized_phone"]
        msg = mgr._render_message(lead)
        link = build_whatsapp_link(phone, msg, mode="web")

        print(f"\n[{idx}/{len(leads)}] {lead['company_name']} ({lead['area']})")
        print(f"Phone: {format_display_phone(phone)}")
        print("--------------------------------------------------")
        print(msg)
        print("--------------------------------------------------")
        print(f"Link: {link}")
        
        try:
            choice = input("\nAction: [Enter/s] Sent | [k] Skip | [n] Not on WA | [q] Quit: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting queue. Progress is saved in database.")
            break

        if choice in ("", "s"):
            mgr.mark_status(lead["id"], "SENT", message_text=msg)
            print("✓ Marked SENT")
        elif choice == "k":
            mgr.mark_status(lead["id"], "SKIPPED", message_text=msg)
            print("⊘ Marked SKIPPED")
        elif choice == "n":
            mgr.mark_status(lead["id"], "NOT_ON_WA", message_text=msg)
            print("✗ Marked NOT_ON_WA")
        elif choice == "q":
            print("Exiting queue. Progress is saved in database.")
            break


if __name__ == "__main__":
    main()
