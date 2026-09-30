# Production Pipeline Activation & End-to-End Verification Report

**Document:** `docs/campaign_readiness/PRODUCTION_PIPELINE_ACTIVATION_AND_VERIFICATION_REPORT.md`  
**Date:** 2026-09-20  
**Target System:** LeadForge Autonomous Cold Email System (`leadforge/daemon.py`, `leadforge/server.py`, `leadforge/outreach/`, `campaign_routing.yaml`)  
**Target Database:** `leadforge/leadforge.db` (SQLite)  
**Associated Prior Reports:**
1. [`SUBJECT_LENGTH_BUDGET_AND_COMPACTION_REPORT.md`](file:///mnt/data/rj/email_auto/docs/campaign_readiness/SUBJECT_LENGTH_BUDGET_AND_COMPACTION_REPORT.md)
2. [`EMAIL_BODY_REVIEW_AND_REWRITE_REPORT.md`](file:///mnt/data/rj/email_auto/docs/campaign_readiness/EMAIL_BODY_REVIEW_AND_REWRITE_REPORT.md)
3. [`EMAIL_BRIDGE_GROUNDING_REPORT.md`](file:///mnt/data/rj/email_auto/docs/campaign_readiness/EMAIL_BRIDGE_GROUNDING_REPORT.md)
4. [`EMAIL_AND_CAMPAIGN_STATUS.md`](file:///mnt/data/rj/email_auto/leadforge/EMAIL_AND_CAMPAIGN_STATUS.md)

---

## 1. Executive Summary

This audit and activation task was executed to verify that the LeadForge production environment is actively running the finalized, four-stage verified cold email pipeline end-to-end without stale code, bypassed templates, or ungrounded drafts, and to establish dry-run readiness for initial batch dispatch.

### 1.1 Core Findings
1. **Live Approved Drafts State:** The 39 deduplicated drafts in `leadforge.db` were confirmed to be **100% current and identical** to the final target state verified in `EMAIL_BRIDGE_GROUNDING_REPORT.md`. An automated string-by-string comparison showed **0 mismatches** across all 39 bodies, subjects, hooks, and grounded bridges.
2. **The Stale Daemon & 40th Draft Incident:** A background daemon process (`PID 3521822`), running since September 17 under `systemd-inhibit`, executed at 22:04:32 IST using pre-fix in-memory code. It generated a stale 40th draft (`01a0bfab-58ef-7bf7-9fae-c8a77a5d27c5`) for `bhagwaticomb@gmail.com` with the old 61-word body, duplicate location mentions, and no bridge sentence. The stale daemon process was terminated (`pkill -f "leadforge.daemon"`), and the duplicate draft was marked `CANCELLED`, restoring the approved queue to exactly the 39 verified leads.
3. **Production Wiring Gaps Identified & Remediated:** Both `leadforge/server.py` (`generate_draft` API) and `leadforge/daemon.py` (`run_email_generation_step`) contained a wiring gap: they called `body = body_tpl.format_map(template_vars)` instead of `CampaignRouter.render_body(...)`. This bypassed dynamic bridge synthesis (`generate_contact_bridge()`), leaving the `{contact_bridge}` slot completely blank, and bypassed opening location deduplication. Furthermore, neither entry point executed `EmailQualityEngine.validate_body()` or `EmailQualityEngine.validate_subject()`. Both files were updated and wired to use `CampaignRouter.render_body()` and `EmailQualityEngine` validation gates.
4. **Wiring Test Coverage:** Added `tests/test_production_pipeline_wiring.py` (2 tests, 100% passing) verifying that draft generation through both `server.py` and `daemon.py` invokes `CampaignRouter.render_body()` and enforces quality gates.
5. **Dry-Run Confirmation:** The pre-send dry run tool (`scripts/outreach_dry_run.py`) was executed against the clean, 39-draft approved batch. It confirmed 38 DNS MX passes, 1 MX failure (`sales@shivammfg.co.in`, correctly catching the non-existent domain), 0 suppressions, 0 duplicates, 38 dispatch-eligible leads, and an effective send count of **10** (strictly matching the Day 1 warm-up limit).
6. **No Emails Dispatched:** In accordance with instructions, no SMTP connections were opened and no real emails were dispatched.

---

## 2. Investigation Findings

### 2.1 Content Verification of Approved Drafts in `leadforge.db`
A programmatic audit of all approved drafts in `leadforge/leadforge.db` was performed against the published target state in `docs/campaign_readiness/EMAIL_BRIDGE_GROUNDING_REPORT.md`.

- **Total Approved Drafts:** 39 unique recipient leads.
- **Content Comparison Results:**
  - **Subject Lines:** 100% match. Median length 41.0 characters, maximum 49 characters, 0 exceeding 50 characters. Real product terms per business.
  - **Email Bodies:** 100% match. Median word count 56 words, 100% in the 40–60 word band, 0 unverified operational diagnosis claims.
  - **Contact Bridges:** 100% match. 39/39 distinct bridge sentences (0 duplicate bridge collisions). 37 leads cite verified scraped specifications (Tier A); 2 leads cite regional industrial directory entries with 0 website/catalog fabrication (Tier B).
  - **Location Collisions:** 0 opening location duplications across all 39 drafts.
  - **Quality Scores:** 100% recorded with `quality_score >= 80` and `quality_passed = 1`.
  - **Mismatches Detected:** **0 across all 39 leads**.

### 2.2 Root Cause of the 40th Draft (`01a0bfab-58ef-7bf7-9fae-c8a77a5d27c5`)
During the inspection, a 40th draft was discovered with `status = 'APPROVED'`:
- **Draft ID:** `01a0bfab-58ef-7bf7-9fae-c8a77a5d27c5`
- **Recipient:** `bhagwaticomb@gmail.com` (Business: `Bhagwati Engineering`)
- **Created At:** `2026-09-20T16:34:32Z` (22:04:32 IST)
- **Subject:** `lead follow-up at Bhagwati Engineering`
- **Body:** 61 words, location duplication (`Ahmedabad` twice in opening sentences), old ungrounded middle (`"I help local manufacturing plants automate their incoming inquiry flow..."`), no contact bridge.

**Root Cause:**
1. A background daemon process (`PID 3521822`: `python3 -u -m leadforge.daemon`) had been running continuously under `systemd-inhibit` since September 17.
2. Because the Python process was never restarted following the September 19–20 code refactors, it held pre-fix modules in memory.
3. When the loop awoke, its pre-fix query did not filter against recipient email deduplication for businesses sharing a contact address (`Bhagwati engineering corporation` vs `Bhagwati Engineering`), generating a stale duplicate draft.

**Remediation:**
1. Process terminated using `pkill -f "leadforge.daemon"`.
2. Draft `01a0bfab-58ef-7bf7-9fae-c8a77a5d27c5` updated in SQLite:
   ```sql
   UPDATE email_drafts
   SET status = 'CANCELLED',
       error_message = 'Duplicate recipient email: bhagwaticomb@gmail.com already has approved draft 01a0b783-c165-7573-a2d2-4cb45940e144',
       updated_at = datetime('now')
   WHERE id = '01a0bfab-58ef-7bf7-9fae-c8a77a5d27c5';
   ```
3. Database queue restored to exactly the 39 deduplicated, verified leads.

### 2.3 Configuration & Environment Audit
A complete audit of `settings` in `leadforge.db` confirmed no feature toggles, cached legacy prompts, or dev/staging discrepancies exist:
- `llm.model_name`: `qwen2.5:3b` (confirmed authoritative local model).
- `llm.system_prompt`: Synchronized with `031_compact_subject_and_topic.sql` and `generator.py`'s `DEFAULT_SYSTEM_PROMPT` (constraining topic to 1–3 words).
- `outreach.daily_send_limit`: `10` (strictly preserved).
- `enrichment.directory_providers_enabled`: `false` (dead directory scrapers disabled).
- `smtp.host`: `smtp.gmail.com` / `orvionstudio.co@gmail.com` (aligned with `.env`).
- No `USE_LEGACY_TEMPLATES` or conditional template bypass flags exist.

---

## 3. Production Entry Point Wiring Gaps & Fixes

### 3.1 Gaps Identified
Prior to this task, draft generation in the live entry points (`server.py` and `daemon.py`) bypassed the four fixes:

| Entry Point | File & Location | Previous Code | Defect / Failure Mode |
|---|---|---|---|
| **API Server** | `leadforge/server.py:1259` | `body = body_tpl.format_map(template_vars)` | `{contact_bridge}` slot evaluated to empty string `""`. Deduplication of duplicate city mentions bypassed. Quality gates `validate_body()` and `validate_subject()` omitted. |
| **Daemon** | `leadforge/daemon.py:404` | `body = body_tpl.format_map(vars_dict)` | `{contact_bridge}` slot evaluated to empty string `""`. Deduplication of duplicate city mentions bypassed. Missing top-level `json` import. Quality gates `validate_body()` and `validate_subject()` omitted. |

### 3.2 Code Changes Applied

#### 1. `leadforge/server.py` (`generate_draft` endpoint)
```python
# Updated body rendering and validation
body = CampaignRouter.render_body(
    template=body_tpl,
    business_name=display_name,
    observation_hook=hook or "",
    city=city or "",
    area=area_val or "",
    category=category or "",
    business_name_full=business_name or "",
    specific_topic=specific_topic,
    topic_focus=topic_focus,
    scraped_text=audit["cleaned_text"] or "",
    business_id=business_id,
)

# Quality scoring and strict validation
quality = EmailQualityEngine.score_draft(body, previous_bodies=recent_bodies)
body_valid, body_issues = EmailQualityEngine.validate_body(
    body,
    city=city or "",
    has_website=bool(website_domain),
)
subj_valid, subj_issues = EmailQualityEngine.validate_subject(
    subject,
    business_name=display_name,
)
if not body_valid:
    quality["issues"].extend(body_issues)
    quality["passed"] = False
if not subj_valid:
    quality["issues"].extend(subj_issues)
    quality["passed"] = False
```

#### 2. `leadforge/daemon.py` (`run_email_generation_step`)
- Added top-level `import json`.
- Replaced `format_map` with `CampaignRouter.render_body()` passing `scraped_text`, `business_id`, and lead metadata.
- Integrated `EmailQualityEngine.validate_body()` and `EmailQualityEngine.validate_subject()`.
- Auto-approval now strictly requires: `quality_score == 100 and quality_passed and is_valid_email`.
- Serializes `quality_issues` as JSON rather than an empty string.

### 3.3 Test Verification
Created `leadforge/tests/test_production_pipeline_wiring.py` containing:
- `test_server_generate_draft_calls_render_body_and_includes_contact_bridge`: Proves API calls `CampaignRouter.render_body()`, synthesizes a non-empty grounded contact bridge, enforces word budget, and records quality issues.
- `test_daemon_run_email_generation_step_calls_render_body_and_validates`: Proves daemon calls `CampaignRouter.render_body()`, validates via `EmailQualityEngine`, and auto-approves compliant drafts.

Both tests pass cleanly: `2 passed, 1 warning in 0.77s`.

---

## 4. Standalone Pre-Send Dry Run Execution

The pre-send dry run tool (`scripts/outreach_dry_run.py`) was executed against the verified live database:

```text
Outreach pre-send dry run (no email sent)
Generated: 2026-09-20T17:01:42Z
Resolved SMTP from-address: orvionstudio.co@gmail.com
Approved drafts inspected: 39
MX: 38 pass, 1 fail
Suppressed: 0
Deduplicated (already sent): 0
Eligible to dispatch: 38
Daily limit: 10; remaining allowance: 10
Effective send count: 10
Allowance detail: 10 left today (sent 0/10, bound by configured limit; bounce 0% of last 0)
```

### 4.1 Safety Rail Verification Breakdown
- **Approved Drafts Inspected:** 39 (1:1 recipient mapping across all active approved leads).
- **Fresh DNS MX Check:** 38 pass, 1 fail.
  - The 1 failure is Draft `01a0b782-d4a4-7ab3-a909-990f7f68ab1b` (`sales@shivammfg.co.in`), an unresolvable fabricated domain correctly caught by DNS resolution.
- **Suppression Check:** 0 suppressed (no active opt-outs in `unsubscribe_suppressions` or `businesses.is_suppressed`).
- **Deduplication Check:** 0 duplicates (no recipient has previously received a `SENT` draft).
- **Eligible to Dispatch:** 38 leads.
- **Daily Send Limit Enforcement:** Sized at `10` emails/day, leaving `10` available today.
- **Effective Send Count:** Exactly **10** drafts will dispatch on the first manual run, with remaining leads queued for subsequent daily batches.

---

## 5. Full Test Suite Pass Line

The complete LeadForge test suite (unit tests, integration tests, SIL benchmarks, and outreach hardening tests) was executed:

```text
================== 867 passed, 1 warning in 74.58s (0:01:14) ===================
```

---

## 6. Operational Handoff: Next Steps for the Operator

1. **Review Output:** Confirm that the dry-run results above align with campaign expectations (10 emails scheduled for Day 1 dispatch out of 38 eligible).
2. **Execute Manual Dispatch:** When ready to send Batch 1, trigger the manual delivery endpoint or script:
   ```bash
   cd /mnt/data/rj/email_auto/leadforge
   # Run pre-send dry run once more immediately before sending:
   python scripts/outreach_dry_run.py

   # Trigger delivery of Day 1 batch (10 sends):
   curl -X POST http://localhost:8000/api/outreach/deliver
   ```
3. **Monitor Day 1 Ingestion:** Check delivery receipts and IMAP replies via `logs/run.log` or the UI dashboard before approving the next daily batch.
