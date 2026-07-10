"""Phase 5 Campaign Intelligence — unit and integration tests.

Verifies:
  - PlanMetrics dataclass fields and derived values
  - CampaignIntelligence producer-side API (discovery counters, timing, url_plan_map)
  - CampaignIntelligence consumer-side API (attribution, outcome recording)
  - finalize() produces deterministic, correctly ordered PlanMetrics list
  - Reconciliation: per-plan sums match campaign-level totals
  - Unattributed URLs (source_url not in map) return plan_idx = -1
  - record_rejection routes correctly to website / phone / validation_failures
  - Multiple plans have independent accumulators
  - Derived metrics: yield_percentage and duplicate_percentage
  - Silent no-op for unknown plan_idx values
  - Control plane wiring: CampaignIntelligence is instantiated and called
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from leadforge.campaign_intelligence import CampaignIntelligence, PlanMetrics
from leadforge.sil.search_plan_generator import SearchPlan


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_plan(idx: int, query: str = "", category: str = "Widget",
               partition: str = "City") -> SearchPlan:
    q = query or f"{category} in {partition}"
    return SearchPlan(
        search_query=q,
        canonical_category=category,
        geographic_partition=partition,
        original_city="City",
        priority_score=float(10 - idx),
        execution_order=idx + 1,
    )


def _ci(n: int = 2) -> CampaignIntelligence:
    plans = [_make_plan(i) for i in range(n)]
    return CampaignIntelligence(plans)


# ─────────────────────────────────────────────────────────────────────────────
# PlanMetrics dataclass
# ─────────────────────────────────────────────────────────────────────────────


class TestPlanMetrics:
    def test_frozen(self):
        pm = PlanMetrics(
            plan_idx=0, search_query="X in Y", canonical_category="X",
            geographic_partition="Y", urls_discovered=5,
            discovery_duplicates=1, discovery_duration_s=2.0,
            urls_processed=4, qualified=2, consumer_duplicates=0,
            website_rejections=1, phone_rejections=0, validation_failures=1,
            processing_duration_s=3.0, yield_percentage=50.0,
            duplicate_percentage=20.0,
        )
        with pytest.raises((AttributeError, TypeError)):
            pm.qualified = 99  # type: ignore[misc]

    def test_to_dict_keys(self):
        pm = PlanMetrics(
            plan_idx=0, search_query="X in Y", canonical_category="X",
            geographic_partition="Y", urls_discovered=0,
            discovery_duplicates=0, discovery_duration_s=0.0,
            urls_processed=0, qualified=0, consumer_duplicates=0,
            website_rejections=0, phone_rejections=0, validation_failures=0,
            processing_duration_s=0.0, yield_percentage=0.0,
            duplicate_percentage=0.0,
        )
        d = pm.to_dict()
        for key in ("plan_idx", "search_query", "canonical_category",
                    "geographic_partition", "urls_discovered",
                    "discovery_duplicates", "discovery_duration_s",
                    "urls_processed", "qualified", "consumer_duplicates",
                    "website_rejections", "phone_rejections",
                    "validation_failures", "processing_duration_s",
                    "yield_percentage", "duplicate_percentage"):
            assert key in d


# ─────────────────────────────────────────────────────────────────────────────
# CampaignIntelligence — initialisation
# ─────────────────────────────────────────────────────────────────────────────


class TestCampaignIntelligenceInit:
    def test_url_plan_map_starts_empty(self):
        ci = _ci(3)
        assert ci.url_plan_map == {}

    def test_accumulators_created_for_all_plans(self):
        ci = _ci(4)
        assert len(ci._accumulators) == 4

    def test_empty_plan_list(self):
        ci = CampaignIntelligence([])
        assert ci.finalize() == []


# ─────────────────────────────────────────────────────────────────────────────
# Producer-side API
# ─────────────────────────────────────────────────────────────────────────────


class TestProducerAPI:
    def test_record_url_discovered_increments_counter(self):
        ci = _ci()
        ci.record_url_discovered(0)
        ci.record_url_discovered(0)
        ci.record_url_discovered(1)
        assert ci._accumulators[0].urls_discovered == 2
        assert ci._accumulators[1].urls_discovered == 1

    def test_record_discovery_duplicate_increments_counter(self):
        ci = _ci()
        ci.record_discovery_duplicate(0)
        ci.record_discovery_duplicate(0)
        assert ci._accumulators[0].discovery_duplicates == 2

    def test_url_plan_map_written_by_producer(self):
        ci = _ci()
        url = "https://maps.google.com/?cid=123"
        ci.url_plan_map[url] = 0
        assert ci.attribute(url) == 0

    def test_discovery_timing_recorded(self):
        ci = _ci()
        ci.mark_discovery_start(0)
        time.sleep(0.01)
        ci.mark_discovery_end(0)
        assert ci._accumulators[0].discovery_duration_s > 0.005

    def test_unknown_plan_idx_is_noop(self):
        ci = _ci(2)
        # Should not raise for out-of-range plan_idx
        ci.record_url_discovered(99)
        ci.record_discovery_duplicate(99)
        ci.mark_discovery_start(99)
        ci.mark_discovery_end(99)


# ─────────────────────────────────────────────────────────────────────────────
# Consumer-side API
# ─────────────────────────────────────────────────────────────────────────────


class TestConsumerAPI:
    def test_attribute_known_url_returns_plan_idx(self):
        ci = _ci()
        ci.url_plan_map["https://maps.google.com/?cid=42"] = 1
        assert ci.attribute("https://maps.google.com/?cid=42") == 1

    def test_attribute_unknown_url_returns_minus_one(self):
        ci = _ci()
        assert ci.attribute("https://unknown.example.com/") == -1

    def test_record_processed_increments_counter(self):
        ci = _ci()
        ci.record_processed(0)
        ci.record_processed(0)
        ci.record_processed(1)
        assert ci._accumulators[0].urls_processed == 2
        assert ci._accumulators[1].urls_processed == 1

    def test_record_qualified_increments_counter(self):
        ci = _ci()
        ci.record_qualified(0)
        assert ci._accumulators[0].qualified == 1

    def test_record_consumer_duplicate(self):
        ci = _ci()
        ci.record_consumer_duplicate(0)
        ci.record_consumer_duplicate(0)
        assert ci._accumulators[0].consumer_duplicates == 2

    def test_record_rejection_has_website_routes_to_website_counter(self):
        ci = _ci()
        ci.record_rejection(0, "HAS_WEBSITE")
        assert ci._accumulators[0].website_rejections == 1
        assert ci._accumulators[0].phone_rejections == 0
        assert ci._accumulators[0].validation_failures == 0

    def test_record_rejection_no_phone_routes_to_phone_counter(self):
        ci = _ci()
        ci.record_rejection(0, "NO_PHONE")
        assert ci._accumulators[0].phone_rejections == 1
        assert ci._accumulators[0].website_rejections == 0
        assert ci._accumulators[0].validation_failures == 0

    def test_record_rejection_other_routes_to_validation_failures(self):
        ci = _ci()
        for reason in ("WRONG_CATEGORY", "WRONG_CITY", "LOW_CONFIDENCE",
                       "BELOW_MIN_RATING", "GHOST_LISTING"):
            ci.record_rejection(0, reason)
        assert ci._accumulators[0].validation_failures == 5
        assert ci._accumulators[0].website_rejections == 0
        assert ci._accumulators[0].phone_rejections == 0

    def test_unknown_plan_idx_consumer_is_noop(self):
        ci = _ci(2)
        ci.record_processed(99)
        ci.record_qualified(99)
        ci.record_consumer_duplicate(99)
        ci.record_rejection(99, "HAS_WEBSITE")


# ─────────────────────────────────────────────────────────────────────────────
# finalize()
# ─────────────────────────────────────────────────────────────────────────────


class TestFinalize:
    def test_returns_one_record_per_plan(self):
        ci = _ci(3)
        metrics = ci.finalize()
        assert len(metrics) == 3

    def test_ordered_by_plan_idx(self):
        ci = _ci(3)
        metrics = ci.finalize()
        assert [m.plan_idx for m in metrics] == [0, 1, 2]

    def test_plan_identity_fields(self):
        plans = [_make_plan(0, category="Dentist", partition="Ahmedabad")]
        ci = CampaignIntelligence(plans)
        m = ci.finalize()[0]
        assert m.search_query == "Dentist in Ahmedabad"
        assert m.canonical_category == "Dentist"
        assert m.geographic_partition == "Ahmedabad"

    def test_finalize_is_idempotent(self):
        ci = _ci(2)
        ci.record_url_discovered(0)
        r1 = ci.finalize()
        r2 = ci.finalize()
        assert r1 == r2

    def test_all_counters_zero_when_no_activity(self):
        ci = _ci(2)
        for m in ci.finalize():
            assert m.urls_discovered == 0
            assert m.qualified == 0
            assert m.yield_percentage == 0.0
            assert m.duplicate_percentage == 0.0

    def test_returns_plandmetrics_instances(self):
        ci = _ci()
        for m in ci.finalize():
            assert isinstance(m, PlanMetrics)


# ─────────────────────────────────────────────────────────────────────────────
# Derived metrics
# ─────────────────────────────────────────────────────────────────────────────


class TestDerivedMetrics:
    def _populate(self, ci: CampaignIntelligence, plan_idx: int, *,
                  discovered: int, disc_dups: int, processed: int,
                  qualified: int, consumer_dups: int) -> None:
        for _ in range(discovered):
            ci.record_url_discovered(plan_idx)
        for _ in range(disc_dups):
            ci.record_discovery_duplicate(plan_idx)
        for _ in range(processed):
            ci.record_processed(plan_idx)
        for _ in range(qualified):
            ci.record_qualified(plan_idx)
        for _ in range(consumer_dups):
            ci.record_consumer_duplicate(plan_idx)

    def test_yield_percentage_computed_correctly(self):
        ci = _ci()
        self._populate(ci, 0, discovered=10, disc_dups=0,
                       processed=8, qualified=4, consumer_dups=0)
        m = ci.finalize()[0]
        assert m.yield_percentage == pytest.approx(50.0, abs=0.01)

    def test_duplicate_percentage_includes_both_sources(self):
        ci = _ci()
        # 10 discovered: 2 pre-filter dups, 8 queued → 1 consumer dup
        self._populate(ci, 0, discovered=10, disc_dups=2,
                       processed=7, qualified=3, consumer_dups=1)
        m = ci.finalize()[0]
        # (2 + 1) / 10 = 30%
        assert m.duplicate_percentage == pytest.approx(30.0, abs=0.01)

    def test_yield_percentage_zero_when_no_processing(self):
        ci = _ci()
        ci.record_url_discovered(0)
        m = ci.finalize()[0]
        assert m.yield_percentage == 0.0

    def test_duplicate_percentage_zero_when_no_discovery(self):
        ci = _ci()
        m = ci.finalize()[0]
        assert m.duplicate_percentage == 0.0

    def test_100_percent_yield(self):
        ci = _ci()
        ci.record_processed(0)
        ci.record_qualified(0)
        m = ci.finalize()[0]
        assert m.yield_percentage == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation: plan sums must match campaign totals
# ─────────────────────────────────────────────────────────────────────────────


class TestReconciliation:
    def _run_scenario(self) -> tuple[CampaignIntelligence, dict]:
        """Simulate a 3-plan campaign and return CI + expected campaign totals."""
        ci = _ci(3)

        # Plan 0: 5 discovered (1 disc dup), 4 queued → 3 processed
        #   → 1 qualified, 1 consumer dup, 1 HAS_WEBSITE rejection
        ci.record_url_discovered(0)
        ci.record_url_discovered(0)
        ci.record_url_discovered(0)
        ci.record_url_discovered(0)
        ci.record_url_discovered(0)
        ci.record_discovery_duplicate(0)
        for _ in range(3):
            ci.record_processed(0)
        ci.record_qualified(0)
        ci.record_consumer_duplicate(0)
        ci.record_rejection(0, "HAS_WEBSITE")

        # Plan 1: 3 discovered, 3 queued → 3 processed → 2 qualified, 1 NO_PHONE
        ci.record_url_discovered(1)
        ci.record_url_discovered(1)
        ci.record_url_discovered(1)
        for _ in range(3):
            ci.record_processed(1)
        ci.record_qualified(1)
        ci.record_qualified(1)
        ci.record_rejection(1, "NO_PHONE")

        # Plan 2: 2 discovered, 2 queued → 2 processed → 1 qualified, 1 LOW_CONFIDENCE
        ci.record_url_discovered(2)
        ci.record_url_discovered(2)
        for _ in range(2):
            ci.record_processed(2)
        ci.record_qualified(2)
        ci.record_rejection(2, "LOW_CONFIDENCE")

        totals = {
            "urls_discovered": 10,   # 5+3+2
            "discovery_duplicates": 1,
            "urls_processed": 8,     # 3+3+2
            "qualified": 4,          # 1+2+1
            "consumer_duplicates": 1,
            "website_rejections": 1,
            "phone_rejections": 1,
            "validation_failures": 1,  # LOW_CONFIDENCE
        }
        return ci, totals

    def test_sum_urls_discovered(self):
        ci, totals = self._run_scenario()
        assert sum(m.urls_discovered for m in ci.finalize()) == totals["urls_discovered"]

    def test_sum_discovery_duplicates(self):
        ci, totals = self._run_scenario()
        assert sum(m.discovery_duplicates for m in ci.finalize()) == totals["discovery_duplicates"]

    def test_sum_urls_processed(self):
        ci, totals = self._run_scenario()
        assert sum(m.urls_processed for m in ci.finalize()) == totals["urls_processed"]

    def test_sum_qualified(self):
        ci, totals = self._run_scenario()
        assert sum(m.qualified for m in ci.finalize()) == totals["qualified"]

    def test_sum_consumer_duplicates(self):
        ci, totals = self._run_scenario()
        assert sum(m.consumer_duplicates for m in ci.finalize()) == totals["consumer_duplicates"]

    def test_sum_website_rejections(self):
        ci, totals = self._run_scenario()
        assert sum(m.website_rejections for m in ci.finalize()) == totals["website_rejections"]

    def test_sum_phone_rejections(self):
        ci, totals = self._run_scenario()
        assert sum(m.phone_rejections for m in ci.finalize()) == totals["phone_rejections"]

    def test_sum_validation_failures(self):
        ci, totals = self._run_scenario()
        assert sum(m.validation_failures for m in ci.finalize()) == totals["validation_failures"]

    def test_total_rejections_equals_campaign_rejected_count(self):
        # Campaign-level: rejected_count = website + phone + other (no LOW_CONFIDENCE split)
        ci, totals = self._run_scenario()
        metrics = ci.finalize()
        total_rejections = sum(
            m.website_rejections + m.phone_rejections + m.validation_failures
            for m in metrics
        )
        expected_rejected = (
            totals["website_rejections"]
            + totals["phone_rejections"]
            + totals["validation_failures"]
        )
        assert total_rejections == expected_rejected


# ─────────────────────────────────────────────────────────────────────────────
# Per-plan independence
# ─────────────────────────────────────────────────────────────────────────────


class TestPlanIndependence:
    def test_plan0_metrics_do_not_affect_plan1(self):
        ci = _ci(2)
        ci.record_url_discovered(0)
        ci.record_qualified(0)
        m = ci.finalize()
        assert m[0].urls_discovered == 1
        assert m[1].urls_discovered == 0
        assert m[0].qualified == 1
        assert m[1].qualified == 0

    def test_url_attribution_routes_correctly(self):
        ci = _ci(3)
        ci.url_plan_map["https://example.com/a"] = 0
        ci.url_plan_map["https://example.com/b"] = 2
        assert ci.attribute("https://example.com/a") == 0
        assert ci.attribute("https://example.com/b") == 2
        assert ci.attribute("https://example.com/c") == -1


# ─────────────────────────────────────────────────────────────────────────────
# Control-plane wiring smoke test
# ─────────────────────────────────────────────────────────────────────────────


class TestControlPlaneWiring:
    """Verify CampaignIntelligence is imported and instantiated by the module."""

    def test_campaign_intelligence_importable_from_control_plane(self):
        import leadforge.control_plane as cp  # noqa: F401
        from leadforge.campaign_intelligence import CampaignIntelligence  # noqa: F401

    def test_campaign_intelligence_used_in_run_qualified_campaign(self):
        import inspect
        import leadforge.control_plane as cp
        src = inspect.getsource(cp.SearchOrchestrator.run_qualified_campaign)
        assert "CampaignIntelligence" in src
        assert "ci.finalize()" in src
        assert "ci.save(" in src
        assert "ci.attribute(" in src
        assert "ci.record_processed(" in src
        assert "ci.record_qualified(" in src
        assert "ci.record_consumer_duplicate(" in src
        assert "ci.record_rejection(" in src

    def test_producer_wired_with_discovery_instrumentation(self):
        import inspect
        import leadforge.control_plane as cp
        src = inspect.getsource(cp.SearchOrchestrator.run_qualified_campaign)
        assert "ci.record_url_discovered(" in src
        assert "ci.record_discovery_duplicate(" in src
        assert "ci.mark_discovery_start(" in src
        assert "ci.mark_discovery_end(" in src
        assert "ci.url_plan_map[url]" in src


# ─────────────────────────────────────────────────────────────────────────────
# save() — DB persistence (mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestSave:
    def test_save_none_search_id_is_noop(self):
        ci = _ci()
        ci.record_url_discovered(0)
        # Should not raise even if DB is not initialised
        ci.save(None)

    def test_save_calls_executemany_with_correct_row_count(self):
        # save() uses lazy `from leadforge.database import ...` inside the method;
        # patch the source module attributes so the import picks up the mock.
        ci = _ci(3)
        mock_conn = MagicMock()
        with patch("leadforge.database.get_db_connection", return_value=mock_conn):
            with patch("leadforge.database.uuidv7",
                       side_effect=[f"uuid-{i}" for i in range(10)]):
                ci.save("search-001")
        mock_conn.executemany.assert_called_once()
        rows = mock_conn.executemany.call_args[0][1]
        assert len(rows) == 3  # one row per plan

    def test_save_row_contains_search_id(self):
        ci = _ci(2)
        mock_conn = MagicMock()
        with patch("leadforge.database.get_db_connection", return_value=mock_conn):
            with patch("leadforge.database.uuidv7",
                       side_effect=[f"uuid-{i}" for i in range(10)]):
                ci.save("my-search-id")
        rows = mock_conn.executemany.call_args[0][1]
        assert all(row[1] == "my-search-id" for row in rows)

    def test_save_commits_and_closes(self):
        ci = _ci()
        mock_conn = MagicMock()
        with patch("leadforge.database.get_db_connection", return_value=mock_conn):
            with patch("leadforge.database.uuidv7", return_value="u"):
                ci.save("sid")
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()
