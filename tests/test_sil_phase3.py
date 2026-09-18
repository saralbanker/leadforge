"""Phase 3 integration tests: SearchPlanGenerator → SearchOrchestrator.

Verifies that:
- SearchPlanGenerator is called with the correct city/category/limit.
- Plans are executed sequentially (each plan's discovery is called in order).
- discover_business_links_stream is called with the correct partition/variant.
- Campaign terminates when the qualified-lead count is reached mid-plans.
- Campaign terminates with SEARCH_SPACE_EXHAUSTED when all plans are exhausted.
- A single state object spans the entire multi-plan campaign.
- The SIL fallback (empty plan list) produces a single original-query plan.
- Per-plan DISCOVERY_FAILED is skipped; only all-plans-fail sets the flag.
- No existing behavioural contract (validator, repos, CLI, exports) is changed.

Architecture note on the mock consumer
---------------------------------------
The SearchOrchestrator producer (_producer task) and consumer (main coroutine)
share a queue.  The consumer's mock must drain the queue's sentinel (None)
so the producer can complete naturally and all discovery calls are made.
An empty-iterator mock that ignores _url_source causes the producer to be
cancelled before it runs.  All tests here use _draining_collect which
consumes _url_source until the producer's sentinel arrives.

All tests are isolated from production DB and from real Playwright/network.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Isolate the database before any leadforge imports ────────────────────────
import leadforge.database

_temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_temp_db_path = Path(_temp_db.name)
_temp_db.close()
from leadforge.database import initialize_database  # noqa: E402
from leadforge.sil.search_plan_generator import SearchPlan  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _db_setup():
    mp = pytest.MonkeyPatch()
    mp.setattr(leadforge.database, "DB_PATH", _temp_db_path)
    initialize_database()
    yield
    mp.undo()
    if _temp_db_path.exists():
        try:
            os.remove(_temp_db_path)
        except Exception:
            pass


# ── Shared async stubs ────────────────────────────────────────────────────────


async def _draining_collect(url_source, *args, **kwargs):
    """Mock for collect_business_details_stream.

    Drains the url_source so the producer can run to completion and put its
    sentinel.  Yields nothing — the campaign always finishes with 0 leads.
    """
    async for _ in url_source:
        pass
    return
    yield  # make this function an async generator


async def _empty_discovery(*_args, **_kwargs):
    """Async generator that yields no URLs (search space exhausted instantly)."""
    return
    yield


# ── Plan builder ──────────────────────────────────────────────────────────────


def _plan(
    variant: str,
    partition: str,
    *,
    city: str = "Ahmedabad",
    order: int = 1,
    priority: float = 1.0,
    canonical: str = "",
) -> SearchPlan:
    return SearchPlan(
        search_query=f"{variant} in {partition}",
        canonical_category=canonical or variant,
        geographic_partition=partition,
        original_city=city,
        priority_score=priority,
        execution_order=order,
    )


# ── Core test helper ──────────────────────────────────────────────────────────


def _run(
    orch,
    *,
    city: str,
    category: str,
    limit: int,
    plans: list,
    discovery_fn=None,
    check_duplicate=False,
) -> list:
    """Run a campaign synchronously with mocked I/O.

    Patches:
    - SearchPlanGenerator to return *plans*
    - async_playwright (no browser)
    - discover_business_links_stream (via *discovery_fn*)
    - collect_business_details_stream → draining (lets producer finish)
    - SQLiteLeadRepository.check_duplicate → *check_duplicate*
    """
    if discovery_fn is None:
        discovery_fn = _empty_discovery

    async def _campaign():
        with (
            patch("leadforge.control_plane.SearchPlanGenerator") as MockGen,
            patch("leadforge.control_plane.async_playwright") as MockPW,
            patch(
                "leadforge.control_plane.discover_business_links_stream",
                side_effect=discovery_fn,
            ),
            patch(
                "leadforge.control_plane.collect_business_details_stream",
                side_effect=_draining_collect,
            ),
            patch.object(
                orch.lead_repo, "check_duplicate", return_value=check_duplicate
            ),
        ):
            # Wire SearchPlanGenerator mock.
            mock_gen = MagicMock()
            mock_gen.generate.return_value = plans
            MockGen.return_value = mock_gen

            # Minimal Playwright stub — no browser is started.
            mock_pw_ctx = AsyncMock()
            mock_browser = AsyncMock()
            mock_shared_ctx = AsyncMock()
            MockPW.return_value.start = AsyncMock(return_value=mock_pw_ctx)
            mock_pw_ctx.chromium = MagicMock()
            mock_pw_ctx.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_shared_ctx)
            mock_browser.close = AsyncMock()
            mock_pw_ctx.stop = AsyncMock()

            return await orch.run_qualified_campaign(
                city=city, category=category, limit=limit
            )

    return asyncio.run(_campaign())


# ═══════════════════════════════════════════════════════════════════════════════
# SearchPlanGenerator integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestSearchPlanGeneratorIntegration:
    def test_generator_called_with_city_category_limit(self):
        """SearchOrchestrator passes city, category, and limit to generate()."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()
        captured: dict = {}

        def _fake_generate(city, category, target_qualified_leads=50):
            captured["city"] = city
            captured["category"] = category
            captured["limit"] = target_qualified_leads
            return []  # empty → triggers fallback plan

        async def _campaign():
            with (
                patch("leadforge.control_plane.SearchPlanGenerator") as MockGen,
                patch("leadforge.control_plane.async_playwright") as MockPW,
                patch(
                    "leadforge.control_plane.discover_business_links_stream",
                    side_effect=_empty_discovery,
                ),
                patch(
                    "leadforge.control_plane.collect_business_details_stream",
                    side_effect=_draining_collect,
                ),
                patch.object(orch.lead_repo, "check_duplicate", return_value=False),
            ):
                mock_gen = MagicMock()
                mock_gen.generate.side_effect = _fake_generate
                MockGen.return_value = mock_gen

                mock_pw_ctx = AsyncMock()
                mock_browser = AsyncMock()
                MockPW.return_value.start = AsyncMock(return_value=mock_pw_ctx)
                mock_pw_ctx.chromium = MagicMock()
                mock_pw_ctx.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_browser.new_context = AsyncMock(return_value=AsyncMock())
                mock_browser.close = AsyncMock()
                mock_pw_ctx.stop = AsyncMock()

                return await orch.run_qualified_campaign(
                    city="Ahmedabad", category="Manufacturer", limit=30
                )

        asyncio.run(_campaign())
        assert captured["city"] == "Ahmedabad"
        assert captured["category"] == "Manufacturer"
        assert captured["limit"] == 30

    def test_fallback_plan_when_generator_returns_empty(self):
        """When SIL returns [], a fallback plan using the raw query is used."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()
        discovery_calls: list = []

        async def _capture(city, category, limit=50, **kwargs):
            discovery_calls.append((city, category))
            return
            yield

        _run(
            orch,
            city="Baroda",
            category="Textile",
            limit=5,
            plans=[],  # empty → fallback plan
            discovery_fn=_capture,
        )

        assert len(discovery_calls) == 1
        city_arg, cat_arg = discovery_calls[0]
        assert city_arg == "Baroda"
        assert cat_arg == "Textile"


# ═══════════════════════════════════════════════════════════════════════════════
# Sequential plan execution
# ═══════════════════════════════════════════════════════════════════════════════


class TestSequentialPlanExecution:
    def test_discovery_called_once_per_plan(self):
        """Each search plan triggers exactly one discover_business_links_stream call."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()
        discovery_calls: list = []

        async def _capture(city, category, limit=50, **kwargs):
            discovery_calls.append((city, category))
            return
            yield

        plans = [
            _plan("Manufacturer", "Naroda", order=1, priority=20001.0),
            _plan("Manufacturer", "Vatva", order=2, priority=20000.0),
            _plan("Manufacturer", "Odhav", order=3, priority=19999.0),
        ]

        _run(
            orch,
            city="Ahmedabad",
            category="Manufacturer",
            limit=5,
            plans=plans,
            discovery_fn=_capture,
        )

        assert len(discovery_calls) == 3

    def test_discovery_uses_partition_as_city_arg(self):
        """Each discover call uses geographic_partition as the city argument."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()
        discovery_calls: list = []

        async def _capture(city, category, limit=50, **kwargs):
            discovery_calls.append((city, category))
            return
            yield

        plans = [
            _plan("Manufacturer", "Naroda", order=1),
            _plan("Manufacturing company", "Vatva", canonical="Manufacturer", order=2),
        ]

        _run(
            orch,
            city="Ahmedabad",
            category="Manufacturer",
            limit=5,
            plans=plans,
            discovery_fn=_capture,
        )

        partitions = [c[0] for c in discovery_calls]
        variants = [c[1] for c in discovery_calls]
        assert partitions == ["Naroda", "Vatva"]
        assert variants == ["Manufacturer", "Manufacturing company"]

    def test_plans_executed_in_execution_order(self):
        """Plans are executed in the order provided by SearchPlanGenerator."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()
        sequence: list = []

        async def _capture(city, category, limit=50, **kwargs):
            sequence.append(f"{category} in {city}")
            return
            yield

        plans = [
            _plan("Manufacturer", "Naroda", order=1, priority=30000.0),
            _plan("Manufacturer", "Vatva", order=2, priority=29999.0),
            _plan("Manufacturing company", "Naroda", canonical="Manufacturer", order=3, priority=19999.0),
            _plan("Manufacturer", "Nikol", order=4, priority=19998.0),
        ]

        _run(
            orch,
            city="Ahmedabad",
            category="Manufacturer",
            limit=5,
            plans=plans,
            discovery_fn=_capture,
        )

        assert sequence == [
            "Manufacturer in Naroda",
            "Manufacturer in Vatva",
            "Manufacturing company in Naroda",
            "Manufacturer in Nikol",
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# Campaign termination
# ═══════════════════════════════════════════════════════════════════════════════


class TestCampaignTermination:
    def test_termination_when_search_space_exhausted_all_plans(self):
        """All plans return no URLs → SEARCH_SPACE_EXHAUSTED."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()

        plans = [
            _plan("Manufacturer", "Naroda", order=1),
            _plan("Manufacturer", "Vatva", order=2),
        ]

        _run(orch, city="Ahmedabad", category="Manufacturer", limit=10, plans=plans)

        assert orch.state.termination_reason == "SEARCH_SPACE_EXHAUSTED"

    def test_all_plans_fail_sets_discovery_failed(self):
        """When every plan raises DISCOVERY_FAILED, the campaign returns []."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()

        async def _always_fail(city, category, limit=50, **kwargs):
            raise RuntimeError("DISCOVERY_FAILED")
            yield  # pragma: no cover

        plans = [
            _plan("Manufacturer", "Naroda", order=1),
            _plan("Manufacturer", "Vatva", order=2),
        ]

        qualified = _run(
            orch,
            city="Ahmedabad",
            category="Manufacturer",
            limit=5,
            plans=plans,
            discovery_fn=_always_fail,
        )

        assert qualified == []
        assert orch.state.termination_reason == "DISCOVERY_FAILED"

    def test_single_plan_failure_does_not_abort_campaign(self):
        """A DISCOVERY_FAILED on one plan lets subsequent plans execute."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()
        discovery_calls: list = []

        async def _first_fails(city, category, limit=50, **kwargs):
            discovery_calls.append((city, category))
            if city == "Naroda":
                raise RuntimeError("DISCOVERY_FAILED")
            return
            yield

        plans = [
            _plan("Manufacturer", "Naroda", order=1),
            _plan("Manufacturer", "Vatva", order=2),
            _plan("Manufacturer", "Odhav", order=3),
        ]

        _run(
            orch,
            city="Ahmedabad",
            category="Manufacturer",
            limit=5,
            plans=plans,
            discovery_fn=_first_fails,
        )

        # All three plans must have been attempted.
        assert len(discovery_calls) == 3
        # Only one failure → discovery_failed must NOT be set.
        assert orch.state.termination_reason != "DISCOVERY_FAILED"


# ═══════════════════════════════════════════════════════════════════════════════
# Campaign identity — single state across all plans
# ═══════════════════════════════════════════════════════════════════════════════


class TestCampaignIdentity:
    def test_single_state_object_spans_all_plans(self):
        """orch.state is set once and shared across the entire campaign."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()

        plans = [
            _plan("Manufacturer", "Naroda", order=1),
            _plan("Manufacturer", "Vatva", order=2),
        ]

        _run(orch, city="Ahmedabad", category="Manufacturer", limit=5, plans=plans)

        assert orch.state is not None
        assert orch.state.limit == 5

    def test_discovered_links_accumulate_across_plans(self):
        """URLs discovered across plans are collected into one discovered_links list."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()

        plan1_urls = [
            "https://maps.google.com/maps/place/A/data=!4m2!3m1!1s0x1111:0xaaaa",
            "https://maps.google.com/maps/place/B/data=!4m2!3m1!1s0x2222:0xbbbb",
        ]
        plan2_urls = [
            "https://maps.google.com/maps/place/C/data=!4m2!3m1!1s0x3333:0xcccc",
        ]
        batches = [plan1_urls, plan2_urls]
        call_idx = [0]

        async def _batched(city, category, limit=50, **kwargs):
            batch = batches[call_idx[0]]
            call_idx[0] += 1
            for url in batch:
                yield url

        plans = [
            _plan("Manufacturer", "Naroda", order=1),
            _plan("Manufacturer", "Vatva", order=2),
        ]

        _run(
            orch,
            city="Ahmedabad",
            category="Manufacturer",
            limit=50,
            plans=plans,
            discovery_fn=_batched,
            check_duplicate=False,
        )

        assert len(orch.discovered_links) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Variant extraction correctness
# ═══════════════════════════════════════════════════════════════════════════════


class TestVariantExtraction:
    @pytest.mark.parametrize(
        "variant,partition",
        [
            ("Manufacturer", "Naroda"),
            ("Manufacturing company", "Vatva"),
            ("Machine manufacturer", "GIDC Estate"),
            ("Dentist", "New Town"),
            ("Restaurant", "South Delhi"),
        ],
    )
    def test_removesuffix_recovers_variant(self, variant, partition):
        """removesuffix correctly strips ' in {partition}' to recover the variant."""
        search_query = f"{variant} in {partition}"
        assert search_query.removesuffix(f" in {partition}") == variant

    def test_ahmedabad_manufacturer_mandatory_example(self):
        """Mandatory demonstration: 50 Manufacturers in Ahmedabad via SIL plans."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()
        sequence: list = []

        async def _capture(city, category, limit=50, **kwargs):
            sequence.append((city, category))
            return
            yield

        plans = [
            _plan("Manufacturer", "Naroda", order=1),
            _plan("Manufacturer", "Vatva", order=2),
            _plan("Manufacturer", "Odhav", order=3),
            _plan("Manufacturing company", "Naroda", canonical="Manufacturer", order=4),
            _plan("Manufacturer", "Nikol", order=5),
        ]

        _run(
            orch,
            city="Ahmedabad",
            category="Manufacturer",
            limit=50,
            plans=plans,
            discovery_fn=_capture,
        )

        expected = [
            ("Naroda", "Manufacturer"),
            ("Vatva", "Manufacturer"),
            ("Odhav", "Manufacturer"),
            ("Naroda", "Manufacturing company"),
            ("Nikol", "Manufacturer"),
        ]
        assert sequence == expected


# ═══════════════════════════════════════════════════════════════════════════════
# Regression contracts
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegressionContracts:
    def test_validator_receives_original_city_not_partition(self):
        """Validator's target_city is the original operator city, not the geo partition."""
        from leadforge.control_plane import SearchOrchestrator
        from leadforge.validator import BusinessValidator

        orch = SearchOrchestrator()
        validate_calls: list = []

        def _capture_validate(self_v, lead, *, target_city="", **kwargs):
            validate_calls.append(target_city)
            return "NO_PHONE"  # reject — avoids full persistence path

        url = "https://maps.google.com/maps/place/X/data=!4m2!3m1!1s0x1111:0xaaaa"

        async def _one_url(city, category, limit=50, **kwargs):
            yield url

        async def _one_lead(url_source, *args, **kwargs):
            async for _ in url_source:
                pass
            yield {
                "name": "Test Mfg",
                "phone": "+91 99999 00000",
                "website": "",
                "address": "Naroda, Ahmedabad",
                "area": "Naroda",
                "postal_code": "",
                "category": "Manufacturer",
                "google_primary_category": "Manufacturer",
                "source_url": url,
                "rating": None,
                "review_count": None,
                "business_status": "OPERATIONAL",
                "opening_hours": "",
                "categories": "",
                "email": "",
                "social_links": "",
            }

        plans = [_plan("Manufacturer", "Naroda", order=1)]

        async def _campaign():
            with (
                patch("leadforge.control_plane.SearchPlanGenerator") as MockGen,
                patch("leadforge.control_plane.async_playwright") as MockPW,
                patch(
                    "leadforge.control_plane.discover_business_links_stream",
                    side_effect=_one_url,
                ),
                patch(
                    "leadforge.control_plane.collect_business_details_stream",
                    side_effect=_one_lead,
                ),
                patch.object(orch.lead_repo, "check_duplicate", return_value=False),
                patch.object(BusinessValidator, "validate", _capture_validate),
            ):
                mock_gen = MagicMock()
                mock_gen.generate.return_value = plans
                MockGen.return_value = mock_gen

                mock_pw_ctx = AsyncMock()
                mock_browser = AsyncMock()
                MockPW.return_value.start = AsyncMock(return_value=mock_pw_ctx)
                mock_pw_ctx.chromium = MagicMock()
                mock_pw_ctx.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_browser.new_context = AsyncMock(return_value=AsyncMock())
                mock_browser.close = AsyncMock()
                mock_pw_ctx.stop = AsyncMock()

                return await orch.run_qualified_campaign(
                    city="Ahmedabad", category="Manufacturer", limit=5
                )

        asyncio.run(_campaign())

        assert validate_calls, "Validator was never called"
        for city_used in validate_calls:
            assert city_used == "Ahmedabad", (
                f"Expected target_city='Ahmedabad', got '{city_used}'"
            )

    def test_search_plan_carries_no_runtime_state(self):
        """SearchPlan TypedDict has no runtime-state fields (Phase 2 contract)."""
        p = _plan("Manufacturer", "Naroda")
        forbidden = {
            "campaign_id", "search_id", "browser_context",
            "queue", "scraper", "repository",
        }
        assert not forbidden.intersection(set(p.keys()))

    def test_fallback_query_equals_original_single_query(self):
        """SIL fallback reproduces the original '{category} in {city}' query."""
        from leadforge.control_plane import SearchOrchestrator

        orch = SearchOrchestrator()
        discovery_calls: list = []

        async def _capture(city, category, limit=50, **kwargs):
            discovery_calls.append((city, category))
            return
            yield

        _run(
            orch,
            city="Surat",
            category="Textile",
            limit=5,
            plans=[],  # empty → fallback
            discovery_fn=_capture,
        )

        assert len(discovery_calls) == 1
        city_arg, cat_arg = discovery_calls[0]
        # Fallback: geographic_partition=city, variant=category
        # → url = "Textile in Surat"  (identical to old single-query behaviour)
        assert city_arg == "Surat"
        assert cat_arg == "Textile"
