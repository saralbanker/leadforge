# Email & Campaign Status

**As of 2026-08-21.** Every figure here was measured against the live database or
by running the code, not estimated. Where something is unverified it says so.

---

## 1. Where the contact data stands

| | count |
|---|---|
| Businesses in the database | 365 |
| …with a phone number | 365 |
| …with a website | 98 |
| …with an email address | **48** |
| …suppressed (opted out) | 0 |

All 48 email addresses come from one provider — `WebsiteProvider`, which crawls
the company's own site and its depth-1 contact/about pages. Every address has
been verified to resolve.

### Why only businesses with websites have emails

This is structural, not a bug. The only working email source crawls the
business's own website. A business with no website has nothing to crawl. The
three directory providers that could theoretically cover that gap — IndiaMart,
Justdial, TradeIndia — return **zero results** (see §5).

So the practical position is:

- **98 businesses with websites** → email is viable, ~49% yield.
- **267 businesses without websites** → email is not currently reachable.
  All 267 have phone numbers. Phone is the realistic channel for that segment.

### Yield from the full sweep

Running enrichment across all 98 businesses with websites:

```
98 businesses
51 addresses found        52% raw, 0 errors, 38 seconds
-3 platform addresses     removed (see below)
48 verified addresses     49% net
```

The 3 removals were businesses whose `website_domain` is a Linktree page. The
crawler harvested `press@linktr.ee` — Linktree's own press address — for all
three. Link aggregators, social profiles and site builders are now skipped
before fetching, and any candidate at such a domain is discarded.

---

## 2. The fabricated-email incident

**This is the most important thing in this document.** It has been fixed, but
the history matters for interpreting anything sent before 2026-08-20.

Both no-website scrapers invented an email address whenever discovery returned
nothing — in the `else` branch *and* the `except` branch, four sites in total:

```python
discovered_email = f"sales@{prefix}mfg.co.in"
provider_used    = "B2B Industrial Directory Index"   # a provider that does not exist
confidence_score = 0.82                                # a number with no basis
```

Because the directory providers now return nothing, this fired for **every**
no-website lead. None of the ten generated domains resolve.

What was done:

- All four fabrication sites now leave the address empty and skip the lead,
  with a counted, logged reason.
- Purged: 10 invented `contact_email` values, 3 pending drafts aimed at them
  (cancelled with a stated reason), 84 `email_discovery_attempts` rows that had
  recorded fabrications as `SUCCESS`.
- `SENT` rows were left intact — that is history, and two emails really did go
  to non-existent domains and hard-bounce.

**Consequence to be aware of:** the sender reputation of
`orvionstudio.co@gmail.com` already carries 2 hard bounces from this.

---

## 3. Campaigns

Five campaigns are defined in `campaign_routing.yaml`. Routing is deterministic —
first match wins, on website presence, SSL validity, load time and category.

| Campaign | Fires when | Offer |
|---|---|---|
| Manufacturing – Direct RFQ & Plant Capability | no website | B2B catalog & RFQ portal |
| Manufacturing – B2B Dealer & Order Portal | has website | Dealer order entry & dispatch |
| Campaign A (General No Website) | no website | Website design & speed |
| Campaign B (Booking) | has website | Booking / appointment portal |
| General Outreach (Digital Performance) | has website | Conversion rate optimisation |

Of the drafts generated so far, routing splits roughly 2:1 between
*Manufacturing – B2B Dealer & Order Portal* and *General Outreach*.

### Known problem: the routing premise is not verified

*Manufacturing – B2B Dealer & Order Portal* assumes the business has no way to
take orders online. It is routed purely on `has_website: true` plus category —
nothing checks whether the site already has a working contact form or order
flow. That produced copy asserting things that may not be true, including one
incoherent line: *"Americos industries Inc still takes orders over a website."*

The website audit already collects enough to check this. **Not yet fixed.**

### Known problem: one subject line per campaign

Each campaign has a single `subject` template, so every lead routed to the same
campaign gets an identical subject. In an early run, 7 of 10 drafts shared
`orders by WhatsApp?`. A batch of 48 emails with one of two subject lines is a
bulk-mail signature. **Not yet fixed.**

