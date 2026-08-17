"""Phase 4 planner unit tests — SearchPlanGenerator intelligence improvements.

Verifies:
  - Taxonomy-aware category expansion via token-prefix overlap
  - Morphological root matching (_tokens_match precision / recall)
  - Geographic partition ordering by business-density zone score
  - Stable sort preservation for equal-score partitions
  - Base-variant filtering via _BASE_VARIANT_SIM_THRESHOLD
  - Normalised deduplication (apostrophes, whitespace)
  - Full determinism across repeated executions
  - Backward compatibility with stub resolvers (no taxonomy path)
  - Priority score ordering reflects geo zone tier
  - Regression: 214 existing tests continue passing (enforced by CI; not re-run here)
"""

from __future__ import annotations

import pytest

from leadforge.sil.search_plan_generator import (
    _BASE_VARIANT_SIM_THRESHOLD,
    _MATCH_PREFIX_FRACTION,
    _MAX_EXPANDED_VARIANTS,
    _deduplicate,
    _expand_from_taxonomy,
    _geo_zone_score,
    _normalize_query,
    _prioritize_geo_partitions,
    _token_overlap_score,
    _tokenize_category,
    _tokens_match,
    SearchPlan,
    SearchPlanGenerator,
)


# ─────────────────────────────────────────────────────────────────────────────
# Stub resolvers (no I/O)
# ─────────────────────────────────────────────────────────────────────────────


class _StubCategoryResolver:
    """No all_categories attribute — exercises the stub/legacy code path."""

    def __init__(self, variants: list[str]) -> None:
        self._variants = variants

    def get_variants(self, _category: str) -> list[str]:
        return list(self._variants)


class _TaxonomyCategoryResolver:
    """Minimal taxonomy resolver that exposes all_categories."""

    def __init__(self, canonical: str, all_categories: list[str]) -> None:
        self._canonical = canonical
        self.all_categories = all_categories

    def get_variants(self, _category: str) -> list[str]:
        return [self._canonical]


class _StubGeoResolver:
    def __init__(self, partitions: list[str]) -> None:
        self._partitions = partitions

    def get_neighbourhoods(self, _city: str) -> list[str]:
        return list(self._partitions)


# ─────────────────────────────────────────────────────────────────────────────
# _tokenize_category
# ─────────────────────────────────────────────────────────────────────────────


class TestTokenizeCategory:
    def test_basic_split(self):
        assert _tokenize_category("Dental Clinic") == frozenset({"dental", "clinic"})

    def test_removes_stopwords(self):
        toks = _tokenize_category("Food and Beverage Manufacturer")
        assert "and" not in toks
        assert "food" in toks
        assert "manufacturer" in toks

    def test_drops_short_tokens(self):
        toks = _tokenize_category("A to Z Distributor")
        assert "a" not in toks
        assert "to" not in toks

    def test_punctuation_split(self):
        toks = _tokenize_category("Hardware/Software Supplier")
        assert "hardware" in toks
        assert "software" in toks
        assert "supplier" in toks

    def test_empty_string(self):
        assert _tokenize_category("") == frozenset()

    def test_all_stopwords(self):
        assert _tokenize_category("of the a") == frozenset()


# ─────────────────────────────────────────────────────────────────────────────
# _tokens_match — precision and recall
# ─────────────────────────────────────────────────────────────────────────────


