"""Phase 2 unit tests: SearchPlanGenerator.

All tests use stub resolvers — no SQLite, no network, no Playwright.

Coverage:
- canonical category resolution (primary variant at index-0)
- secondary category variant resolution
- geographic partition resolution
- Cartesian generation (variants × partitions = correct combinations)
- deterministic priority ordering (primary > secondary > geo order)
- 1-based execution_order numbering
- duplicate search_query elimination (first occurrence wins)
- empty geography fallback → single plan using original city
- empty category fallback → raw category used as canonical
- stable output across repeated executions
- blank city / category inputs → empty result
- SearchPlan schema completeness (all required keys present)
"""

from leadforge.sil.search_plan_generator import (
    SearchPlanGenerator,
    SearchPlan,
    _deduplicate,
)


# ── Stub resolvers ────────────────────────────────────────────────────────────


class _StubCategoryResolver:
    """Returns a fixed list of variants; index-0 is treated as canonical."""

    def __init__(self, variants: list[str]) -> None:
        self._variants = list(variants)

    def get_variants(self, category: str) -> list[str]:
        return list(self._variants)

    def resolve(self, category: str):
        return self._variants[0] if self._variants else None


class _StubGeoResolver:
    """Returns a fixed list of place names."""

    def __init__(self, partitions: list[str]) -> None:
        self._partitions = list(partitions)

    def get_neighbourhoods(self, city: str) -> list[str]:
        return list(self._partitions)


def _make_generator(
    variants: list[str],
    partitions: list[str],
) -> SearchPlanGenerator:
    return SearchPlanGenerator(
        category_resolver=_StubCategoryResolver(variants),
        geo_resolver=_StubGeoResolver(partitions),
    )


# ── Schema ────────────────────────────────────────────────────────────────────

_REQUIRED_KEYS = {
    "search_query",
    "canonical_category",
    "geographic_partition",
    "original_city",
    "priority_score",
    "execution_order",
}


class TestSearchPlanSchema:
    def test_all_required_keys_present(self):
        gen = _make_generator(["Dentist"], ["Navrangpura"])
        plans = gen.generate("Ahmedabad", "Dentist")
        assert plans
        for plan in plans:
            assert _REQUIRED_KEYS == set(plan.keys())

    def test_types_correct(self):
        gen = _make_generator(["Dentist"], ["Navrangpura"])
        plan = gen.generate("Ahmedabad", "Dentist")[0]
        assert isinstance(plan["search_query"], str)
        assert isinstance(plan["canonical_category"], str)
        assert isinstance(plan["geographic_partition"], str)
        assert isinstance(plan["original_city"], str)
        assert isinstance(plan["priority_score"], float)
        assert isinstance(plan["execution_order"], int)

    def test_no_extra_keys(self):
        gen = _make_generator(["Dentist"], ["Navrangpura"])
        plan = gen.generate("Ahmedabad", "Dentist")[0]
        assert set(plan.keys()) == _REQUIRED_KEYS


# ── Category resolution ───────────────────────────────────────────────────────


class TestCategoryResolution:
    def test_canonical_is_primary_variant(self):
        gen = _make_generator(["Manufacturer", "Manufacturing company"], ["Naroda"])
        plans = gen.generate("Ahmedabad", "Manufacturers")
        canonicals = {p["canonical_category"] for p in plans}
        assert canonicals == {"Manufacturer"}

    def test_single_canonical_with_no_variants(self):
        # get_variants returns [] → raw category used as canonical
        gen = _make_generator([], ["Naroda"])
        plans = gen.generate("Ahmedabad", "FooCategory")
        assert len(plans) == 1
        assert plans[0]["canonical_category"] == "FooCategory"
        assert plans[0]["search_query"] == "FooCategory in Naroda"

    def test_secondary_variants_expand_queries(self):
        gen = _make_generator(
            ["Manufacturer", "Manufacturing company", "Machine manufacturer"],
            ["Naroda"],
        )
        plans = gen.generate("Ahmedabad", "Manufacturers")
        queries = [p["search_query"] for p in plans]
        assert "Manufacturer in Naroda" in queries
        assert "Manufacturing company in Naroda" in queries
        assert "Machine manufacturer in Naroda" in queries

    def test_all_plans_share_same_canonical(self):
        gen = _make_generator(
            ["Dentist", "Dental clinic", "Dental lab"],
            ["Paldi", "Maninagar"],
        )
        plans = gen.generate("Ahmedabad", "Dentist")
        assert all(p["canonical_category"] == "Dentist" for p in plans)

    def test_original_city_preserved_in_all_plans(self):
        gen = _make_generator(["Dentist"], ["SoHo", "Midtown"])
        plans = gen.generate("New York", "Dentist")
        assert all(p["original_city"] == "New York" for p in plans)


