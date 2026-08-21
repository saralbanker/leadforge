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
