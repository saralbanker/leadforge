"""Execution State module for LeadForge V3.0 architecture.

ONLY stores runtime state (progress, retry queue, qualified count, search budget).
NEVER stores business intelligence.
"""

import time
from typing import Any, Dict, List

_YIELD_SAMPLE_INTERVAL = 5  # recompute adaptive budget every N businesses visited

# Rejection reason → counter attribute name
_REJECTION_COUNTER_MAP = {
    "NO_NAME": "no_name_count",
    "NO_PHONE": "no_phone_count",
    "PERMANENTLY_CLOSED": "permanently_closed_count",
    "WRONG_STATUS": "wrong_status_count",
    "WRONG_CATEGORY": "wrong_category_count",
    "WRONG_CITY": "wrong_city_count",
    "HAS_WEBSITE": "has_website_count",
    "BELOW_MIN_RATING": "below_min_rating_count",
    "BELOW_MIN_REVIEWS": "below_min_reviews_count",
    "WRONG_AREA": "wrong_area_count",
    "LOW_CONFIDENCE": "low_confidence_count",
    "CATEGORY_UNVERIFIED": "category_unverified_count",
    "NO_ADDRESS": "no_address_count",
    "GHOST_LISTING": "ghost_listing_count",
}

# Tier-1 (collector-level) rejection reasons tracked separately from validator
# rejections — these businesses never reach Tier-2 extraction or validation.
_TIER1_REASONS = ("NO_NAME", "NO_PHONE", "HAS_WEBSITE", "CLOSED")

# Enrichment fields whose extraction success rate is measured per campaign.
_EXTRACTION_FIELDS = ("rating", "reviews", "categories", "address", "opening_hours")

# Deterministic numeric mapping for average-confidence reporting.
_CONFIDENCE_NUMERIC = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.0}