class TestTokensMatch:
    # True positives — morphological relatives
    def test_exact_match(self):
        assert _tokens_match("dental", "dental") is True

    def test_full_prefix_containment_machine_machinery(self):
        assert _tokens_match("machine", "machinery") is True

    def test_full_prefix_containment_reversed(self):
        assert _tokens_match("machinery", "machine") is True

    def test_five_char_prefix_manufacturer_manufacturing(self):
        assert _tokens_match("manufacturer", "manufacturing") is True

    def test_four_char_prefix_fraction_dental_dentist(self):
        # "dent" / "dental" = 4/6 = 67%, "dent" / "dentist" = 4/7 = 57%
        # both ≥ _MATCH_PREFIX_FRACTION (50%) → True
        assert _tokens_match("dental", "dentist") is True

    def test_food_foods(self):
        assert _tokens_match("food", "foods") is True

    def test_engineer_engineering(self):
        assert _tokens_match("engineer", "engineering") is True

    # False positives correctly excluded
    def test_restaurant_restoration_excluded(self):
        # "rest" / "restaurant" = 4/10 = 40% < 50% → False
        assert _tokens_match("restaurant", "restoration") is False

    def test_restaurant_restoration_reversed(self):
        assert _tokens_match("restoration", "restaurant") is False

    def test_short_token_excluded(self):
        # tokens < 4 chars never match on prefix
        assert _tokens_match("art", "artist") is False

    def test_unrelated_words(self):
        assert _tokens_match("dental", "market") is False

    def test_prefix_fraction_constant_is_fifty_percent(self):
        assert _MATCH_PREFIX_FRACTION == 0.50


# ─────────────────────────────────────────────────────────────────────────────
# _token_overlap_score
# ─────────────────────────────────────────────────────────────────────────────


class TestTokenOverlapScore:
    def test_exact_category_match(self):
        q = frozenset({"restaurant"})
        c = frozenset({"indian", "restaurant"})
        assert _token_overlap_score(q, c) == 1

    def test_prefix_match_counted(self):
        q = frozenset({"dentist"})
        c = frozenset({"dental", "clinic"})
        assert _token_overlap_score(q, c) == 1

    def test_no_overlap_zero(self):
        q = frozenset({"restaurant"})
        c = frozenset({"restoration", "service"})
        # restaurant/restoration → False (fraction gate); service → no match
        assert _token_overlap_score(q, c) == 0

    def test_multi_token_query(self):
        q = frozenset({"machine", "manufacturer"})
        c = frozenset({"machine", "parts"})
        assert _token_overlap_score(q, c) == 1


# ─────────────────────────────────────────────────────────────────────────────
# _geo_zone_score
# ─────────────────────────────────────────────────────────────────────────────


class TestGeoZoneScore:
    def test_industrial_gidc(self):
        assert _geo_zone_score("GIDC Estate") == 3

    def test_industrial_area(self):
        assert _geo_zone_score("Industrial Area") == 3

    def test_commercial_market(self):
        assert _geo_zone_score("Commercial Market") == 2

    def test_commercial_chowk(self):
        assert _geo_zone_score("Lal Chowk") == 2

    def test_general_zero(self):
        assert _geo_zone_score("Navrangpura") == 0

    def test_residential_negative(self):
        assert _geo_zone_score("Green Colony") == -1

    def test_township_residential(self):
        assert _geo_zone_score("Satellite Township") == -1

    def test_case_insensitive(self):
        assert _geo_zone_score("gidc estate") == 3


# ─────────────────────────────────────────────────────────────────────────────
# _prioritize_geo_partitions
# ─────────────────────────────────────────────────────────────────────────────


