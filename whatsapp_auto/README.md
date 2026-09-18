# WhatsApp-Auto

> **Solo-Operator WhatsApp Outreach Engine for Ahmedabad B2B Industrial Manufacturers**  
> *Zero-Ban &bull; 1-Click Semi-Automated Dispatch &bull; WhatsApp-to-Tally Hook &bull; 100% Free*

---

## What Is This?
`whatsapp-auto` is a standalone, lightweight prospecting engine built to reach manufacturing owners, managing directors, and plant heads across Ahmedabad's industrial corridors (Vatva GIDC, Odhav, Kathwada, Changodar, Sanand, Naroda).

Instead of brittle headless browser scrapers that trigger Meta phone number bans, `whatsapp-auto` uses a **1-Click Dispatch Queue**:
- Ingests verified mobile numbers directly from `leadforge.db` (or CSV).
- Formats direct, professional, conversational messages (Template A: WhatsApp-to-Tally order entry).
- Generates pre-filled WhatsApp Web / Desktop deep links.
- Enables the operator to review and dispatch 20–25 personalized messages in under 10 minutes.

---

## Directory Structure
```text
whatsapp-auto/
├── docs/
│   ├── SYSTEM_ARCHITECTURE.md          # Full design philosophy, ban threat model & architecture
│   ├── TEMPLATE_AND_COPYWRITING_GUIDE.md # Proven Ahmedabad industrial WhatsApp copy & rules
│   ├── OPERATOR_RUNBOOK.md             # Step-by-step daily routine & reply objection handling
│   └── TECHNICAL_SPECIFICATION.md      # Data contracts, schema & module blueprint for AI models
├── foundation/
│   ├── schema.sql                      # Lightweight SQLite schema (contacts, dispatches, status)
│   ├── config.py                      # Core settings (daily limits, paths, operator profile)
│   ├── phone_utils.py                  # Strict Indian mobile normalizer (+91 10-digit series 6-9)
│   ├── templates.py                    # Professional Template A, B, and C generators
│   ├── url_builder.py                  # RFC-compliant WhatsApp deep-link constructor
│   └── queue_manager.py                # Lead ingestion, CLI interactive loop & HTML dashboard generator
├── dispatch_queue.html                 # 1-Click interactive browser dashboard
├── whatsapp_outreach.db                # Dedicated local SQLite database
└── README.md                           # Quick-start guide (this file)
```

---

## Quick Start (Daily Routine)

### 1. Ingest Leads from LeadForge
```bash
cd /mnt/data/rj/email_auto/whatsapp-auto
python3 -m foundation.queue_manager --import-leadforge
```

### 2. Generate Today's 1-Click Dashboard
```bash
python3 -m foundation.queue_manager --generate-html --limit 25
```
Open `dispatch_queue.html` in your browser. Click **🟢 Open in WhatsApp Web** on each card, review, and hit **Enter** to send.

### 3. Or Run via Terminal CLI
```bash
python3 -m foundation.queue_manager --limit 25
```
Step through contacts interactively and log sends directly to SQLite.
