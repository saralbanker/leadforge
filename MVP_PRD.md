# LeadForge MVP PRD v1.0

## Project Name
**LeadForge**

## Subtitle
AI-Powered Local Business Lead Intelligence System

## Vision
LeadForge is an internal desktop application that automatically discovers businesses from Google Maps, analyzes their digital presence, identifies possible software opportunities, prevents duplicate records, and generates high-quality lead lists for the sales team.

* The MVP is designed for one company, one city (Ahmedabad), and one sales team.
* This is not a CRM.
* This is not a SaaS.
* This is a Lead Intelligence Engine.

## Primary Goal
Allow a salesperson to answer one question:
**"Who should I call next?"**
in less than 30 seconds.

## MVP Features
The system must:
* Search Google Maps by category.
* Collect businesses.
* Extract public information.
* Detect duplicate businesses.
* Analyze website presence.
* Recommend software opportunities.
* Store history locally.
* Export Excel.

## Out of Scope (Not included in Version 1)
* User login
* Authentication
* Cloud sync
* Multi-user
* CRM
* Meetings
* Tasks
* Proposals
* Analytics
* WhatsApp integration
* Email automation
* AI chatbot
* Invoicing
* Accounting

---

## System Architecture

```
                 Google Maps
                       │
                       ▼
                Search Engine
                       │
                       ▼
             Business Collector
                       │
                       ▼
            Data Normalization
                       │
                       ▼
           Duplicate Detection
                       │
                       ▼
           SQLite Database
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
 Opportunity Engine  Exporter    Dashboard
        │
        ▼
     Excel Output
```

---

## Backend Pipeline
Every search follows this workflow.

```
User selects:
City, Category, Limit
       │
       ▼
  Start Search
       │
       ▼
Google Maps Search
       │
       ▼
 Business URLs
       │
       ▼
 Business Details
       │
       ▼
 Normalize Data
       │
       ▼
Check Duplicate ─── Already Exists?
                       │
             ┌─────────┴─────────┐
             ▼ YES               ▼ NO
      Update last_seen      Insert Business
  Increase discovery_count       │
         Skip Export        Generate Opportunities
                                 │
                            Export Excel
                                 │
                            Display Results
```

---

## Final Database Structure
Exactly 6 Tables:

### 1. `businesses` ⭐ (Central Table)
Stores every discovered business. One row = One real-world business.
* **Fields:**
  * `id` (UUIDv7)
  * `google_place_id`
  * `business_name`
  * `category`
  * `phone`
  * `website`
  * `has_website`
  * `address`
  * `area`
  * `city`
  * `rating`
  * `review_count`
  * `digital_maturity`
  * `status`
  * `first_seen`
  * `last_seen`
  * `discovery_count`
  * `created_at`
  * `updated_at`
* **Rules:**
  * Never delete.
  * Never duplicate.
  * Update existing records.
  * One business = one row.

### 2. `services`
Master list of everything you sell. Defines available software/services.
* **Fields:**
  * `id`
  * `name`
  * `description`
* **Example Data:**
  * Website
  * Website Redesign
  * ERP
  * CRM
  * Inventory
  * Billing
  * POS
  * Appointment
  * AI Automation
  * Custom Software

### 3. `opportunities`
One business can have multiple opportunities. Stores recommendations.
* **Fields:**
  * `id`
  * `business_id`
  * `service_id`
  * `score`
  * `confidence`
  * `reason`
  * `created_at`
* **Example:**
  * ABC Industries → ERP (Score 95, reason: "Manufacturer")
  * ABC Industries → Website (Score 80, reason: "No website")
  * ABC Industries → Inventory (Score 90, reason: "Industrial Business")

### 4. `searches`
Stores scraper execution history. Audits scraper runs.
* **Fields:**
  * `id`
  * `keyword`
  * `city`
  * `limit_requested`
  * `businesses_found`
  * `new_businesses`
  * `duplicates`
  * `started_at`
  * `finished_at`

### 5. `discovery_history`
Tracks every rediscovery. Know when a business was found again.
* **Fields:**
  * `id`
  * `business_id`
  * `search_id`
  * `source`
  * `discovered_at`

### 6. `settings`
Application configuration.
* **Fields:**
  * `key`
  * `value`
* **Examples:**
  * High Priority Threshold
  * Duplicate Confidence
  * Google Delay
  * Export Folder
  * Default City
  * Search Delay

### Relationships

```
                    searches
                        │
                        │
                  discovery_history
                        │
                        │
                        ▼
                  businesses
                        │
        ┌───────────────┴───────────────┐
        │                               │
        ▼                               ▼
 opportunities                     services
```

---

## Duplicate Detection

### Priority Order:
1. Google Place ID
2. Phone Number
3. Website Domain
4. Business Name + Area
5. Business Name + Address

### Algorithm:
```
Business Found
     │
     ▼
Google Place ID Exists?
     │
     ├─► YES ──> Already Exists?
     │                ├─► YES ──> Update Existing Record ──> Skip Export
     │                └─► NO ───> Insert New Business
     │
     └─► NO ───> Process other duplicates
```

---

## Opportunity Engine
Do not use AI initially; use rule-based mappings.

| Category | Suggested Services |
|---|---|
| Manufacturer | ERP, Inventory, Website |
| Restaurant | POS, Website |
| Clinic | Appointment, Website |
| School | School ERP |
| Warehouse | Inventory |
| Retail | Billing, POS |
| Logistics | Fleet Management |
| Hotel | Booking System |
| Gym | Membership System |

* **Each recommendation receives:** Score, Confidence, and Reason.

---

## Digital Maturity
Score every business from 0–100. Higher score = more digitally mature.
* **Example factors:**
  * Website exists
  * HTTPS
  * Business email
  * Google reviews
  * Social links
  * Website completeness

---

## Export
Generate an Excel file with the following columns:
* Business Name
* Phone
* Website
* Category
* Area
* Rating
* Suggested Services
* Priority
* Notes

* **Export filter:** Only export new businesses or those explicitly selected for re-export.

---

## Project Structure
```
leadforge/
├── database.py          # SQLite connection
├── models.py            # Database models
├── scraper.py           # Google Maps scraping
├── normalizer.py        # Clean phone, website, names
├── deduplicator.py      # Duplicate detection logic
├── opportunity.py       # Rule engine
├── exporter.py          # Excel export
├── settings.py          # Configuration
└── main.py              # CLI entry point

leadforge.db             # SQLite local database file
```

---

## Backend Communication Flow
```
User ──> main.py ──> scraper.py ──> normalizer.py ──> deduplicator.py ──> database.py ──> businesses ──> opportunity.py ──> opportunities ──> exporter.py ──> Excel
```

* **Single Responsibility Rules:**
  * `scraper.py` only collects raw business data.
  * `normalizer.py` cleans and standardizes it.
  * `deduplicator.py` decides whether to insert or update.
  * `database.py` is the only module allowed to execute SQL.
  * `opportunity.py` generates service recommendations.
  * `exporter.py` reads from the database and creates Excel files.

---

## Success Criteria
The MVP is complete when it can:
1. Search an Ahmedabad business category.
2. Collect 100–500 businesses.
3. Prevent duplicate records across runs.
4. Detect website presence.
5. Recommend likely software/services using rule-based logic.
6. Store all results in SQLite.
7. Export a clean Excel file ready for the sales team.
8. Complete a typical run in a few minutes without manual data cleanup.