class TestPrioritizeGeoPartitions:
    def test_industrial_before_commercial(self):
        ordered = _prioritize_geo_partitions(
            ["Commercial Zone", "GIDC Estate", "General Area"]
        )
        assert ordered.index("GIDC Estate") < ordered.index("Commercial Zone")

    def test_commercial_before_general(self):
        ordered = _prioritize_geo_partitions(
            ["Navrangpura", "Manek Chowk", "GIDC Estate"]
        )
        assert ordered.index("Manek Chowk") < ordered.index("Navrangpura")

    def test_general_before_residential(self):
        ordered = _prioritize_geo_partitions(
            ["Green Colony", "Navrangpura", "GIDC Estate"]
        )
        assert ordered.index("Navrangpura") < ordered.index("Green Colony")

    def test_stable_sort_equal_score_preserves_input_order(self):
        # All score=0; input order must be preserved.
        parts = ["Alpha", "Beta", "Gamma"]
        assert _prioritize_geo_partitions(parts) == ["Alpha", "Beta", "Gamma"]

    def test_stable_sort_two_industrial_zones(self):
        # Both score=3; must preserve original order between them.
        parts = ["First Industrial", "Second Industrial"]
        ordered = _prioritize_geo_partitions(parts)
        assert ordered[0] == "First Industrial"
        assert ordered[1] == "Second Industrial"

    def test_empty_list(self):
        assert _prioritize_geo_partitions([]) == []

    def test_full_ordering(self):
        parts = [
            "Colony A",       # -1
            "Commercial Zone", # 2
            "GIDC Estate",    # 3
            "Navrangpura",    # 0
            "Industrial Area", # 3
            "Paldi",          # 0
        ]
        ordered = _prioritize_geo_partitions(parts)
        scores = [_geo_zone_score(p) for p in ordered]
        # Must be non-increasing.
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]
        # GIDC and Industrial Area both 3, GIDC was before Industrial in input
        assert ordered.index("GIDC Estate") < ordered.index("Industrial Area")


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_query
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeQuery:
    def test_lowercase(self):
        assert _normalize_query("Dental Clinic") == "dental clinic"

    def test_strips_apostrophe_possessive(self):
        assert _normalize_query("Dentist's Clinic") == "dentist clinic"

    def test_strips_apostrophe_s(self):
        assert _normalize_query("Doctor's Office") == "doctor office"

    def test_collapses_whitespace(self):
        assert _normalize_query("Dental  Clinic") == "dental clinic"

    def test_strip_leading_trailing(self):
        assert _normalize_query("  dental clinic  ") == "dental clinic"

    def test_bare_apostrophe(self):
        # "'s" is stripped entirely, not converted to "s"
        assert _normalize_query("it's") == "it"


# ─────────────────────────────────────────────────────────────────────────────
# _deduplicate
# ─────────────────────────────────────────────────────────────────────────────


def _make_plan(query: str, score: float = 10.0) -> SearchPlan:
    return SearchPlan(
        search_query=query,
        canonical_category="Test",
        geographic_partition="City",
        original_city="City",
        priority_score=score,
        execution_order=0,
    )


class TestDeduplicate:
    def test_removes_exact_duplicate(self):
        plans = [_make_plan("Dentist in Ahmedabad"), _make_plan("Dentist in Ahmedabad")]
        assert len(_deduplicate(plans)) == 1

    def test_removes_apostrophe_variant(self):
        # "Dentist's in City" normalises to "dentist in city"
        # "Dentist in City"   normalises to "dentist in city"  → same key
        plans = [
            _make_plan("Dentist's in Ahmedabad"),
            _make_plan("Dentist in Ahmedabad"),
        ]
        assert len(_deduplicate(plans)) == 1

    def test_case_insensitive_dedup(self):
        plans = [_make_plan("DENTIST in City"), _make_plan("dentist in city")]
        assert len(_deduplicate(plans)) == 1

    def test_whitespace_dedup(self):
        plans = [_make_plan("Dental  Clinic in City"), _make_plan("Dental Clinic in City")]
        assert len(_deduplicate(plans)) == 1

    def test_preserves_first_occurrence(self):
        p1 = _make_plan("Dentist in City", score=100.0)
        p2 = _make_plan("Dentist in City", score=50.0)
        result = _deduplicate([p1, p2])
        assert result[0]["priority_score"] == 100.0

    def test_distinct_plans_unchanged(self):
        plans = [
            _make_plan("Dentist in Alpha"),
            _make_plan("Dental Clinic in Alpha"),
        ]
        assert len(_deduplicate(plans)) == 2


# ─────────────────────────────────────────────────────────────────────────────
# _expand_from_taxonomy
# ─────────────────────────────────────────────────────────────────────────────