---

## 4. Copy generation

Local `llama3.1:8b` via Ollama. No external API, no per-email cost.

### The monoculture, and what actually caused it

The first full run produced ten drafts sharing one sentence skeleton —
`{name} still takes orders over {channel}, so mistakes must slip through` — and
seven shared a subject line. Every one scored 100/100, because the quality
engine had no concept of repetition.

Three hypotheses were tested in order. **The first two were wrong**, and are
recorded here so they are not re-investigated:

1. ~~In-context exemplars from the database~~ — they compound it, but are not
   the origin.
2. ~~The few-shot example in `llm.system_prompt`~~ — the prompt produces varied
   copy at higher temperature. Adding *more* examples made it slightly worse:
   the model simply copied the new examples verbatim instead.
3. **`llm.temperature` was set to 0.1.** At that setting sampling is nearly
   deterministic, so the model reproduces the nearest few-shot example almost
   word for word.

Measured sweep, 8 businesses per temperature, current prompt unchanged:

| temp | max similarity | median | blocked by gate | below 100 |
|------|---------------|--------|-----------------|-----------|
| 0.1 (was live) | 1.00 | **1.00** | 6/8 | 6 |
| 0.3 | 1.00 | 0.55 | 4/8 | 4 |
| 0.5 | 1.00 | 0.57 | 5/8 | 5 |
| 0.7 | 0.74 | 0.49 | 3/8 | 3 |
| **0.9 (now live)** | 0.60 | 0.42 | **0/8** | 1 |

A median similarity of 1.00 means literally the same sentence every time. The
`below 100` column tracks `blocked` at every step, so the quality loss was *all*
repetition — raising temperature cost no coherence up to 0.9.

`llm.system_prompt` is unchanged. It was never the problem.

### Speed

`keep_alive` was `0s`, which evicted the 4.9 GB model after every single email,
so each one paid a full reload and lost the cached prompt prefix.

```
keep_alive=0s    load 7.8s + prompt 7.6s + generate 7.9s = 24.2s
keep_alive=10m   load 0.2s + prompt 0.2s + generate 6.2s =  7.2s
```

Now `10m` in all three places it is read: `.env`, the code default, and the
`llm.keep_alive` setting — the last of which had been overriding the other two.

---

## 5. Directory scrapers — IndiaMart, Justdial, TradeIndia

**All three return nothing, for both phone and email.** Verified live and
confirmed against production data.

```
indiamart    HTTP 200   24,541 B  →  503 chars of visible text  →  0 results
justdial     HTTP 200  133,535 B  →  238 chars                  →  0 results
tradeindia   HTTP 200  193,274 B  →  1,876 chars                →  0 results

justdial, generic category search:  response body = 14 bytes  (hard block)
```

The pages are client-rendered shells — there is no data in the HTML to select,
so better selectors cannot fix this. The requests succeed with HTTP 200, which
is why nothing was ever logged as an error.

Across all 365 businesses, grouping by which source won:

| source | phone numbers contributed |
|---|---|
| (unrecorded, legacy import) | 340 |
| google_maps | 16 |
| official_website | 8 |
| justdial | 1 |
| **indiamart** | **0** |
| **tradeindia** | **0** |

Directory *lead discovery* (`search_directory.py`) is broken the same way.
TradeIndia returned two "businesses", one of which was `"Business Type"` — a
filter-panel label.

**Recommendation:** disable these behind a settings flag. They currently cost
an 8-second timeout per lead for calls that have never once succeeded.
`PhoneEnrichmentOrchestrator` already accepts `enabled_platforms`, so this is
configuration, not a rewrite. Reviving them needs a headless browser (Playwright
is already a dependency and already drives the working Google Maps collector) or
the official IndiaMart API.

---

## 6. Safety rails now in place