# ── Geographic resolution ────────────────────────────────────────────────────


class TestGeographicResolution:
    def test_each_partition_generates_one_plan_per_variant(self):
        variants = ["Dentist", "Dental clinic"]
        partitions = ["Navrangpura", "Paldi", "Maninagar"]
        gen = _make_generator(variants, partitions)
        plans = gen.generate("Ahmedabad", "Dentist")
        # 2 variants × 3 partitions = 6 plans
        assert len(plans) == 6

    def test_geographic_partition_field_matches_geo(self):
        gen = _make_generator(["Dentist"], ["Navrangpura", "Paldi"])
        plans = gen.generate("Ahmedabad", "Dentist")
        partitions_in_plans = {p["geographic_partition"] for p in plans}
        assert partitions_in_plans == {"Navrangpura", "Paldi"}

    def test_geo_fallback_to_city_when_resolver_returns_empty(self):
        gen = _make_generator(["Dentist"], [])
        plans = gen.generate("Ahmedabad", "Dentist")
        assert len(plans) == 1
        assert plans[0]["geographic_partition"] == "Ahmedabad"
        assert plans[0]["original_city"] == "Ahmedabad"
        assert plans[0]["search_query"] == "Dentist in Ahmedabad"

    def test_geo_fallback_with_multiple_variants(self):
        gen = _make_generator(["Dentist", "Dental clinic"], [])
        plans = gen.generate("Surat", "Dentist")
        # Both variants × single city fallback = 2 plans
        assert len(plans) == 2
        assert all(p["geographic_partition"] == "Surat" for p in plans)


# ── Cartesian generation ─────────────────────────────────────────────────────


class TestCartesianGeneration:
    def test_plan_count_equals_cartesian_product(self):
        gen = _make_generator(
            ["A", "B", "C"],
            ["X", "Y", "Z", "W"],
        )
        plans = gen.generate("City", "A")
        assert len(plans) == 3 * 4

    def test_search_query_format(self):
        gen = _make_generator(["Manufacturer"], ["Naroda"])
        plans = gen.generate("Ahmedabad", "Manufacturer")
        assert plans[0]["search_query"] == "Manufacturer in Naroda"

    def test_single_variant_single_geo(self):
        gen = _make_generator(["Dentist"], ["Paldi"])
        plans = gen.generate("Ahmedabad", "Dentist")
        assert len(plans) == 1
        assert plans[0]["search_query"] == "Dentist in Paldi"

    def test_all_combinations_present(self):
        variants = ["Manufacturer", "Factory"]
        geos = ["Naroda", "Vatva", "Odhav"]
        gen = _make_generator(variants, geos)
        plans = gen.generate("Ahmedabad", "Manufacturer")
        expected = {f"{v} in {g}" for v in variants for g in geos}
        actual = {p["search_query"] for p in plans}
        assert expected == actual


# ── Priority ordering ────────────────────────────────────────────────────────


class TestPriorityOrdering:
    def test_primary_variant_has_highest_priority(self):
        gen = _make_generator(
            ["Manufacturer", "Manufacturing company"],
            ["Naroda"],
        )
        plans = gen.generate("Ahmedabad", "Manufacturers")
        primary_scores = [
            p["priority_score"]
            for p in plans
            if "Manufacturer in" in p["search_query"]
            and "company" not in p["search_query"]
        ]
        secondary_scores = [
            p["priority_score"]
            for p in plans
            if "Manufacturing company" in p["search_query"]
        ]
        assert primary_scores
        assert secondary_scores
        assert min(primary_scores) > max(secondary_scores)

    def test_priority_strictly_descending_in_output(self):
        gen = _make_generator(
            ["A", "B", "C"],
            ["X", "Y", "Z"],
        )
        plans = gen.generate("City", "A")
        scores = [p["priority_score"] for p in plans]
        assert scores == sorted(scores, reverse=True)

    def test_primary_variant_all_geos_before_secondary_variant_any_geo(self):
        variants = ["Primary", "Secondary"]
        geos = ["G1", "G2", "G3"]
        gen = _make_generator(variants, geos)
        plans = gen.generate("City", "Primary")
        primary_plans = [p for p in plans if p["search_query"].startswith("Primary")]
        secondary_plans = [
            p for p in plans if p["search_query"].startswith("Secondary")
        ]
        # All primary scores must exceed all secondary scores.
        assert min(p["priority_score"] for p in primary_plans) > max(
            p["priority_score"] for p in secondary_plans
        )

    def test_within_primary_tier_geo_order_preserved(self):
        geos = ["First", "Second", "Third"]
        gen = _make_generator(["Manufacturer"], geos)
        plans = gen.generate("City", "Manufacturer")
        # Geo ordering from resolver must be respected: First > Second > Third
        assert plans[0]["geographic_partition"] == "First"
        assert plans[1]["geographic_partition"] == "Second"
        assert plans[2]["geographic_partition"] == "Third"

    def test_secondary_tier_geo_order_preserved(self):
        geos = ["Alpha", "Beta", "Gamma"]
        gen = _make_generator(["Primary", "Secondary"], geos)
        plans = gen.generate("City", "Primary")
        secondary = [p for p in plans if p["search_query"].startswith("Secondary")]
        assert secondary[0]["geographic_partition"] == "Alpha"
        assert secondary[1]["geographic_partition"] == "Beta"
        assert secondary[2]["geographic_partition"] == "Gamma"