class TestExpandFromTaxonomy:
    # A minimal synthetic taxonomy
    _TAXONOMY = [
        "Manufacturer",
        "Food manufacturer",
        "Machine manufacturer",
        "Manufacturing company",
        "Steel fabricator",
        "Distributor",
        "Retailer",
    ]

    def test_canonical_is_first(self):
        base = ["Manufacturer", "Food manufacturer"]
        result = _expand_from_taxonomy("Manufacturer", base, self._TAXONOMY)
        assert result[0] == "Manufacturer"

    def test_token_overlap_finds_manufacturing_company(self):
        base = ["Manufacturer"]
        result = _expand_from_taxonomy("Manufacturer", base, self._TAXONOMY)
        assert "Manufacturing company" in result

    def test_steel_fabricator_excluded_no_overlap(self):
        # "fabricator" shares no token with "manufacturer"
        base = ["Manufacturer"]
        result = _expand_from_taxonomy("Manufacturer", base, self._TAXONOMY)
        assert "Steel fabricator" not in result

    def test_distributor_excluded(self):
        base = ["Manufacturer"]
        result = _expand_from_taxonomy("Manufacturer", base, self._TAXONOMY)
        assert "Distributor" not in result

    def test_max_expanded_variants_cap(self):
        # Generate a large synthetic taxonomy with many overlap matches.
        big_taxonomy = [f"Test {i} manufacturer" for i in range(50)]
        base = ["Test 0 manufacturer"]
        result = _expand_from_taxonomy("Manufacturer", base, big_taxonomy)
        assert len(result) <= _MAX_EXPANDED_VARIANTS

    def test_max_expanded_variants_constant(self):
        assert _MAX_EXPANDED_VARIANTS == 8

    def test_base_variant_sim_threshold_constant(self):
        assert _BASE_VARIANT_SIM_THRESHOLD == 0.65

    def test_base_variant_low_sim_excluded(self):
        # "Artist" has ~0.615 string similarity to "Dentist" but zero token overlap.
        # It must be excluded (0.615 < _BASE_VARIANT_SIM_THRESHOLD=0.65).
        taxonomy = ["Dentist", "Dental clinic", "Artist", "Orthodontist"]
        base = ["Dentist", "Artist", "Orthodontist"]
        result = _expand_from_taxonomy("Dentist", base, taxonomy)
        assert "Artist" not in result

    def test_low_sim_zero_overlap_base_variant_excluded(self):
        # "Retailer" has zero token overlap with "Manufacturer" and
        # low string similarity → must be excluded by _BASE_VARIANT_SIM_THRESHOLD.
        taxonomy = ["Manufacturer", "Retailer"]
        base = ["Manufacturer", "Retailer"]
        result = _expand_from_taxonomy("Manufacturer", base, taxonomy)
        assert "Retailer" not in result

    def test_no_duplicates_in_result(self):
        base = ["Manufacturer", "Food manufacturer", "Machine manufacturer"]
        result = _expand_from_taxonomy("Manufacturer", base, self._TAXONOMY)
        assert len(result) == len(set(result))

    def test_empty_taxonomy_returns_canonical(self):
        result = _expand_from_taxonomy("Manufacturer", ["Manufacturer"], [])
        assert result == ["Manufacturer"]

    def test_deterministic_repeated_calls(self):
        base = ["Manufacturer", "Food manufacturer"]
        r1 = _expand_from_taxonomy("Manufacturer", base, self._TAXONOMY)
        r2 = _expand_from_taxonomy("Manufacturer", base, self._TAXONOMY)
        assert r1 == r2


# ─────────────────────────────────────────────────────────────────────────────
# SearchPlanGenerator — full integration
# ─────────────────────────────────────────────────────────────────────────────