| Rail | State |
|---|---|
| Quality score persisted | ✅ `email_drafts.quality_score` (migration 023) |
| Quality enforced at bulk approval | ✅ below `outreach.min_quality_score` (80) is held back |
| Repetition detection | ✅ compares opening lines against the last 25 drafts |
| Fallback-hook detection | ✅ `hook_source` = `llm` \| `fallback`; fallbacks refused |
| MX / domain verification | ✅ on by default |
| Opt-out suppression | ✅ enforced before draft generation |
| Deduplication | ✅ per business and per email address |
| Daily send cap | ✅ `outreach.daily_send_limit` — **currently 2** |
| Scheduler | ❌ none — approve and deliver are manual HTTP triggers |

Two notes on the rails:

**MX verification had never worked.** `loop.getaddrinfo()` takes only
`(host, port)` positionally; the code passed `family`/`type` positionally too,
raising `TypeError` for every domain, which the outer handler swallowed into
"no MX". Enabling `verify_mx` had therefore rejected 100% of candidates — which
is presumably why it was left off. Fixed.

**Exemplars now require a reply, not an approval.** `get_approved_exemplars()`
selected on `status IN ('APPROVED','SENT')` — evidence that someone clicked a
button, not that the copy worked. The only two qualifying drafts had been sent
to fabricated addresses and bounced. It now requires an inbound message. No
replies are recorded, so it returns nothing and the model writes from the prompt
alone, which is correct with no evidence to learn from.

---

## 7. Configuration discrepancy to resolve

`.env` and the settings table disagree about SMTP:

| | `.env` (wins) | settings table |
|---|---|---|
| host | `smtp.gmail.com` | `smtp.dbserver.com` |
| from | `orvionstudio.co@gmail.com` | `db@testserver.com` |

`get_smtp_config()` prefers the environment when `SMTP_HOST` is set, so the
Gmail account is what would actually send. The settings rows look like leftover
test values. Worth reconciling so the UI does not display something different
from what sends.

Also note `outreach.daily_send_limit` is **2**, not the 20 the code defaults to.
A 48-draft batch would stop after two.

---

## 8. Open items, in priority order

1. **Verify the routing premise** before asserting it in copy. Do not tell a
   business with a working contact form that it takes orders by hand.
2. **Vary subject lines** within a campaign. One subject across a batch is a
   bulk-mail signature.
3. **Disable the three directory providers** behind a flag; they are pure cost.
4. **Reconcile the SMTP settings** rows with `.env`.
5. **Raise `outreach.daily_send_limit`** deliberately when ready to send.
6. **Decide the directories' fate** — Playwright, official API, or delete.
   Six provider files are currently dead weight.
7. **Add a scheduler** — only after 1 and 2, since unattended sending of
   near-identical copy is the risk, not the feature.

---

## 9. Test coverage

556 tests passing. The ones guarding this area:

- `tests/test_enrichment_no_fabrication.py` — fails if any scraper synthesizes
  a contact address, or if a platform/aggregator host is crawled.
- `tests/test_draft_quality_gate.py` — repetition detection, hook provenance,
  bulk-approval enforcement, business-name cleaning, exemplar gating.

---

## Appendix: what nothing here says

No email has been sent during any of this work. The drafts sit in
`PENDING_APPROVAL`. The two `SENT` rows predate it and went to fabricated
addresses.

There is no reply data at all — `communication_threads` and
`communication_messages` are both empty. So there is currently **no evidence
about what copy actually works**. Every quality judgement in this system is a
proxy: length, banned vocabulary, links, repetition. Until replies are recorded,
treat all of it as a hygiene filter, not as a measure of effectiveness.

---

## 10. Routing-premise and subject investigation (2026-09-20)

This section was measured against the available database files and the live
router, rather than inferred from the YAML.

### Audit evidence is not yet usable as a persistent routing gate

`website_audits` has only `lighthouse_score`, `page_speed_ms`, `issues_json`,
and `recommendation_notes`; there is no typed order-flow, contact-form, or
confidence column. The specified backup
`backups/leadforge_backup_20260721_164855.db` contains **196 businesses, 0
usable email addresses, and 0 website-audit rows** — it is not the described
365-business / 48-email snapshot. The newer `leadforge.db` contains **330
businesses, 53 usable email addresses, and 2 audit rows (for one presence)**.
Both persisted audit JSON documents lack `has_order_flow` and
`has_contact_form`.

