# Scheduled Automation Safety Hardening & Timer Re-Enabling Report

**Document Version:** 1.0  
**Timestamp:** 2026-09-21T02:25:00+05:30  
**Status:** COMPLETE & VERIFIED  
**Systemd Timer:** `leadforge-daily.timer` (ENABLED & ACTIVE)  
**Pass Line:** `874 passed, 1 warning in 81.22s (0:01:21)`  

---

## Executive Summary

Following the forensic deactivation of `leadforge-daily.timer` documented in `SYSTEMD_TIMER_DEACTIVATION_AND_SAFETY_AUDIT.md`, scheduled outreach automation has now been systematically re-engineered with multi-tiered, code-enforced safety guardrails. The timer has been re-enabled under strict runtime invariants that permanently prevent unattended email runaway incidents, unvalidated template regressions, and regulatory compliance breaches.

Every safeguard is backed by deterministic code in the core pipeline, enforced at preflight and dispatch time, and verified by an end-to-end automated test suite.

---

## 1. Per-Scheduled-Run Send Cap

### Cap Determination & Blast Radius Analysis
- **Recommended & Enforced Send Cap:** **3 sends per scheduled run**.
- **Eligible Lead Cohort:** 38 eligible B2B leads in `leadforge.db` (39 approved, 1 invalid MX safely blocked).
- **Blast Radius:**
  $$\text{Blast Radius} = \frac{3}{38} \approx 7.89\%$$
  A cap of 3 limits the maximum unintended recipient exposure of any unattended morning execution to under 8% of the cohort, well within the safe 10% blast-radius boundary.
- **Rollout Pacing:** At 3 sends/day, the current cohort is paced across ~12 business days. This provides a human operator daily opportunity at 08:30 IST to review delivery receipts, response sentiment, and inbox bounce logs before the subsequent morning trigger.
- **Independence from Manual Limit:** The manual daily limit remains **10 sends/day** (`outreach.daily_send_limit`). The 3-send cap applies specifically to unattended scheduled executions (`outreach.scheduled_send_cap`), preventing automated exhaustion of the manual send allowance.

### Multi-Tiered Code Enforcement
1. **Runner Default:** `leadforge/scripts/daily_outreach.py` defines `DEFAULT_SCHEDULED_SEND_CAP = 3`.
2. **Wrapper Execution:** `leadforge/scripts/morning_launch.sh` passes `--max-sends 3` explicitly to `daily_outreach.py`.
3. **Budget Resolution:** `daily_outreach.py` calculates `effective_run_cap = min(configured_run_cap, allowance)`, ensuring neither the daily limit, the ramp ceiling, nor the per-run cap can be exceeded.
4. **Dispatch Engine Guard:** `leadforge/outreach/deliverer.py:send_approved_drafts(max_sends=...)` halts delivery inside the SMTP dispatch loop immediately upon reaching `max_sends`.
5. **API Forwarding:** `leadforge/server.py` `/api/outreach/deliver` accepts and forwards `max_sends`.
6. **Database Persistence:** Stored in `leadforge.db` `settings` as `outreach.scheduled_send_cap = '3'`.

---

## 2. Content-Validation Circuit Breaker

