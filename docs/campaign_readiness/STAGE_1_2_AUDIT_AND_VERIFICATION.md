# LeadForge Email Campaign & Outreach Hardening: Stage 1 & Stage 2 Audit & Verification Report

**Date:** 2026-09-20  
**Status:** All Stage 1 & Stage 2 Objectives Completed & Verified  
**Suite Passing Line:** `======================= 719 passed, 1 warning in 56.45s ========================`

---

## 1. Executive Summary & Repo State

When resuming from the interrupted work session (Codex):
- **Repository State:** Git status showed uncommitted edits across configuration, orchestrators, deliverer, server, and test files. Scaffolding for `outreach/dry_run.py` was present, and settings had been partially synced.
- **Pytest State:** The log `/tmp/leadforge-full-pytest.log` was 0 bytes due to the prior session being interrupted by usage limits.
- **Database State:** The live `leadforge.db` contained 330 businesses, 53 email-viable businesses (43 matching the portal campaign), and 40 approved email drafts. `outreach.daily_send_limit` had been set to 10 in SQLite.

---

## 2. Stage 1 Objective 1: SMTP Discrepancy Resolution

### Problem
Previously, `.env` defined `smtp.gmail.com` (`orvionstudio.co@gmail.com`), whereas the SQLite `settings` table had leftover test values (`smtp.dbserver.com`, `db@testserver.com`). Although `get_smtp_config()` prioritizes environment variables, the UI reads the settings table, causing silent disagreement between what was shown to operators and what was dispatched over the wire.

### Resolution
1. **Source Surface in Config:** `get_smtp_config()` now tags the resolved configuration dictionary with `"source": "environment"` if `SMTP_HOST` is populated in the process environment, or `"source": "database"` otherwise.
2. **UI / API Transparency:** `GET /api/settings` in `leadforge/server.py` now includes `"source"` and `"authoritative"` metadata on all `smtp.*` keys, so administrative dashboards explicitly reflect whether the runtime values are driven by `.env` or the database.
3. **Database Reconciliation:** Live rows in `leadforge.db` for `smtp.host`, `smtp.port`, `smtp.username`, `smtp.from_email`, `smtp.from_name`, `smtp.reply_to`, and `smtp.use_tls` were aligned with `.env`.
4. **Automated Verification:** `tests/test_smtp_configuration_resolution.py` proves:
   - Environment variables remain authoritative over stale database rows.
   - `get_smtp_config()` correctly identifies `"source": "environment"` vs `"source": "database"`.
   - `/api/settings` surfaces `"source": "environment"` when `SMTP_HOST` is active.

---

## 3. Stage 1 Objective 2: Justified Daily Send Limit

### Decision: `outreach.daily_send_limit = 10`
The limit was deliberately tuned to **10**, rather than defaulting to 20 or leaving it stuck at 2:

1. **Cohort Size Sizing:**
   - The verified database yields ~48-53 total businesses with reachable email addresses, with exactly ~43 routing to the Manufacturing B2B Portal campaign.
   - A batch of ~40 approved drafts dispatched at 10 emails/day establishes a 4-day controlled rollout.
2. **Warm-Up Ramp Schedule:**
   - `leadforge/outreach/ramp.py` defines `DEFAULT_RAMP_SCHEDULE = "1:10,8:20,15:30,22:40"`.
   - Day 1 allows a ceiling of 10. Aligning `daily_send_limit` to 10 ensures the system operates strictly within its planned ramp bounds.
3. **Sender Reputation Protection:**
   - The sender `orvionstudio.co@gmail.com` carries 2 historical hard bounces from earlier scraper fabrications and has 0 inbound replies recorded.
   - A conservative cap of 10/day prevents Gmail spam heuristics from flagging sudden volume spikes, while allowing daily inspection of bounces and deliverability metrics.

---

## 4. Stage 1 Objective 3: Re-Verification of Safety Rails