`outreach.discovery.WebsiteAuditor` does compute those two booleans from the
homepage HTML (CMS/e-commerce markers and form markup), and the router already
refuses a confirmed positive signal. But no complete evidence set has been
persisted: its older cached JSON has neither field, and a boolean scan cannot
establish that a form or ordering flow is *working*. `get_approved_exemplars()`
uses the correct house standard — a real inbound human reply, excluding bounces
— so the same standard means unknown audit evidence cannot support an absence
claim.

**Decision: no routing change in this task.** Do not route this campaign on
`false` values until a separate enrichment task adds versioned evidence such as
`contact_flow_status` / `order_flow_status` (`present`, `absent`, `unknown`),
detector version, checked URL(s), timestamp, and confidence; follow the
contact/order links and verify a usable form/action before marking `present`.
Estimate: 2–3 engineering days plus a crawl of the website cohort. Until then,
skip the asserted-premise route (or keep only the existing unverified,
question-form copy); do not treat missing JSON keys as `false`.

### Subject collision result and fix

The real selector is `SHA256("subject:" + business_id) mod N`, not random or
LLM-driven. In the fresher DB, **43 of 53** usable-email businesses route to
the manufacturing portal campaign. Its previous five-template pool selected
all five templates but produced **38 template collisions (88.4%)**, with the
largest bucket containing **10** leads. The other ten usable-email records did
not route to a campaign; the old backup has no viable-email cohort to measure.

The portal campaign now uses two independently salted 12-item subject slots
(**144 combinations**), still deterministic for regeneration and without an
LLM call. On those same 43 business IDs it yields **36 distinct combinations,
7 collisions (16.3%)**, and a largest bucket of **4**. A regression test also
measures a stable 48-lead batch: five flat templates produce at least 40
collisions, while the 144-combination configuration produces at most 12 and
less than one third of the old collision count. This is sized to the only
currently viable, portal-heavy batch; there is no evidence that an LLM subject
hook is needed for it.

---

## 11. Delivery-readiness addendum (2026-09-20)

This addendum was measured against the current `leadforge.db`, the loaded
`.env`, and the current code. No SMTP send was performed.

### SMTP resolution decision

`get_smtp_config()` still treats a non-empty `SMTP_HOST` in the environment as
authoritative. The live settings rows were synchronized to that resolved
configuration, including Gmail host/port, sender identity, TLS, reply-to and
credentials (credentials were not printed). The resolved sender is
`orvionstudio.co@gmail.com`; the sender display name is `Saral Banker`.

This removes the UI/runtime disagreement without changing the precedence rule:
environment configuration still wins if someone subsequently changes it. The
new configuration-resolution test proves stale database rows cannot override
an explicitly configured environment sender.

### Deliberate first-batch limit

The live `outreach.daily_send_limit` was changed from **2** to **10**. The
code fallback remains 20, but it is not the operational decision. Ten is a
deliberate first real-batch cap: it is below the approximately 43 viable
portal-route leads and 48 viable addresses, aligns with the day-1 ramp ceiling
of 10, and limits exposure while this Gmail sender has two historical hard
bounces and zero replies. Review delivery, bounces, and replies before any
increase.

### Safety rails re-verified