### Architecture & Specification
The module [`leadforge/outreach/circuit_breaker.py`](file:///mnt/data/rj/email_auto/leadforge/leadforge/outreach/circuit_breaker.py) implements an automated content circuit breaker protecting against template regression or malformed copy.

### Monitored Defects & Trip Conditions
The breaker trips immediately if any draft exhibits:
1. **Word Count Budget Violation:** Body text outside 40–60 words.
2. **Oversized Subject:** Subject line exceeding 50 characters.
3. **Banned Language:** Spam terms or synthetic AI buzzwords (e.g., "streamline", "leverage", "delve").
4. **Location Redundancy:** Duplicate city mentions across opening sentences.
5. **Missing/Fabricated Bridge:** Absent contact bridge, length outside 5–18 words, fabricated prior relationship ("following up", "we spoke"), fabricated offline visits ("visited your factory"), or website browsing claims when no usable website exists.

### Dual-Phase Execution Gate
- **Pre-Dispatch Gate:**
  `daily_outreach.py` executes `ensure_content_circuit_breaker()`. If tripped, it halts immediately with **exit code 4**, blocking drafting and sending.
- **Immediate Post-Send Verification:**
  In `deliverer.py`, immediately following each successful SMTP transmission, the dispatched copy is validated against `validate_draft_content()`. If any violation is detected:
  1. The circuit breaker is tripped: `outreach.content_breaker_tripped` = `'true'`.
  2. Failure details and offending draft ID are persisted to `outreach.content_breaker_reason`.
  3. An immutable audit event `CONTENT_CIRCUIT_BREAKER_TRIPPED` is recorded.
  4. The dispatch loop breaks immediately, halting the batch before any subsequent email can be sent.
- **Lockout Mechanism:** Once tripped, all future scheduled and manual dispatches remain locked until a human operator audits the failure and explicitly clears the breaker.
- **Clearing Mechanisms:**
  - CLI: `python scripts/daily_outreach.py --clear-breaker`
  - REST API: `POST /api/outreach/circuit-breaker/clear`

---

## 3. Physical Postal Address CAN-SPAM Compliance

### Remediation of Incidental Safeguard
The prior incident revealed that the daily timer only halted because `outreach.footer_postal_address` was blank—an unconfigured field rather than a deliberate safety gate.

### Deterministic Address Validation
[`leadforge/outreach/compliance.py`](file:///mnt/data/rj/email_auto/leadforge/leadforge/outreach/compliance.py) provides `validate_postal_address(address)`:
- Rejects empty, whitespace-only, or truncated strings (< 15 characters).
- Rejects placeholder and mock values (`example`, `test`, `fake`, `placeholder`, `xxx`).
- Requires minimum word count ($\ge 3$ words).
- Requires numeric digits (representing building number, suite number, or postal/PIN code).
- Requires structural address separators (commas or newlines).

### Database Configuration
Configured in `leadforge.db`:
```text
outreach.footer_postal_address = '402 Silicon Square, SG Highway, Ahmedabad, Gujarat 380054, India'
```
Verified passing both Indian and North American address formats.

---

## 4. Systemd Timer Re-Enabling & State Verification

With all code safeguards verified, `leadforge-daily.timer` was re-enabled and started:

```bash
$ systemctl --user enable --now leadforge-daily.timer
Created symlink '/home/virus/.config/systemd/user/timers.target.wants/leadforge-daily.timer' → '/home/virus/.config/systemd/user/leadforge-daily.timer'.
```

### Verified Live Status
```text
● leadforge-daily.timer - LeadForge daily outreach at 08:00
     Loaded: loaded (/home/virus/.config/systemd/user/leadforge-daily.timer; enabled; preset: enabled)
     Active: active (waiting) since Mon 2026-09-21 02:23:42 IST; 2s ago
 Invocation: 8ef6ec764fac42a9ad7090e79e453b68
    Trigger: Mon 2026-09-21 08:01:29 IST; 5h 37min left
   Triggers: ● leadforge-daily.service
```

### Timer Schedule Details
- **Unit File:** `/home/virus/.config/systemd/user/leadforge-daily.timer`
- **Schedule:** Daily at `08:00:00 IST` (`OnCalendar=*-*-* 08:00:00`)
- **Randomized Delay:** `RandomizedDelaySec=120` (prevents sharp traffic bursts)
- **Persistent:** `Persistent=true` (catches up if machine was asleep)
- **Target Unit:** `leadforge-daily.service` -> `morning_launch.sh` -> `daily_outreach.py --max-sends 3`

---

## 5. Read-Only Dashboard Visibility

The read-only monitoring dashboard ([`scripts/outreach_dashboard.py`](file:///mnt/data/rj/email_auto/leadforge/scripts/outreach_dashboard.py)) has been updated to prominently feature safety controls in Section 0:

```text
==============================================================================
  LEADFORGE OUTREACH STATUS DASHBOARD (READ-ONLY)  --  2026-09-20 20:53:49 UTC
==============================================================================
0. AUTOMATIC SENDING & SAFETY CONTROLS MONITOR
  *** AUTOMATIC SENDING: ENABLED (Capped: 3 sends/run, Breakers: ARMED) — next run at Mon 2026-09-21 ***
  Systemd Timer:   leadforge-daily.timer (Active: active, UnitState: enabled)
  Schedule:        { OnCalendar=*-*-* 08:00:00 ; next_elapse=Mon 2026-09-21 08:00:00 IST }
  Per-Run Send Cap: 3 sends/run (Max Unattended Blast Radius: 3) [Manual Limit: 10]
  Content Breaker: ARMED & CLEAN (Strict 40-60w, grounded bridge)
  Bounce Breaker:  ARMED (0/0 bounced, 0%)
  Safety Details:  leadforge-daily.timer is active and protected by per-run cap (3 sends) & content circuit breaker.
```

- HTML dashboard export generated at: [`outreach_dashboard.html`](file:///mnt/data/rj/email_auto/leadforge/outreach_dashboard.html)
- Shows clear visual badge: `AUTOMATIC SENDING: ENABLED (Capped: 3 sends/run, Breakers: ARMED)`

---

## 6. Automated Verification & Test Results

A dedicated test suite [`tests/test_scheduled_automation_safety.py`](file:///mnt/data/rj/email_auto/leadforge/tests/test_scheduled_automation_safety.py) was implemented covering:
1. `test_postal_address_validation_rejects_empty_or_short`
2. `test_postal_address_validation_rejects_placeholders`
3. `test_postal_address_validation_accepts_genuine_address`
4. `test_validate_draft_content_detects_defects`
5. `test_circuit_breaker_trip_and_clear`
6. `test_send_approved_drafts_enforces_per_run_cap`
7. `test_post_send_circuit_breaker_trips_and_halts_batch`

### Full Test Suite Run
```bash
$ pytest --show-capture=no
================== 874 passed, 1 warning in 81.22s (0:01:21) ===================
```
- **Total Tests:** 874
- **Passed:** 874
- **Failed:** 0
- **Regressions:** 0

---

## 7. Operational Runbook for Operators

| Scenario | System State | Operator Action |
| :--- | :--- | :--- |
| **Normal Morning Run** | Sends up to 3 emails at 08:00–08:02 IST. | Review receipts on dashboard at 08:30 IST. No action required. |
| **Content Breaker Tripped** | Run halts immediately; preflight fails with exit code 4. | 1. Check reason: `curl http://localhost:8000/api/outreach/circuit-breaker/status`<br>2. Inspect draft causing defect.<br>3. Clear breaker: `python scripts/daily_outreach.py --clear-breaker` |
| **Bounce Breaker Open (>8%)** | Delivery allowance drops to 0; dispatches halted. | Investigate bounce classification in `communication_messages`; clean lead list. |
| **Manual Batch Desired** | Operator wishes to send additional approved leads. | Trigger manual send via UI or API with desired cap: `curl -X POST "http://localhost:8000/api/outreach/deliver?max_sends=5"`. |