# ── Execution order ───────────────────────────────────────────────────────────


class TestExecutionOrder:
    def test_execution_order_starts_at_one(self):
        gen = _make_generator(["Dentist"], ["Paldi"])
        plans = gen.generate("Ahmedabad", "Dentist")
        assert plans[0]["execution_order"] == 1

    def test_execution_order_sequential(self):
        gen = _make_generator(["A", "B"], ["X", "Y", "Z"])
        plans = gen.generate("City", "A")
        orders = [p["execution_order"] for p in plans]
        assert orders == list(range(1, len(plans) + 1))

    def test_execution_order_reflects_priority_sequence(self):
        gen = _make_generator(["Primary", "Secondary"], ["G1", "G2"])
        plans = gen.generate("City", "Primary")
        # Plan 1 must be Primary in G1 (highest priority)
        assert plans[0]["search_query"] == "Primary in G1"
        assert plans[0]["execution_order"] == 1
        # Last plan must be Secondary in G2
        assert plans[-1]["search_query"] == "Secondary in G2"
        assert plans[-1]["execution_order"] == 4

    def test_execution_order_single_plan(self):
        gen = _make_generator([], ["G1"])  # empty variants → raw category
        plans = gen.generate("City", "SomeCategory")
        assert plans[0]["execution_order"] == 1


# ── Duplicate elimination ─────────────────────────────────────────────────────


class TestDuplicateElimination:
    def test_duplicate_queries_removed(self):
        # Build plans manually to test _deduplicate directly.
        plan_a: SearchPlan = {
            "search_query": "Dentist in Paldi",
            "canonical_category": "Dentist",
            "geographic_partition": "Paldi",
            "original_city": "Ahmedabad",
            "priority_score": 100.0,
            "execution_order": 0,
        }
        plan_b: SearchPlan = {
            "search_query": "Dentist in Paldi",  # exact duplicate
            "canonical_category": "Dentist",
            "geographic_partition": "Paldi",
            "original_city": "Ahmedabad",
            "priority_score": 50.0,
            "execution_order": 0,
        }
        result = _deduplicate([plan_a, plan_b])
        assert len(result) == 1
        assert result[0]["priority_score"] == 100.0  # first (higher priority) kept

    def test_case_insensitive_dedup(self):
        plan_a: SearchPlan = {
            "search_query": "Dentist in Paldi",
            "canonical_category": "Dentist",
            "geographic_partition": "Paldi",
            "original_city": "Ahmedabad",
            "priority_score": 100.0,
            "execution_order": 0,
        }
        plan_b: SearchPlan = {
            "search_query": "DENTIST IN PALDI",
            "canonical_category": "Dentist",
            "geographic_partition": "Paldi",
            "original_city": "Ahmedabad",
            "priority_score": 50.0,
            "execution_order": 0,
        }
        result = _deduplicate([plan_a, plan_b])
        assert len(result) == 1

    def test_distinct_queries_all_retained(self):
        plans: list[SearchPlan] = [
            {
                "search_query": f"Dentist in Zone{i}",
                "canonical_category": "Dentist",
                "geographic_partition": f"Zone{i}",
                "original_city": "City",
                "priority_score": float(100 - i),
                "execution_order": 0,
            }
            for i in range(5)
        ]
        result = _deduplicate(plans)
        assert len(result) == 5

    def test_execution_order_reassigned_after_dedup(self):
        # When SearchPlanGenerator.generate() deduplicates, execution_order
        # must still be sequential from 1.
        gen = _make_generator(["A"], ["X", "X", "Y"])  # X appears twice
        plans = gen.generate("City", "A")
        # "A in X" appears twice → deduped to one; "A in Y" is distinct.
        queries = [p["search_query"] for p in plans]
        assert queries.count("A in X") == 1
        orders = [p["execution_order"] for p in plans]
        assert orders == list(range(1, len(plans) + 1))