class ScraperExecutionState:
    """Tracks the progress and constraints of a scraper campaign run."""

    def __init__(self, limit: int, search_budget: int = None) -> None:
        self.limit = limit
        self.qualified_count = 0
        # If budget is not specified, default to 3x limit (standard over-fetch budget)
        self.search_budget = search_budget if search_budget is not None else limit * 3
        self._initial_budget: int = self.search_budget
        self.budget_consumed = 0
        self.search_space_exhausted = False
        self.discovered_links: List[str] = []
        self.processed_links_count = 0

        # Termination tracking
        self.termination_reason: str = ""

        # Per-rejection-type counters
        self.rejected_count: int = 0
        self.no_name_count: int = 0
        self.no_phone_count: int = 0
        self.permanently_closed_count: int = 0
        self.wrong_status_count: int = 0
        self.wrong_category_count: int = 0
        self.wrong_city_count: int = 0
        self.has_website_count: int = 0
        self.below_min_rating_count: int = 0
        self.below_min_reviews_count: int = 0
        self.wrong_area_count: int = 0
        self.low_confidence_count: int = 0
        self.category_unverified_count: int = 0
        self.no_address_count: int = 0
        self.ghost_listing_count: int = 0
        self.duplicate_count: int = 0

        # Tier-1 rejection counters (incremented in place by the collector)
        self.tier1_rejections: Dict[str, int] = {r: 0 for r in _TIER1_REASONS}

        # Extraction success counters (incremented in place by the collector)
        self.extraction_stats: Dict[str, int] = {
            "attempts": 0,
            **{f: 0 for f in _EXTRACTION_FIELDS},
        }

        # Confidence tracking for evaluated leads
        self._confidence_total: float = 0.0
        self._confidence_samples: int = 0

        # Timing (monotonic for duration math; not wall-clock)
        self._campaign_start: float = time.monotonic()

    def should_continue(self) -> bool:
        """Determines if the scraper loop should continue running.

        Sets termination_reason on the first call that returns False.
        """
        if self.qualified_count >= self.limit:
            if not self.termination_reason:
                self.termination_reason = "REQUESTED_COUNT_REACHED"
            return False
        if self.budget_consumed >= self.search_budget:
            if not self.termination_reason:
                self.termination_reason = "SEARCH_BUDGET_EXHAUSTED"
            return False
        if self.search_space_exhausted:
            if not self.termination_reason:
                self.termination_reason = "SEARCH_SPACE_EXHAUSTED"
            return False
        return True

    def mark_search_space_exhausted(self) -> None:
        """Call after all candidate links have been processed without reaching the limit."""
        self.search_space_exhausted = True
        if not self.termination_reason:
            self.termination_reason = "SEARCH_SPACE_EXHAUSTED"

    def increment_qualified(self) -> None:
        self.qualified_count += 1

    def consume_budget(self) -> None:
        self.budget_consumed += 1

    def record_rejection(self, reason: str) -> None:
        """Increments the appropriate per-type rejection counter."""
        self.rejected_count += 1
        counter_attr = _REJECTION_COUNTER_MAP.get(reason, "")
        if counter_attr:
            setattr(self, counter_attr, getattr(self, counter_attr) + 1)

    def record_duplicate(self) -> None:
        self.duplicate_count += 1

    def record_confidence(self, level: str) -> None:
        """Track the confidence level of an evaluated lead (HIGH/MEDIUM/LOW)."""
        self._confidence_total += _CONFIDENCE_NUMERIC.get(level, 0.0)
        self._confidence_samples += 1

    def avg_confidence(self) -> float:
        """Average confidence across evaluated leads (0.0–1.0; HIGH=1, MEDIUM=0.5)."""
        if self._confidence_samples == 0:
            return 0.0
        return self._confidence_total / self._confidence_samples

    def extraction_rates(self) -> Dict[str, float]:
        """Per-field extraction success rate (0.0–1.0) for Tier-2 survivors."""
        attempts = self.extraction_stats.get("attempts", 0)
        if attempts == 0:
            return {f: 0.0 for f in _EXTRACTION_FIELDS}
        return {
            f: round(self.extraction_stats.get(f, 0) / attempts, 4)
            for f in _EXTRACTION_FIELDS
        }

    def rejection_breakdown(self) -> dict:
        """Returns a dict of all rejection counters for reporting."""
        return {
            "rejected_total": self.rejected_count,
            "no_name": self.no_name_count,
            "no_phone": self.no_phone_count,
            "permanently_closed": self.permanently_closed_count,
            "wrong_status": self.wrong_status_count,
            "wrong_category": self.wrong_category_count,
            "wrong_city": self.wrong_city_count,
            "has_website": self.has_website_count,
            "below_min_rating": self.below_min_rating_count,
            "below_min_reviews": self.below_min_reviews_count,
            "wrong_area": self.wrong_area_count,
            "low_confidence": self.low_confidence_count,
            "category_unverified": self.category_unverified_count,
            "no_address": self.no_address_count,
            "ghost_listing": self.ghost_listing_count,
            "duplicates": self.duplicate_count,
            "tier1": dict(self.tier1_rejections),
        }

    # ── Runtime metrics ─────────────────────────────────────────────────────────

    def elapsed(self) -> float:
        """Seconds since campaign start (monotonic)."""
        return time.monotonic() - self._campaign_start

    def qualification_yield(self) -> float:
        """Fraction of visited businesses that qualified (0.0–1.0)."""
        if self.budget_consumed == 0:
            return 0.0
        return self.qualified_count / self.budget_consumed

    def avg_seconds_per_business(self) -> float:
        """Average elapsed time per business visited."""
        if self.budget_consumed == 0:
            return 0.0
        return self.elapsed() / self.budget_consumed

    def avg_seconds_per_qualified_lead(self) -> float:
        """Average elapsed time per qualified lead produced."""
        if self.qualified_count == 0:
            return 0.0
        return self.elapsed() / self.qualified_count

    def estimated_remaining_visits(self) -> int:
        """Estimated businesses still needed to reach the requested limit."""
        remaining = max(0, self.limit - self.qualified_count)
        if remaining == 0:
            return 0
        y = self.qualification_yield()
        if y <= 0:
            return remaining * 4  # fallback: assume 25% yield
        return max(0, int(remaining / y) + 5)  # +5 safety margin

    def estimated_remaining_sec(self) -> float:
        """Estimated remaining campaign time in seconds."""
        spb = self.avg_seconds_per_business()
        if spb <= 0:
            return 0.0
        return self.estimated_remaining_visits() * spb

    def update_adaptive_budget(self) -> bool:
        """Reduce search_budget when live yield is better than initially assumed.

        Called every _YIELD_SAMPLE_INTERVAL visits. Returns True if the budget
        was tightened (wasted-work reduction active).
        """
        if self.budget_consumed < _YIELD_SAMPLE_INTERVAL:
            return False
        y = self.qualification_yield()
        if y <= 0:
            return False
        remaining = max(0, self.limit - self.qualified_count)
        estimated_remaining = int(remaining / y) + 5  # +5 safety margin
        new_budget = self.budget_consumed + estimated_remaining
        if new_budget < self.search_budget:
            self.search_budget = new_budget
            return True
        return False

    def to_metrics(self) -> Dict[str, Any]:
        """Snapshot of live campaign metrics suitable for API serialisation."""
        return {
            "qualified": self.qualified_count,
            "requested": self.limit,
            "visited": self.budget_consumed + sum(self.tier1_rejections.values()),
            "rejected": self.rejected_count,
            "duplicates": self.duplicate_count,
            "yield_rate": round(self.qualification_yield(), 4),
            "avg_seconds_per_business": round(self.avg_seconds_per_business(), 2),
            "avg_seconds_per_qualified_lead": round(
                self.avg_seconds_per_qualified_lead(), 2
            ),
            "estimated_remaining_visits": self.estimated_remaining_visits(),
            "estimated_remaining_sec": round(self.estimated_remaining_sec(), 1),
            "elapsed_sec": round(self.elapsed(), 1),
            "adaptive_budget": self.search_budget,
            "initial_budget": self._initial_budget,
            "active_termination_condition": self.termination_reason or "IN_PROGRESS",
            "tier1_rejections": dict(self.tier1_rejections),
            "extraction_rates": self.extraction_rates(),
            "avg_confidence": round(self.avg_confidence(), 4),
        }