class TestSearchPlanGeneratorStubPath:
    """Stub resolver path: no taxonomy expansion, Phase 2 contracts preserved."""

    def _gen(self, variants, partitions):
        return SearchPlanGenerator(
            category_resolver=_StubCategoryResolver(variants),
            geo_resolver=_StubGeoResolver(partitions),
        )

    def test_returns_list_of_dicts(self):
        # SearchPlan is a TypedDict (subclass of dict); isinstance(x, SearchPlan)
        # raises TypeError at runtime — use dict instead.
        plans = self._gen(["Widget"], ["City"]).generate("City", "Widget")
        assert isinstance(plans, list)
        assert all(isinstance(p, dict) for p in plans)
        assert all("search_query" in p and "execution_order" in p for p in plans)

    def test_execution_order_is_one_based(self):
        plans = self._gen(["A", "B"], ["X", "Y"]).generate("X", "A")
        orders = [p["execution_order"] for p in plans]
        assert orders == list(range(1, len(plans) + 1))

    def test_no_taxonomy_expansion_without_all_categories(self):
        # StubCategoryResolver has no all_categories → expansion skipped.
        plans = self._gen(["Widget", "Gadget"], ["City"]).generate("City", "Widget")
        queries = {p["search_query"] for p in plans}
        assert "Widget in City" in queries
        assert "Gadget in City" in queries

    def test_empty_city_returns_empty(self):
        plans = self._gen(["Widget"], ["X"]).generate("", "Widget")
        assert plans == []

    def test_empty_category_returns_empty(self):
        plans = self._gen(["Widget"], ["X"]).generate("City", "")
        assert plans == []

    def test_original_city_preserved(self):
        plans = self._gen(["Widget"], ["District"]).generate("City", "Widget")
        assert all(p["original_city"] == "City" for p in plans)

    def test_canonical_category_matches_first_variant(self):
        plans = self._gen(["Widget", "Gadget"], ["District"]).generate("City", "Widget")
        assert all(p["canonical_category"] == "Widget" for p in plans)

    def test_stub_resolver_order_preserved(self):
        # Stub path has no geo zone sorting.
        parts = ["Third", "Second", "First"]
        plans = self._gen(["Widget"], parts).generate("City", "Widget")
        # Plans ordered Third → Second → First (stub respects resolver order).
        partitions_in_order = [p["geographic_partition"] for p in plans]
        assert partitions_in_order == ["Third", "Second", "First"]


class TestSearchPlanGeneratorTaxonomyPath:
    """Taxonomy resolver path: verifies Phase 4 expansion and geo ordering."""

    _TAXONOMY = [
        "Machine manufacturer",
        "Manufacturing company",
        "Textile manufacturer",
        "Food manufacturer",
        "Valve manufacturer",
        "Paint manufacturer",
        "Manufacturer",
        "Distributor",   # no overlap with "Manufacturer"
    ]

    def _gen(self, canonical: str, partitions: list[str]) -> SearchPlanGenerator:
        return SearchPlanGenerator(
            category_resolver=_TaxonomyCategoryResolver(canonical, self._TAXONOMY),
            geo_resolver=_StubGeoResolver(partitions),
        )

    def test_manufacturing_company_included(self):
        plans = self._gen("Manufacturer", ["City"]).generate("City", "Manufacturer")
        queries = {p["search_query"] for p in plans}
        assert "Manufacturing company in City" in queries

    def test_distributor_excluded_no_overlap(self):
        plans = self._gen("Manufacturer", ["City"]).generate("City", "Manufacturer")
        queries = {p["search_query"] for p in plans}
        assert "Distributor in City" not in queries

    def test_geo_industrial_first(self):
        parts = ["Residential Colony", "GIDC Estate", "Navrangpura"]
        plans = self._gen("Manufacturer", parts).generate("City", "Manufacturer")
        # First plan's partition must be GIDC Estate (score=3).
        assert plans[0]["geographic_partition"] == "GIDC Estate"

    def test_geo_residential_last_within_variant(self):
        parts = ["Residential Colony", "Commercial Market", "GIDC Estate"]
        plans = self._gen("Manufacturer", parts).generate("City", "Manufacturer")
        # Among plans for the first (canonical) variant, residential must be last.
        first_variant = plans[0]["canonical_category"]
        variant_plans = [p for p in plans if p["search_query"].startswith(f"{first_variant} in")]
        assert variant_plans[-1]["geographic_partition"] == "Residential Colony"

    def test_priority_scores_non_increasing(self):
        parts = ["GIDC Estate", "Commercial Market", "Colony"]
        plans = self._gen("Manufacturer", parts).generate("City", "Manufacturer")
        scores = [p["priority_score"] for p in plans]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))

    def test_deterministic_repeated_calls(self):
        parts = ["Colony", "GIDC Estate", "Market"]
        gen = self._gen("Manufacturer", parts)
        r1 = gen.generate("City", "Manufacturer")
        r2 = gen.generate("City", "Manufacturer")
        assert [p["search_query"] for p in r1] == [p["search_query"] for p in r2]

    def test_no_duplicate_plans(self):
        parts = ["Area", "Area", "Zone"]
        plans = self._gen("Manufacturer", parts).generate("City", "Manufacturer")
        queries = [p["search_query"] for p in plans]
        assert len(queries) == len(set(queries))