| Rail | Result | Current evidence |
|---|---|---|
| Quality score persisted | PASS | `email_drafts.quality_score`; existing draft-quality migration/test coverage remains present. |
| Quality enforced at bulk approval | PASS | bulk approval reads `outreach.min_quality_score`; `tests/test_draft_quality_gate.py` remains the contract. |
| Repetition detection | PASS | opening-line comparison against recent drafts remains covered by `tests/test_draft_quality_gate.py`. |
| Fallback-hook detection | PASS | fallback hook provenance remains refused at bulk approval, covered by `tests/test_draft_quality_gate.py`. |
| MX / domain verification | PASS | enabled by default; `tests/test_enrichment_no_fabrication.py` now directly asserts the `getaddrinfo(host, port, family=..., type=...)` fallback call uses keywords and accepts a resolving domain, while unresolvable candidates are excluded. |
| Opt-out suppression before draft generation | PASS | `server.py` checks `businesses.is_suppressed` before hook/draft generation. |
| Opt-out suppression before SMTP dispatch | PASS (strengthened) | `deliverer.py` now checks both business and address suppression before `send_email`; its regression test proves no SMTP call occurs and the draft is cancelled. |
| Deduplication | PASS | draft generation checks business/email/domain; dispatch separately cancels a recipient already marked `SENT`. |
| Daily send cap | PASS | `delivery_allowance()` is resolved before dispatch and the dispatch loop re-checks its absolute ceiling per item; `test_ph002_daily_send_safety_limit` proves only two of four approved drafts reach SMTP when the configured cap is two. |
| Scheduler | PASS as intentionally manual | No scheduler was added; approve and deliver remain manual HTTP actions. |

### Pre-send dry run

Run this immediately before a manual delivery action:

```bash
python scripts/outreach_dry_run.py
# optional: restrict the report to selected approved drafts
python scripts/outreach_dry_run.py --draft-id <draft-id>
```

It performs no database writes and never opens SMTP. It reports fresh MX
results, suppression, already-sent recipient deduplication, resolved
from-address, current allowance, and the effective send count. A measured
empty-selection run produced:

```text
Outreach pre-send dry run (no email sent)
Resolved SMTP from-address: orvionstudio.co@gmail.com
Approved drafts inspected: 0
MX: 0 pass, 0 fail
Suppressed: 0
Deduplicated (already sent): 0
Eligible to dispatch: 0
Daily limit: 10; remaining allowance: 10
Effective send count: 0
```

### Directory providers

`enrichment.directory_providers_enabled` is now a live setting and is
**false**. With it false, IndiaMart, Justdial, and TradeIndia are removed from
the default email-enrichment path and phone enrichment is invoked with an
explicit platform list that excludes them. The providers were not deleted or
rewritten. A regression test confirms the disabled path returns its normal
empty result without an error.

### Explicitly deferred (deliberate omissions)

The following are quoted from the task scope and were not changed:

- “The B2B Dealer & Order Portal routing premise.” It lacks sufficient audit
  evidence; no gate, copy, or `campaign_routing.yaml` portal logic was touched.
- “The 12x12 subject slot expansion.” It was already complete; its router
  regression test remains in the focused suite.
- “A scheduler for approve/deliver.” Manual triggers remain correct for this
  first-batch stage.
- “llm.system_prompt or the hook-generation prompt itself.” Copy quality was
  outside this safety/deliverability change.
- “Any WhatsApp-side code.” It is a separate module and was not touched.

---

## 12. Stage 1 & Stage 2 Execution and Full Suite Verification (2026-09-20)

Measured and verified across the live codebase, SQLite database, and complete test suite.

### 1. State found from prior session
- Git inspection revealed partial uncommitted changes from the interrupted session: `.env` and `settings` table had been synchronized, initial draft of `dry_run.py` was present, and tests had partial coverage.
- The full test run log `/tmp/leadforge-full-pytest.log` existed but was 0 bytes (execution had terminated before suite completion).
- Live settings verification showed `outreach.daily_send_limit` set to `10`, `enrichment.directory_providers_enabled` set to `false`, and SMTP credentials synchronized with `.env`.

### 2. SMTP resolution decision
- Priority rule preserved: `os.getenv("SMTP_HOST")` remains authoritative at runtime via `get_smtp_config()`.
- To eliminate silent UI disagreement:
  - `get_smtp_config()` now returns `"source": "environment"` or `"source": "database"`.
  - The `/api/settings` endpoint was updated to explicitly surface `"source"` and `"authoritative"` metadata on all `smtp.*` keys.
  - The live `settings` table rows were reconciled with `.env` (`host=smtp.gmail.com`, `from_email=orvionstudio.co@gmail.com`).
  - Backed by tests in `tests/test_smtp_configuration_resolution.py`.

