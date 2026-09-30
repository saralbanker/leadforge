"""Control Plane module for LeadForge V3.0/3.1/3.2 architecture.

Implements the Search Planner, Search Orchestrator, and control loop.
Ensures optimization for Qualified Leads, applying standardization, duplicate matching,
qualification validation, confidence grading, opportunity evaluation, and SQLite persistence.
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from playwright.async_api import async_playwright
from leadforge.config import (
    DEFAULT_CITY_PIN_PREFIXES,
    HEADLESS_SCRAPING,
    PLAYWRIGHT_SLOWMO,
    USER_AGENT,
)
from leadforge.execution_state import ScraperExecutionState
from leadforge.validator import BusinessValidator
from leadforge.confidence_engine import ConfidenceEngine
from leadforge.opportunity_engine import OpportunityIntelligenceEngine
from leadforge.merge import BusinessMerger
from leadforge.repositories.lead import SQLiteLeadRepository
from leadforge.repositories.settings import SettingsCache
from leadforge.search import discover_business_links_stream
from leadforge.collector import collect_business_details_stream
from leadforge.normalizer import (
    normalize_phone,
    normalize_website,
    normalize_domain,
    normalize_category,
    normalize_status,
)
from leadforge.sil.search_plan_generator import SearchPlanGenerator, SearchPlan
from leadforge.campaign_intelligence import CampaignIntelligence
from leadforge.enrichment.phone_orchestrator import PhoneEnrichmentOrchestrator
from leadforge.taxonomy import get_keywords_for_subcategory
from leadforge.search_directory import (
    discover_indiamart_businesses_stream,
    discover_justdial_businesses_stream,
    discover_tradeindia_businesses_stream,
)
from leadforge.utils import extract_place_id, get_logger

logger = get_logger()

_YIELD_SAMPLE_INTERVAL = 5  # adaptive budget recomputed every N businesses


def _check_performance_budgets(
    state: "ScraperExecutionState", settings_cache: "SettingsCache"
) -> None:
    """Emit structured warnings when campaign runtime exceeds configured budgets.

    Warnings are observational only — they never alter business behaviour.
    """
    warnings: List[str] = []

    max_campaign_sec = settings_cache.get_float("PERF_BUDGET_MAX_CAMPAIGN_SEC", 3600.0)
    if state.elapsed() > max_campaign_sec:
        warnings.append(
            f"campaign exceeded max runtime: {state.elapsed():.1f}s > {max_campaign_sec:.0f}s"
        )

    if state.qualified_count > 0:
        vpl = state.budget_consumed / state.qualified_count
        max_vpl = settings_cache.get_float("PERF_BUDGET_MAX_VISITS_PER_QUALIFIED", 20.0)
        if vpl > max_vpl:
            warnings.append(
                f"high visits per qualified lead: {vpl:.1f} > {max_vpl:.0f}"
            )

    min_yield = settings_cache.get_float("PERF_BUDGET_MIN_YIELD", 0.05)
    if state.budget_consumed >= 10 and state.qualification_yield() < min_yield:
        warnings.append(
            f"low qualification yield: {state.qualification_yield():.1%} < {min_yield:.1%}"
        )

    for w in warnings:
        logger.warning(f"[PERF BUDGET] {w}")


def _log_efficiency_report(state: "ScraperExecutionState") -> None:
    """Log a deterministic campaign efficiency report after every completed campaign."""
    visited = state.budget_consumed
    qualified = state.qualified_count
    rejected = state.rejected_count
    dups = state.duplicate_count
    elapsed = state.elapsed()

    yield_pct = state.qualification_yield() * 100
    avg_s_lead = state.avg_seconds_per_qualified_lead()
    avg_s_biz = state.avg_seconds_per_business()

    # Campaign score (0–100):  yield component + completion component + dedup component
    yield_score = min(40.0, yield_pct * 40.0 / 25.0)  # 25% yield → full 40 pts
    completion_score = min(1.0, qualified / max(1, state.limit)) * 40.0
    dup_rate = dups / max(1, visited + dups)
    dedup_score = max(0.0, 1.0 - dup_rate) * 20.0
    campaign_score = int(yield_score + completion_score + dedup_score)

    sep = "=" * 52
    lines = [
        sep,
        "  CAMPAIGN EFFICIENCY REPORT",
        sep,
        f"  Requested Leads:              {state.limit}",
        f"  Qualified Leads:              {qualified}",
        f"  Businesses Visited:           {visited}",
        f"  Businesses Rejected:          {rejected}",
        f"  Duplicate Count:              {dups}",
        f"  Qualification Yield:          {yield_pct:.1f}%",
        f"  Avg Seconds / Qualified Lead: {avg_s_lead:.1f}s",
        f"  Avg Seconds / Business:       {avg_s_biz:.1f}s",
        f"  Total Elapsed:                {elapsed:.1f}s",
        f"  Adaptive Budget Used:         {state.search_budget} (initial: {state._initial_budget})",
        f"  Termination Reason:           {state.termination_reason}",
        f"  Campaign Score:               {campaign_score}/100",
        sep,
    ]
    for line in lines:
        logger.info(line)


def _extract_place_id(url: str) -> Optional[str]:
    """Extract a Google Place ID; supports all known Maps URL variants."""
    return extract_place_id(url)


def _check_extraction_rates(
    state: "ScraperExecutionState", settings_cache: "SettingsCache"
) -> None:
    """Emit deterministic warnings when extraction success rates fall below the
    configured threshold. Observational only — never alters behaviour."""
    min_rate = settings_cache.get_float("QUALITY_MIN_EXTRACTION_RATE", 0.5)
    min_sample = settings_cache.get_int("QUALITY_MIN_EXTRACTION_SAMPLE", 5)
    if state.extraction_stats.get("attempts", 0) < min_sample:
        return
    for field, rate in state.extraction_rates().items():
        if rate < min_rate:
            logger.warning(
                f"[EXTRACTION QUALITY] {field} extraction rate {rate:.1%} "
                f"below threshold {min_rate:.1%} — check Google Maps selectors."
            )


def _log_quality_report(state: "ScraperExecutionState") -> None:
    """Log the deterministic campaign quality report after every campaign."""
    rates = state.extraction_rates()
    tier1 = state.tier1_rejections
    sep = "=" * 52
    lines = [
        sep,
        "  CAMPAIGN QUALITY REPORT",
        sep,
        f"  Visited:                {state.budget_consumed}",
        f"  Qualified:              {state.qualified_count}",
        f"  Rejected:               {state.rejected_count}",
        f"  Duplicate:              {state.duplicate_count}",
        f"  Category Unverified:    {state.category_unverified_count}",
        f"  Wrong Category:         {state.wrong_category_count}",
        f"  Wrong City:             {state.wrong_city_count}",
        f"  Ghost Listings:         {state.ghost_listing_count}",
        f"  No Phone:               {state.no_phone_count + tier1.get('NO_PHONE', 0)}",
        f"  Has Website:            {state.has_website_count + tier1.get('HAS_WEBSITE', 0)}",
        f"  Review Extraction %:    {rates['reviews']:.1%}",
        f"  Category Extraction %:  {rates['categories']:.1%}",
        f"  Address Extraction %:   {rates['address']:.1%}",
        f"  Average Confidence:     {state.avg_confidence():.2f}",
        sep,
    ]
    for line in lines:
        logger.info(line)


class SearchPlanner:
    """Plans search execution boundaries (e.g. max budget, batch sizing)."""

    def plan(self, limit: int) -> int:
        """Determines the search budget constraint (limit * 4)."""
        return limit * 4


class SearchOrchestrator:
    """Orchestrates the Qualified Lead Pipeline control loop."""

    def __init__(self) -> None:
        self._settings_cache = SettingsCache()
        self.validator = BusinessValidator()
        self.confidence_engine = ConfidenceEngine()
        self.merger = BusinessMerger()
        self.lead_repo = SQLiteLeadRepository()
        self.opp_engine = OpportunityIntelligenceEngine(
            settings_repo=self._settings_cache
        )
        self.discovered_links: List[str] = []

    async def run_qualified_campaign(
        self,
        city: str,
        category: str,
        limit: int,
        no_website_only: bool = False,
        website_filter: str = "ALL",
        search_id: Optional[str] = None,
        campaign_name: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        sub_category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Executes the qualified lead pipeline as a streaming producer-consumer.

        Supports multi-platform discovery (Google Maps, IndiaMart, Justdial, TradeIndia)
        with automatic rollover and multi-provider phone enrichment.
        """
        planner = SearchPlanner()
        budget = planner.plan(limit)
        state = ScraperExecutionState(limit=limit, search_budget=budget)
        self.state = state
        self.discovered_links = state.discovered_links  # live reference

        effective_category = sub_category.strip() if sub_category and sub_category.strip() else category
        active_platforms = [p.lower().strip() for p in (platforms or ["google_maps"])]
        if not active_platforms:
            active_platforms = ["google_maps"]

        # IndiaMart, Justdial, and TradeIndia are known to return no usable
        # contact data.  Keep them opt-in even if an old caller still supplies
        # one of their names.
        from leadforge.enrichment.orchestrator import directory_providers_enabled
        if not directory_providers_enabled(self._settings_cache):
            active_platforms = [
                platform for platform in active_platforms
                if platform not in {"indiamart", "justdial", "tradeindia"}
            ]
            if not active_platforms:
                active_platforms = ["google_maps"]

        logger.info("⚡ Search Orchestrator: Starting qualified-lead campaign.")
        logger.info(f"Target limit: {limit} qualified leads | Search budget: {budget}")
        logger.info(f"Category: '{effective_category}' (Sector: '{category}') | Platforms: {active_platforms}")

        # --- SIL: generate deterministic search plan with taxonomy keyword expansion ---
        _sil = SearchPlanGenerator()
        search_plans: list[SearchPlan] = []

        keywords_to_search: List[str] = []
        if sub_category and sub_category.strip():
            keywords_to_search = get_keywords_for_subcategory(category, sub_category.strip())

        if keywords_to_search:
            for kw in keywords_to_search[:5]:
                kw_plans = _sil.generate(city, kw, target_qualified_leads=limit)
                search_plans.extend(kw_plans)

        if not search_plans:
            search_plans = _sil.generate(
                city, effective_category, target_qualified_leads=limit
            )

        if not search_plans:
            search_plans = [
                SearchPlan(
                    search_query=f"{effective_category} in {city}",
                    canonical_category=effective_category,
                    geographic_partition=city,
                    original_city=city,
                    priority_score=1.0,
                    execution_order=1,
                )
            ]

        # Deduplicate search plans by normalized query
        seen_q = set()
        deduped_plans = []
        for plan in search_plans:
            q_key = plan["search_query"].strip().lower()
            if q_key not in seen_q:
                seen_q.add(q_key)
                plan["execution_order"] = len(deduped_plans) + 1
                deduped_plans.append(plan)
        search_plans = deduped_plans

        logger.info(
            f"[SIL] {len(search_plans)} search plan(s) for '{effective_category}' in '{city}'"
        )

        # --- Phase 5: Campaign Intelligence observer (passive, no runtime effect) ---
        ci = CampaignIntelligence(search_plans)

        # Deterministic validation configuration (settings-overridable)
        allow_temp_closed = (
            self._settings_cache.get_int("VALIDATION_ALLOW_TEMP_CLOSED", 0) == 1
        )
        pin_map: Dict[str, List[str]] = dict(DEFAULT_CITY_PIN_PREFIXES)
        pin_raw = self._settings_cache.get_str("CITY_PIN_PREFIXES", "")
        if pin_raw:
            try:
                pin_map = {
                    str(k).strip().lower(): list(v)
                    for k, v in json.loads(pin_raw).items()
                }
            except Exception:
                logger.warning(
                    "CITY_PIN_PREFIXES setting is not valid JSON — using defaults."
                )

        # --- Phase 3: single shared browser for the entire campaign ---
        custom_user_agent = self._settings_cache.get_str("USER_AGENT", USER_AGENT)
        _browser_start = time.monotonic()
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=HEADLESS_SCRAPING,
            slow_mo=PLAYWRIGHT_SLOWMO,
            args=["--disable-gpu", "--no-sandbox"],
        )
        shared_context = await browser.new_context(
            user_agent=custom_user_agent,
            viewport={"width": 1280, "height": 800},
        )
        browser_startup_sec = time.monotonic() - _browser_start
        logger.info(f"Browser startup: {browser_startup_sec:.2f}s")

        url_queue: asyncio.Queue = asyncio.Queue(maxsize=40)
        discovery_failed = False
        pre_filter_skipped = 0
        _producer_cancelled = False

        async def _producer() -> None:
            """Execute discovery across enabled platforms sequentially with rollover."""
            nonlocal discovery_failed, pre_filter_skipped, _producer_cancelled
            plans_attempted = 0
            plans_failed = 0
            try:
                for target_platform in active_platforms:
                    if (
                        state.qualified_count >= limit
                        or state.budget_consumed >= state.search_budget
                        or state.search_space_exhausted
                    ):
                        break

                    logger.info(f"⚡ Discovery search executing on platform: '{target_platform}'")

                    if target_platform == "google_maps":
                        for plan in search_plans:
                            if (
                                state.qualified_count >= limit
                                or state.budget_consumed >= state.search_budget
                                or state.search_space_exhausted
                            ):
                                break

                            plans_attempted += 1
                            plan_idx = plan["execution_order"] - 1
                            partition = plan["geographic_partition"]
                            variant = plan["search_query"].removesuffix(f" in {partition}")
                            remaining = max(1, state.search_budget - len(state.discovered_links))

                            logger.info(
                                f"[SIL] Plan {plan['execution_order']}/{len(search_plans)}: "
                                f"'{plan['search_query']}' (budget remaining: {remaining})"
                            )

                            ci.mark_discovery_start(plan_idx)
                            try:
                                async for url in discover_business_links_stream(
                                    partition,
                                    variant,
                                    limit=remaining,
                                    settings_cache=self._settings_cache,
                                    context=shared_context,
                                ):
                                    state.discovered_links.append(url)
                                    ci.record_url_discovered(plan_idx)
                                    early_pid = _extract_place_id(url)
                                    if self.lead_repo.check_duplicate(early_pid or "", "", ""):
                                        state.record_duplicate()
                                        ci.record_discovery_duplicate(plan_idx)
                                        pre_filter_skipped += 1
                                        continue
                                    ci.url_plan_map[url] = plan_idx
                                    await url_queue.put(url)
                            except RuntimeError as exc:
                                if "DISCOVERY_FAILED" in str(exc):
                                    logger.warning(
                                        f"[SIL] Plan {plan['execution_order']} discovery failed: "
                                        f"'{plan['search_query']}'"
                                    )
                                    plans_failed += 1
                            finally:
                                ci.mark_discovery_end(plan_idx)

                    elif target_platform == "indiamart":
                        terms = keywords_to_search[:3] if keywords_to_search else [effective_category]
                        for term in terms:
                            if state.qualified_count >= limit or state.budget_consumed >= state.search_budget:
                                break
                            remaining = max(1, state.search_budget - len(state.discovered_links))
                            async for item in discover_indiamart_businesses_stream(city, term, limit=remaining):
                                if state.qualified_count >= limit or state.budget_consumed >= state.search_budget:
                                    break
                                if self.lead_repo.check_duplicate(None, item["name"], item.get("phone")):
                                    state.record_duplicate()
                                    pre_filter_skipped += 1
                                    continue
                                state.discovered_links.append(item.get("source_url", item["name"]))
                                await url_queue.put(item)

                    elif target_platform == "justdial":
                        terms = keywords_to_search[:3] if keywords_to_search else [effective_category]
                        for term in terms:
                            if state.qualified_count >= limit or state.budget_consumed >= state.search_budget:
                                break
                            remaining = max(1, state.search_budget - len(state.discovered_links))
                            async for item in discover_justdial_businesses_stream(city, term, limit=remaining):
                                if state.qualified_count >= limit or state.budget_consumed >= state.search_budget:
                                    break
                                if self.lead_repo.check_duplicate(None, item["name"], item.get("phone")):
                                    state.record_duplicate()
                                    pre_filter_skipped += 1
                                    continue
                                state.discovered_links.append(item.get("source_url", item["name"]))
                                await url_queue.put(item)

                    elif target_platform == "tradeindia":
                        terms = keywords_to_search[:3] if keywords_to_search else [effective_category]
                        for term in terms:
                            if state.qualified_count >= limit or state.budget_consumed >= state.search_budget:
                                break
                            remaining = max(1, state.search_budget - len(state.discovered_links))
                            async for item in discover_tradeindia_businesses_stream(city, term, limit=remaining):
                                if state.qualified_count >= limit or state.budget_consumed >= state.search_budget:
                                    break
                                if self.lead_repo.check_duplicate(None, item["name"], item.get("phone")):
                                    state.record_duplicate()
                                    pre_filter_skipped += 1
                                    continue
                                state.discovered_links.append(item.get("source_url", item["name"]))
                                await url_queue.put(item)

                if plans_attempted > 0 and plans_failed == plans_attempted and len(active_platforms) == 1 and active_platforms[0] == "google_maps":
                    logger.error(
                        "Discovery phase failed — all search plans failed."
                    )
                    discovery_failed = True

            except asyncio.CancelledError:
                _producer_cancelled = True
            finally:
                if _producer_cancelled:
                    try:
                        url_queue.put_nowait(None)
                    except asyncio.QueueFull:
                        while not url_queue.empty():
                            try:
                                url_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        url_queue.put_nowait(None)
                else:
                    await url_queue.put(None)

        async def _url_source():
            while True:
                url = await url_queue.get()
                if url is None:
                    break
                yield url

        producer_task = asyncio.create_task(_producer())
        qualified_leads: List[Dict[str, Any]] = []

        try:
            async for raw_lead in collect_business_details_stream(
                _url_source(),
                effective_category,
                city=city,
                settings_cache=self._settings_cache,
                context=shared_context,
                no_website_only=no_website_only,
                website_filter=website_filter,
                tier1_stats=state.tier1_rejections,
                extraction_stats=state.extraction_stats,
            ):
                _plan_idx = ci.attribute(raw_lead.get("source_url", ""))

                if not state.should_continue():
                    break

                state.consume_budget()
                ci.record_processed(_plan_idx)
                if state.budget_consumed % _YIELD_SAMPLE_INTERVAL == 0:
                    if state.update_adaptive_budget():
                        logger.info(
                            f"Adaptive budget tightened → {state.search_budget} "
                            f"(yield={state.qualification_yield():.1%}, "
                            f"visited={state.budget_consumed})"
                        )
                logger.info(f"Processing scraped result {state.budget_consumed}...")

                standard_lead = {
                    "name": raw_lead.get("name", ""),
                    "phone": normalize_phone(raw_lead.get("phone", "")),
                    "website": normalize_website(raw_lead.get("website", "")),
                    "website_domain": normalize_domain(raw_lead.get("website", "")),
                    "address": raw_lead.get("address", ""),
                    "area": raw_lead.get("area", ""),
                    "postal_code": raw_lead.get("postal_code", ""),
                    "category": normalize_category(raw_lead.get("category", effective_category)),
                    "google_primary_category": raw_lead.get(
                        "google_primary_category", ""
                    ),
                    "source_url": raw_lead.get("source_url", ""),
                    "rating": raw_lead.get("rating"),
                    "review_count": raw_lead.get("review_count"),
                    "business_status": normalize_status(
                        raw_lead.get("business_status", "OPERATIONAL")
                    ),
                    "opening_hours": raw_lead.get("opening_hours", ""),
                    "categories": raw_lead.get("categories", ""),
                    "email": raw_lead.get("email", ""),
                    "social_links": raw_lead.get("social_links", ""),
                    "city": city,
                    "primary_platform": raw_lead.get("primary_platform", "google_maps"),
                    "phone_source": raw_lead.get("primary_platform", "google_maps"),
                    "phone_candidates": [],
                }

                # Cross-Platform Phone Enrichment & Candidate Aggregation
                try:
                    enricher = PhoneEnrichmentOrchestrator()
                    p_phone, p_source, c_phone, cand_list = await enricher.enrich_phone(
                        business_profile={
                            "name": standard_lead["name"],
                            "city": city,
                            "category": standard_lead["category"],
                            "website": standard_lead["website"],
                            "website_domain": standard_lead["website_domain"],
                            "source_url": standard_lead["source_url"],
                        },
                        enabled_platforms=active_platforms,
                        initial_phone=raw_lead.get("phone"),
                        initial_source=raw_lead.get("primary_platform", "google_maps"),
                    )
                    if p_phone:
                        standard_lead["phone"] = p_phone
                        standard_lead["phone_source"] = p_source or raw_lead.get("primary_platform", "google_maps")
                        standard_lead["phone_candidates"] = cand_list
                    else:
                        standard_lead["phone_source"] = raw_lead.get("primary_platform", "google_maps")
                        standard_lead["phone_candidates"] = cand_list or []
                except Exception as exc:
                    logger.debug(f"[ControlPlane] Phone enrichment failed for '{standard_lead['name']}': {exc}")
                    standard_lead["phone_source"] = raw_lead.get("primary_platform", "google_maps")
                    standard_lead["phone_candidates"] = []

                google_place_id = _extract_place_id(standard_lead["source_url"])
                standard_lead["google_place_id"] = google_place_id

                is_duplicate = self.lead_repo.check_duplicate(
                    google_place_id=google_place_id,
                    name=standard_lead["name"],
                    phone=standard_lead["phone"],
                )

                if is_duplicate:
                    logger.info(
                        f"Duplicate match found for '{standard_lead['name']}'. Merging fields..."
                    )
                    state.record_duplicate()
                    ci.record_consumer_duplicate(_plan_idx)
                    existing_id = self.lead_repo._find_existing_business_id(
                        google_place_id,
                        standard_lead["name"],
                        standard_lead["phone"],
                        standard_lead["address"],
                        standard_lead["area"],
                    )
                    existing_biz = self.lead_repo._get_existing_business_by_id(
                        existing_id
                    )
                    if existing_biz:
                        updates, conflicts = self.merger.merge(
                            existing_biz, standard_lead
                        )
                        self.lead_repo.save_merged_lead(
                            existing_id,
                            updates,
                            conflicts,
                            standard_lead,
                            campaign_name,
                            search_id,
                            link_to_campaign=False,
                        )
                    continue

                val_res = self.validator.validate(
                    standard_lead,
                    no_website_only=no_website_only,
                    website_filter=website_filter,
                    target_city=city,
                    target_category=effective_category,
                    allow_temporarily_closed=allow_temp_closed,
                    pin_prefix_map=pin_map,
                )

                if val_res != "PASS":
                    logger.info(
                        f"Lead '{standard_lead['name']}' rejected [{val_res}]. "
                        f"Qualified so far: {state.qualified_count}/{limit}"
                    )
                    state.record_rejection(val_res)
                    ci.record_rejection(_plan_idx, val_res)
                    continue

                logger.info(f"Qualified lead confirmed: '{standard_lead['name']}'")

                weights = self.opp_engine._load_weights()
                signals, score = self.opp_engine._compute_signals(
                    standard_lead, weights
                )
                positive_signal_count = sum(1 for s in signals if s.score_delta > 0)

                maturity = self.opp_engine._maturity.assess(standard_lead)
                confidence_level, confidence_rationale = (
                    self.confidence_engine.calculate(
                        score,
                        positive_signal_count,
                        maturity.data_completeness,
                        weights,
                    )
                )

                state.record_confidence(confidence_level)

                if confidence_level == "LOW":
                    logger.info(
                        f"Lead '{standard_lead['name']}' rejected [LOW_CONFIDENCE]. "
                        f"Rationale: {confidence_rationale}"
                    )
                    state.record_rejection("LOW_CONFIDENCE")
                    ci.record_rejection(_plan_idx, "LOW_CONFIDENCE")
                    continue

                opp_drafts, maturity = self.opp_engine.evaluate_opportunities(
                    standard_lead
                )

                biz_id = self.lead_repo.save_new_qualified_lead(
                    standard_lead, opp_drafts, maturity, campaign_name, search_id
                )

                standard_lead["id"] = biz_id
                standard_lead["priority"] = "High" if score >= 60 else "Medium"
                standard_lead["score"] = score
                standard_lead["notes"] = confidence_rationale
                standard_lead["maturity_grade"] = maturity.grade
                standard_lead["maturity_score"] = round(maturity.score, 1)
                standard_lead["discovery_date"] = datetime.now().strftime("%Y-%m-%d")

                qualified_leads.append(standard_lead)
                state.increment_qualified()
                ci.record_qualified(_plan_idx)

        finally:
            # Stop discovery, then close the shared browser.
            producer_task.cancel()
            try:
                await asyncio.wait_for(producer_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            await browser.close()
            await pw.stop()

        _check_performance_budgets(state, self._settings_cache)
        _check_extraction_rates(state, self._settings_cache)
        _log_efficiency_report(state)
        _log_quality_report(state)

        # --- Phase 5: finalise and persist campaign intelligence metrics ---
        plan_metrics = ci.finalize()
        logger.info(
            f"[CI] Plan metrics finalised: {len(plan_metrics)} plan(s) observed."
        )
        for pm in plan_metrics:
            logger.info(
                f"[CI] Plan {pm.plan_idx}: '{pm.search_query}' | "
                f"discovered={pm.urls_discovered} dup={pm.discovery_duplicates} "
                f"processed={pm.urls_processed} qualified={pm.qualified} "
                f"yield={pm.yield_percentage:.1f}%"
            )
        ci.save(search_id)

        if discovery_failed:
            state.mark_search_space_exhausted()
            state.termination_reason = "DISCOVERY_FAILED"
            return []

        if pre_filter_skipped:
            logger.info(
                f"Pre-filter: {pre_filter_skipped} URL-level duplicate(s) skipped. "
                f"{len(state.discovered_links) - pre_filter_skipped} links sent to scraper."
            )

        self.found_count = len(state.discovered_links)

        if state.qualified_count < limit and not state.termination_reason:
            state.mark_search_space_exhausted()

        if not state.termination_reason:
            state.termination_reason = "REQUESTED_COUNT_REACHED"

        logger.info(
            f"Control Loop complete. Qualified: {state.qualified_count}/{limit} | "
            f"Reason: {state.termination_reason} | "
            f"Rejected: {state.rejected_count} | Duplicates: {state.duplicate_count}"
        )
        return qualified_leads