class TestSearchPlanGeneratorNormalisedDedup:
    """Deduplication catches near-duplicate queries after normalisation."""

    def _gen(self, variants, partitions):
        return SearchPlanGenerator(
            category_resolver=_StubCategoryResolver(variants),
            geo_resolver=_StubGeoResolver(partitions),
        )

    def test_apostrophe_variant_deduped(self):
        # "Dentist's" and "Dentists" normalise to the same key.
        plans = self._gen(["Dentist's", "Dentists"], ["City"]).generate("City", "Dentist's")
        queries = [p["search_query"] for p in plans]
        assert len(queries) == len(set(queries))

    def test_whitespace_variant_deduped(self):
        plans = self._gen(["Dental  Clinic", "Dental Clinic"], ["City"]).generate(
            "City", "Dental  Clinic"
        )
        queries = [p["search_query"] for p in plans]
        assert len(queries) == len(set(queries))


# ─────────────────────────────────────────────────────────────────────────────
# Real-resolver smoke tests (requires installed taxonomy data)
# ─────────────────────────────────────────────────────────────────────────────


class TestRealResolverSmoke:
    """Light smoke tests using the actual CategoryResolver + taxonomy."""

    @pytest.fixture(scope="class", autouse=True)
    def mock_geo_resolver(self):
        from unittest.mock import patch
        def mock_get_neighbourhoods(city: str) -> list[str]:
            city_lower = city.lower()
            if "ahmedabad" in city_lower:
                return ["GIDC Estate", "Navrangpura", "Paldi"]
            elif "mumbai" in city_lower:
                return ["Andheri", "Bandra", "Commercial Chowk"]
            elif "surat" in city_lower:
                return ["Mini Bazar", "Hirabag", "Varachha"]
            return ["Colony A", "Commercial Zone", "GIDC Estate"]

        with patch("leadforge.sil.geo_resolver.GeoResolver.get_neighbourhoods", side_effect=mock_get_neighbourhoods) as m:
            yield m

    @pytest.fixture(scope="class")
    def gen(self, mock_geo_resolver) -> SearchPlanGenerator:
        return SearchPlanGenerator()

    def test_dentist_no_artist_variant(self, gen):
        plans = gen.generate("Ahmedabad", "Dentist")
        queries = {p["search_query"] for p in plans}
        assert all("Artist" not in q for q in queries)

    def test_dentist_no_department_store(self, gen):
        plans = gen.generate("Ahmedabad", "Dentist")
        queries = {p["search_query"] for p in plans}
        assert all("Department store" not in q for q in queries)

    def test_dentist_has_dental_clinic(self, gen):
        plans = gen.generate("Ahmedabad", "Dentist")
        queries = {p["search_query"] for p in plans}
        assert any("Dental clinic" in q for q in queries)

    def test_restaurant_no_restoration_service(self, gen):
        plans = gen.generate("Mumbai", "Restaurant")
        queries = {p["search_query"] for p in plans}
        assert all("restoration" not in q.lower() for q in queries)

    def test_manufacturer_max_eight_variants(self, gen):
        plans = gen.generate("Ahmedabad", "Manufacturer")
        variants = {p["search_query"].split(" in ")[0] for p in plans}
        assert len(variants) <= _MAX_EXPANDED_VARIANTS

    def test_plans_are_deterministic(self, gen):
        p1 = [p["search_query"] for p in gen.generate("Surat", "Dentist")]
        p2 = [p["search_query"] for p in gen.generate("Surat", "Dentist")]
        assert p1 == p2

    def test_execution_order_is_contiguous(self, gen):
        plans = gen.generate("Surat", "Manufacturer")
        assert [p["execution_order"] for p in plans] == list(range(1, len(plans) + 1))

    def test_no_duplicate_queries(self, gen):
        plans = gen.generate("Ahmedabad", "Manufacturer")
        queries = [p["search_query"] for p in plans]
        assert len(queries) == len(set(queries))