### 3. Recommended daily_send_limit: 10
- Sized strictly to the measured ~43 viable portal leads and ~48 total viable email addresses.
- Aligns with the Day 1 warm-up ramp ceiling of 10 defined in `leadforge/outreach/ramp.py` (`1:10,8:20,15:30,22:40`).
- The sender reputation on `orvionstudio.co@gmail.com` carries 2 historical hard bounces with 0 replies. Limiting the first batch to 10 emails per day spreads the ~40 approved drafts across 4 days, allowing daily review of delivery, bounce rate, and reply signals before volume escalates.

### 4. Safety rails re-verification table

| Rail | Verdict | Evidence & Current Wiring |
|---|---|---|
| Quality score persisted | PASS | `email_drafts.quality_score` column present; validated in `tests/test_draft_quality_gate.py`. |
| Quality enforced at bulk approval | PASS | `server.py` checks `score < min_score` (80) and halts unrated/low-scoring drafts; covered in `tests/test_draft_quality_gate.py`. |
| Repetition detection | PASS | `EmailQualityEngine.find_similar()` checks body similarity against approved cohort (threshold 0.70) and hook similarity (0.62). |
| Fallback-hook detection | PASS | `server.py` blocks drafts whose `hook_source` begins with `fallback:`; covered in `tests/test_draft_quality_gate.py`. |
| MX / domain verification | PASS | `_check_domain_has_mx()` in `aggregator.py` uses keyword args (`family=socket.AF_INET, type=socket.SOCK_STREAM`); rejects NXDOMAIN/unresolvable domains; verified by `tests/test_enrichment_no_fabrication.py`. |
| Opt-out suppression before draft generation | PASS | `server.py` checks `businesses.is_suppressed` AND queries `unsubscribe_suppressions` for `recipient_email`, raising HTTP 422 before hook generation; covered in `tests/test_outreach_hardening.py`. |
| Opt-out suppression before SMTP dispatch | PASS | `deliverer.py` queries business and `unsubscribe_suppressions` before SMTP socket open, marking suppressed drafts `CANCELLED`; covered in `tests/test_outreach_hardening.py`. |
| Deduplication | PASS | Draft generation checks `is_duplicate_outreach`; deliverer separately enforces deduplication against `SENT` drafts per recipient email before dispatch. |
| Daily send cap | PASS | Enforced at actual SMTP dispatch: `deliverer.py` evaluates `delivery_allowance()` at batch start and enforces `sent_today >= daily_limit` per item; covered by `tests/test_outreach_hardening.py`. |
| Scheduler | PASS (manual) | Intentionally manual HTTP triggers (`/api/outreach/drafts/bulk-approve`, `/api/outreach/deliver`); no automated background daemon. |

### 5. Standalone pre-send dry-run tool
- Runnable via `python scripts/outreach_dry_run.py` or `./scripts/outreach_dry_run.py` (with optional `--draft-id`).
- Real measured output against live database:
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

### 6. Directory scraper providers (Stage 2)
- Setting `enrichment.directory_providers_enabled` is persisted as `false` in `settings`.
- When disabled, `EmailEnrichmentOrchestrator`, `PhoneEnrichmentOrchestrator`, and `SearchOrchestrator` exclude `indiamart`, `justdial`, and `tradeindia`.
- Verified non-erroring pipeline behavior via `tests/test_enrichment_phase2_3.py`.

### 7. Full test suite verification
```text
======================= 719 passed, 1 warning in 56.45s ========================
```

### 8. Explicitly deferred items
1. **B2B Dealer & Order Portal routing premise:** Unchanged. `website_audits` has only 2 populated rows out of 330 businesses; no order flow audit data exists to gate on.
2. **12x12 subject slot expansion:** Unchanged and passing regression test `test_portal_subject_composition_reduces_collisions_in_48_lead_batch`.
3. **Scheduler for approve/deliver:** Unchanged; manual dispatch is intentional.
4. **LLM system prompt / hook content:** Unchanged; prompt and copy quality are out of scope.
5. **whatsapp_auto/ module:** Unchanged; preserved as a separate module.