# ── Fallback rules ────────────────────────────────────────────────────────────


class TestFallbackRules:
    def test_empty_category_returns_empty_list(self):
        gen = _make_generator(["Dentist"], ["Paldi"])
        assert gen.generate("Ahmedabad", "") == []
        assert gen.generate("Ahmedabad", "   ") == []

    def test_empty_city_returns_empty_list(self):
        gen = _make_generator(["Dentist"], ["Paldi"])
        assert gen.generate("", "Dentist") == []
        assert gen.generate("   ", "Dentist") == []

    def test_both_empty_returns_empty_list(self):
        gen = _make_generator(["Dentist"], ["Paldi"])
        assert gen.generate("", "") == []

    def test_unresolved_category_uses_raw_input_as_canonical(self):
        gen = _make_generator([], ["Naroda"])
        plans = gen.generate("Ahmedabad", "RareNicheCategory")
        assert len(plans) == 1
        assert plans[0]["canonical_category"] == "RareNicheCategory"
        assert plans[0]["search_query"] == "RareNicheCategory in Naroda"

    def test_empty_geo_uses_city_as_single_partition(self):
        gen = _make_generator(["Dentist"], [])
        plans = gen.generate("Ahmedabad", "Dentist")
        assert len(plans) == 1
        assert plans[0]["geographic_partition"] == "Ahmedabad"

    def test_both_fallbacks_active_produces_single_plan(self):
        gen = _make_generator([], [])
        plans = gen.generate("Surat", "UnknownThing")
        assert len(plans) == 1
        assert plans[0]["search_query"] == "UnknownThing in Surat"
        assert plans[0]["canonical_category"] == "UnknownThing"
        assert plans[0]["geographic_partition"] == "Surat"
        assert plans[0]["original_city"] == "Surat"
        assert plans[0]["execution_order"] == 1


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_identical_inputs_produce_identical_outputs(self):
        gen = _make_generator(
            ["Manufacturer", "Manufacturing company", "Machine manufacturer"],
            ["Naroda", "Vatva", "Odhav", "GIDC"],
        )
        plans_1 = gen.generate("Ahmedabad", "Manufacturers", target_qualified_leads=30)
        plans_2 = gen.generate("Ahmedabad", "Manufacturers", target_qualified_leads=30)
        assert plans_1 == plans_2

    def test_repeated_calls_same_order(self):
        gen = _make_generator(["A", "B"], ["X", "Y", "Z"])
        for _ in range(5):
            plans = gen.generate("City", "A")
            assert [p["search_query"] for p in plans] == [
                "A in X",
                "A in Y",
                "A in Z",
                "B in X",
                "B in Y",
                "B in Z",
            ]

    def test_different_instances_same_output(self):
        stubs = dict(
            variants=["Dentist", "Dental clinic"],
            partitions=["Navrangpura", "Paldi"],
        )
        gen1 = _make_generator(**stubs)
        gen2 = _make_generator(**stubs)
        assert gen1.generate("Ahmedabad", "Dentist") == gen2.generate(
            "Ahmedabad", "Dentist"
        )

    def test_target_leads_does_not_affect_plan_content(self):
        gen = _make_generator(["Dentist"], ["Paldi"])
        plans_10 = gen.generate("Ahmedabad", "Dentist", target_qualified_leads=10)
        plans_100 = gen.generate("Ahmedabad", "Dentist", target_qualified_leads=100)
        assert plans_10 == plans_100


# ── Architectural boundary ────────────────────────────────────────────────────


class TestArchitecturalBoundary:
    def test_generator_accepts_injected_resolvers(self):
        gen = SearchPlanGenerator(
            category_resolver=_StubCategoryResolver(["Dentist"]),
            geo_resolver=_StubGeoResolver(["Paldi"]),
        )
        plans = gen.generate("Ahmedabad", "Dentist")
        assert len(plans) == 1

    def test_no_runtime_state_in_plans(self):
        gen = _make_generator(["Dentist"], ["Paldi"])
        plan = gen.generate("Ahmedabad", "Dentist")[0]
        forbidden = {
            "campaign_id",
            "search_id",
            "browser_context",
            "queue",
            "scraper",
            "repository",
            "execution_metadata",
        }
        assert not forbidden.intersection(set(plan.keys()))