| Rail | Target State | Measured Result | Implementation & Evidence |
|---|---|---|---|
| **Quality score persisted** | Tracked per draft | **PASS** | `email_drafts.quality_score` present and written upon draft generation. Guarded by `tests/test_draft_quality_gate.py`. |
| **Quality enforced at bulk approval** | Block `< min_score` (80) | **PASS** | `bulk_approve_drafts` in `server.py` rejects unrated drafts or drafts below `outreach.min_quality_score`. |
| **Repetition detection** | Similarity limits enforced | **PASS** | `EmailQualityEngine.find_similar()` checks body similarity (0.70) against batch cohort and hook similarity (0.62). |
| **Fallback-hook detection** | Refuse degraded fallbacks | **PASS** | `bulk_approve_drafts` blocks any draft whose `hook_source` starts with `"fallback:"`. |
| **MX / Domain verification** | Reject non-resolving domains | **PASS** | `EmailCandidateAggregator._check_domain_has_mx()` uses keyword arguments `family=socket.AF_INET, type=socket.SOCK_STREAM` in asyncio fallback. Unresolvable domains return `False`. Verified by `tests/test_enrichment_no_fabrication.py`. |
| **Opt-out suppression (draft generation)** | Halt generation on opt-out | **PASS** | `server.py` verifies `businesses.is_suppressed == 0` AND queries `unsubscribe_suppressions` for `recipient_email`, returning HTTP 422 before Ollama hook generation. Tested in `tests/test_outreach_hardening.py`. |
| **Opt-out suppression (SMTP dispatch)** | Cancel draft at send time | **PASS** | `deliverer.py` checks business suppression and `unsubscribe_suppressions` before opening an SMTP socket, marking suppressed drafts `CANCELLED`. Tested in `tests/test_outreach_hardening.py`. |
| **Deduplication** | Prevent re-contact | **PASS** | `is_duplicate_outreach()` enforces dedup at draft generation; `deliverer.py` enforces dedup against any `SENT` draft per recipient before sending. |
| **Daily send cap** | Enforced at SMTP point | **PASS** | `deliverer.py` computes `delivery_allowance(conn, settings)` and checks `sent_today >= daily_limit` before batch and per item. Tested in `tests/test_outreach_hardening.py`. |
| **Scheduler** | Manual triggers only | **PASS** | Dispatch remains strictly behind manual triggers (`/api/outreach/drafts/bulk-approve`, `/api/outreach/deliver`); no automated background delivery cron exists. |

---

## 5. Stage 1 Objective 4: Standalone Pre-Send Dry Run Tool

### Tool Implementation
Implemented in `leadforge/outreach/dry_run.py` and wrapped in executable CLI `scripts/outreach_dry_run.py`.
- Non-destructive (0 database writes, 0 SMTP connections).
- Performs live MX lookups, suppression checks, deduplication against `SENT` records, and evaluates remaining daily send allowance.
- Supports filtering by specific draft IDs via `--draft-id`.

### Live Production Execution Output
Ran on 2026-09-20 against live `leadforge.db`:
```text
Outreach pre-send dry run (no email sent)
Generated: 2026-09-20T10:39:50Z
Resolved SMTP from-address: orvionstudio.co@gmail.com
Approved drafts inspected: 40
MX: 39 pass, 1 fail
Suppressed: 0
Deduplicated (already sent): 0
Eligible to dispatch: 39
Daily limit: 10; remaining allowance: 10
Effective send count: 10
Allowance detail: 10 left today (sent 0/10, bound by configured limit; bounce 0% of last 0)
```

---

## 6. Stage 2 Objective 5: Disable Ineffective Directory Scrapers

### Problem
Scrapers for IndiaMart, Justdial, and TradeIndia returned 0 results for both phone and email across 365 businesses tested, while imposing an 8-second timeout per lead.

### Resolution
1. **Setting Opt-In Flag:** Added setting `enrichment.directory_providers_enabled` in SQLite, initialized to `'false'` (migration 029).
2. **Email Pipeline Exclusions:** `EmailEnrichmentOrchestrator` automatically filters out `indiamart`, `justdial`, and `tradeindia` providers when the flag is `'false'`.
3. **Phone Pipeline Exclusions:**
   - `SearchOrchestrator` (in `control_plane.py`) removes directory providers from `active_platforms` (falling back to `google_maps`).
   - `PhoneEnrichmentOrchestrator.enrich_phone()` excludes directory providers by default when `enabled_platforms` is `None` or omitted.
   - `server.py` passes `phone_platforms = ["website"]` when directory providers are disabled.
4. **Resilience Testing:** Verified via `tests/test_enrichment_phase2_3.py` that the pipeline executes cleanly without errors and returns empty result tuples as designed.

---

## 7. Full Test Suite Results

```text
======================= 719 passed, 1 warning in 56.45s ========================
```
A complete execution was run across all 719 tests and logged to `/tmp/leadforge-full-pytest.log`.

---

## 8. Explicitly Deferred Items

As specified in the scope, the following were intentionally deferred:
1. **B2B Dealer & Order Portal Routing Premise:** `website_audits` contains only 2 populated rows across 330 businesses; no verified order-flow or contact-form audit dataset exists. Premise assertions remain unmodified pending dedicated enrichment.
2. **12x12 Subject Slot Expansion:** Previously completed (144 permutations; collision rate reduced from 88.4% to 16.3%); verified via regression test `test_portal_subject_composition_reduces_collisions_in_48_lead_batch`.
3. **Automated Scheduler for Approve & Deliver:** Intentionally omitted; manual approval and delivery triggers remain appropriate for this phase.
4. **LLM System Prompt / Hook Generation Content:** Prompt copy and copy quality tuning were outside this safety and deliverability scope.
5. **WhatsApp Automation Module (`whatsapp_auto/`):** Kept untouched as a distinct module.
