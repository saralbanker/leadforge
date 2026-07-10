"""Campaign Intelligence — Phase 5 passive metrics observer.

Attaches to every SearchPlan execution and records deterministic performance
metrics without influencing runtime behaviour.  Zero adaptive logic; zero
effect on search ordering, budget allocation, or termination decisions.

Architecture
────────────
Producer (in control_plane._producer) writes per-plan discovery metrics:
  1. Marks discovery start/end timestamps.
  2. Increments url_discovered counter for every URL yielded.
  3. Increments discovery_duplicate counter for pre-filter URL duplicates.
  4. Writes  url_plan_map[url] = plan_idx  for every queued (non-duplicate) URL.

Consumer (in control_plane.run_qualified_campaign) reads attribution + writes
outcome metrics:
  5. Calls attribute(source_url) → plan_idx to look up the originating plan.
  6. Records urls_processed, qualified, consumer_duplicates, and rejection
     breakdown per plan.

Finalization (after campaign ends):
  7. finalize() materialises PlanMetrics dataclasses with derived fields.
  8. save(search_id) persists to campaign_plan_metrics (migration 009).

Thread / concurrency model
──────────────────────────
All code runs inside a single asyncio event loop (no threads), so the
shared url_plan_map dict and per-plan accumulators require no locking.
The producer writes url_plan_map[url] before await url_queue.put(url);
the consumer reads it after the corresponding await url_queue.get(), so
the value is always present when the consumer looks it up.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from leadforge.sil.search_plan_generator import SearchPlan


# ── Immutable metric snapshot ─────────────────────────────────────────────────


@dataclass(frozen=True)
class PlanMetrics:
    """Immutable per-plan execution metrics produced by CampaignIntelligence.finalize()."""

    plan_idx: int
    search_query: str
    canonical_category: str
    geographic_partition: str

    # Producer-side: known at discovery time
    urls_discovered: int
    discovery_duplicates: int
    discovery_duration_s: float

    # Consumer-side: attributed via url_plan_map
    urls_processed: int
    qualified: int
    consumer_duplicates: int
    website_rejections: int
    phone_rejections: int
    validation_failures: int
    processing_duration_s: float

    # Derived
    yield_percentage: float     # qualified / urls_processed × 100
    duplicate_percentage: float # (discovery_dups + consumer_dups) / urls_discovered × 100

    def to_dict(self) -> dict:
        return {
            "plan_idx": self.plan_idx,
            "search_query": self.search_query,
            "canonical_category": self.canonical_category,
            "geographic_partition": self.geographic_partition,
            "urls_discovered": self.urls_discovered,
            "discovery_duplicates": self.discovery_duplicates,
            "discovery_duration_s": self.discovery_duration_s,
            "urls_processed": self.urls_processed,
            "qualified": self.qualified,
            "consumer_duplicates": self.consumer_duplicates,
            "website_rejections": self.website_rejections,
            "phone_rejections": self.phone_rejections,
            "validation_failures": self.validation_failures,
            "processing_duration_s": self.processing_duration_s,
            "yield_percentage": self.yield_percentage,
            "duplicate_percentage": self.duplicate_percentage,
        }


# ── Mutable per-plan accumulator (internal) ───────────────────────────────────


class _PlanAccumulator:
    """Mutable counters and timestamps for one SearchPlan execution."""

    def __init__(self, plan: "SearchPlan", plan_idx: int) -> None:
        self._plan = plan
        self.plan_idx = plan_idx

        # Producer-side
        self.urls_discovered: int = 0
        self.discovery_duplicates: int = 0
        self._discovery_start: float | None = None
        self._discovery_end: float | None = None

        # Consumer-side
        self.urls_processed: int = 0
        self.qualified: int = 0
        self.consumer_duplicates: int = 0
        self.website_rejections: int = 0
        self.phone_rejections: int = 0
        self.validation_failures: int = 0
        self._first_processed: float | None = None
        self._last_processed: float | None = None

    def mark_discovery_start(self) -> None:
        self._discovery_start = time.monotonic()

    def mark_discovery_end(self) -> None:
        self._discovery_end = time.monotonic()

    def touch_processed(self) -> None:
        now = time.monotonic()
        if self._first_processed is None:
            self._first_processed = now
        self._last_processed = now

    @property
    def discovery_duration_s(self) -> float:
        if self._discovery_start is None or self._discovery_end is None:
            return 0.0
        return self._discovery_end - self._discovery_start

    @property
    def processing_duration_s(self) -> float:
        if self._first_processed is None or self._last_processed is None:
            return 0.0
        return self._last_processed - self._first_processed

    def to_metrics(self) -> PlanMetrics:
        total_dups = self.discovery_duplicates + self.consumer_duplicates
        yield_pct = (
            self.qualified / self.urls_processed * 100
            if self.urls_processed > 0 else 0.0
        )
        dup_pct = (
            total_dups / self.urls_discovered * 100
            if self.urls_discovered > 0 else 0.0
        )
        return PlanMetrics(
            plan_idx=self.plan_idx,
            search_query=self._plan["search_query"],
            canonical_category=self._plan["canonical_category"],
            geographic_partition=self._plan["geographic_partition"],
            urls_discovered=self.urls_discovered,
            discovery_duplicates=self.discovery_duplicates,
            discovery_duration_s=round(self.discovery_duration_s, 3),
            urls_processed=self.urls_processed,
            qualified=self.qualified,
            consumer_duplicates=self.consumer_duplicates,
            website_rejections=self.website_rejections,
            phone_rejections=self.phone_rejections,
            validation_failures=self.validation_failures,
            processing_duration_s=round(self.processing_duration_s, 3),
            yield_percentage=round(yield_pct, 2),
            duplicate_percentage=round(dup_pct, 2),
        )


# ── Public observer ───────────────────────────────────────────────────────────


class CampaignIntelligence:
    """Passive per-plan metrics collector.

    Has no influence on search ordering, budget, or termination.
    All mutation methods are fire-and-forget with silent no-op fallback
    for unknown plan_idx values (so a misconfigured call never crashes
    the campaign).
    """

    def __init__(self, search_plans: list["SearchPlan"]) -> None:
        self._accumulators: dict[int, _PlanAccumulator] = {
            i: _PlanAccumulator(plan, i)
            for i, plan in enumerate(search_plans)
        }
        # Producer writes url_plan_map[url] = plan_idx before enqueue.
        # Consumer reads it via attribute(source_url).
        self.url_plan_map: dict[str, int] = {}
        self._finalized: list[PlanMetrics] | None = None

    # ── Producer-side API ──────────────────────────────────────────────────

    def mark_discovery_start(self, plan_idx: int) -> None:
        acc = self._accumulators.get(plan_idx)
        if acc:
            acc.mark_discovery_start()

    def mark_discovery_end(self, plan_idx: int) -> None:
        acc = self._accumulators.get(plan_idx)
        if acc:
            acc.mark_discovery_end()

    def record_url_discovered(self, plan_idx: int) -> None:
        """Increment urls_discovered counter for the given plan."""
        acc = self._accumulators.get(plan_idx)
        if acc:
            acc.urls_discovered += 1

    def record_discovery_duplicate(self, plan_idx: int) -> None:
        """Increment discovery_duplicates (URL-level pre-filter hit)."""
        acc = self._accumulators.get(plan_idx)
        if acc:
            acc.discovery_duplicates += 1

    # ── Consumer-side API ──────────────────────────────────────────────────

    def attribute(self, source_url: str) -> int:
        """Return the plan_idx that produced *source_url*, or -1 if unknown."""
        return self.url_plan_map.get(source_url, -1)

    def record_processed(self, plan_idx: int) -> None:
        """Mark one business as entering consumer processing for this plan."""
        acc = self._accumulators.get(plan_idx)
        if acc:
            acc.urls_processed += 1
            acc.touch_processed()

    def record_qualified(self, plan_idx: int) -> None:
        acc = self._accumulators.get(plan_idx)
        if acc:
            acc.qualified += 1

    def record_consumer_duplicate(self, plan_idx: int) -> None:
        """Post-scrape duplicate — business already in the registry."""
        acc = self._accumulators.get(plan_idx)
        if acc:
            acc.consumer_duplicates += 1

    def record_rejection(self, plan_idx: int, reason: str) -> None:
        """Route a validator rejection to the appropriate counter."""
        acc = self._accumulators.get(plan_idx)
        if acc is None:
            return
        if reason == "HAS_WEBSITE":
            acc.website_rejections += 1
        elif reason == "NO_PHONE":
            acc.phone_rejections += 1
        else:
            acc.validation_failures += 1

    # ── Output ─────────────────────────────────────────────────────────────

    def finalize(self) -> list[PlanMetrics]:
        """Return immutable PlanMetrics for every plan in execution order."""
        if self._finalized is None:
            self._finalized = [
                acc.to_metrics()
                for acc in sorted(
                    self._accumulators.values(), key=lambda a: a.plan_idx
                )
            ]
        return self._finalized

    def save(self, search_id: str | None) -> None:
        """Persist plan metrics to campaign_plan_metrics (migration 009).

        No-op if search_id is None (test / headless runs without DB).
        """
        if not search_id:
            return
        from leadforge.database import get_db_connection, uuidv7
        metrics = self.finalize()
        rows = [
            (
                uuidv7(),
                search_id,
                m.plan_idx,
                m.search_query,
                m.canonical_category,
                m.geographic_partition,
                m.urls_discovered,
                m.discovery_duplicates,
                m.discovery_duration_s,
                m.urls_processed,
                m.qualified,
                m.consumer_duplicates,
                m.website_rejections,
                m.phone_rejections,
                m.validation_failures,
                m.processing_duration_s,
                m.yield_percentage,
                m.duplicate_percentage,
            )
            for m in metrics
        ]
        conn = get_db_connection()
        try:
            conn.executemany(
                """INSERT OR REPLACE INTO campaign_plan_metrics
                   (id, search_id, plan_idx, search_query, canonical_category,
                    geographic_partition, urls_discovered, discovery_duplicates,
                    discovery_duration_s, urls_processed, qualified,
                    consumer_duplicates, website_rejections, phone_rejections,
                    validation_failures, processing_duration_s,
                    yield_percentage, duplicate_percentage)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
