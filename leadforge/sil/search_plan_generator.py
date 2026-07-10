"""Deterministic Search Plan Generator — Search Intelligence Layer Phase 4.

Accepts a city, category, and target lead count; produces a fully-ordered,
deduplicated list of SearchPlan objects ready for downstream execution by
the SearchOrchestrator.

Phase 4 planning algorithm:
  1. Resolve category → taxonomy-aware variants (token-overlap + difflib).
  2. Resolve city → neighbourhood partitions via GeoResolver.
  3. Prioritise partitions by business-density zone heuristics (stable sort).
  4. Generate Cartesian product (variants × prioritised partitions).
  5. Assign deterministic multi-factor priority scores.
  6. Eliminate plans with equivalent normalised search intent.
  7. Assign 1-based execution_order after deduplication.

Phase 4 improvements over Phase 2:
  - Category expansion: token-prefix overlap against the full Google Business
    Category taxonomy finds semantic relatives (e.g. "Manufacturer" →
    "Manufacturing company", "Machine manufacturer", "Fabrication engineer")
    that pure difflib string similarity misses.
  - Geographic prioritisation: industrial zones (GIDC, estate, cluster) and
    commercial districts (market, chowk, bazaar) are ordered before general
    or residential partitions using a deterministic zone-score heuristic.
  - Priority scoring: position within a geo tier reflects zone quality, giving
    high-density B2B areas higher execution priority inside each variant tier.
  - Redundancy elimination: normalised-query deduplication strips extra
    whitespace and apostrophes before comparison, catching near-duplicates.

This module is a pure planning component:
  - No network calls.
  - No SQLite access.
  - No Playwright.
  - No repository access.
  - No campaign state.
  - Every identical input produces identical output.
"""

import difflib
import re
from typing import Optional, TypedDict

from leadforge.sil.category_resolver import CategoryResolver
from leadforge.sil.geo_resolver import GeoResolver

# ── Constants ─────────────────────────────────────────────────────────────────

# Each variant tier is separated by _VARIANT_TIER_GAP points so the lowest-
# ranked geo entry in one tier always outscores the highest in the next tier.
# 10 000 accommodates up to 9 999 geo partitions per tier.
_VARIANT_TIER_GAP = 10_000

# Maximum number of category variants produced by taxonomy-aware expansion.
# Kept at 8 to avoid plan explosion while covering semantic relatives.
_MAX_EXPANDED_VARIANTS = 8

# Minimum token length for tokenisation (avoids single-letter noise).
_MIN_TOKEN_LEN = 3

# Prefix lengths used for morphological root matching.
# 5-char prefix: primary check; catches "manuf..." (manufacturer/manufacturing).
# 4-char prefix: secondary check; catches "dent..." (dental/dentist).
#   A 4-char prefix match additionally requires that the prefix represents
#   ≥ _MATCH_PREFIX_FRACTION of EACH token's length, preventing coincidental
#   matches (e.g. "rest" in "restaurant" vs "restoration", where 4/10 = 40%).
_TOKEN_PREFIX_LEN_5 = 5
_TOKEN_PREFIX_LEN_4 = 4
_MATCH_PREFIX_FRACTION = 0.50

# Words stripped from category names before token-overlap scoring.
_CATEGORY_STOPWORDS = frozenset({
    "and", "or", "the", "a", "an", "of", "in", "for",
    "to", "at", "by", "with", "on", "per",
})

# Minimum string-similarity score (difflib ratio) for a base_variant to be
# retained when it has zero token overlap with the query.  Set above difflib's
# own cutoff (0.5) to exclude "Artist" / "Pet store" false matches for "Dentist"
# while retaining true specialist variants like "Orthodontist" (~0.74).
_BASE_VARIANT_SIM_THRESHOLD = 0.65

# ── Geo zone scoring ──────────────────────────────────────────────────────────
# Partition names are tokenised; score is assigned by the highest-priority
# matching set.  Score 3 = industrial (best B2B density), -1 = residential.

_GEO_INDUSTRIAL = frozenset({
    "gidc", "idc", "midc", "industrial", "estate", "cluster",
    "factory", "stice", "uda",
})
_GEO_COMMERCIAL = frozenset({
    "market", "commercial", "bazaar", "bazar", "chowk",
    "plaza", "trade", "apmc", "mandi", "business",
})
_GEO_RESIDENTIAL = frozenset({
    "colony", "society", "residency", "township", "housing",
    "vihar", "kunj", "apartments", "enclave",
})


# ── TypedDict ─────────────────────────────────────────────────────────────────


class SearchPlan(TypedDict):
    """A single fully-resolved, prioritised search entry."""

    search_query: str
    canonical_category: str
    geographic_partition: str
    original_city: str
    priority_score: float
    execution_order: int


# ── SearchPlanGenerator ───────────────────────────────────────────────────────


class SearchPlanGenerator:
    """Produces an ordered, deduplicated list of SearchPlan entries.

    Constructor injection of CategoryResolver and GeoResolver enables
    isolated testing without SQLite or network access.
    """

    def __init__(
        self,
        category_resolver: Optional[CategoryResolver] = None,
        geo_resolver: Optional[GeoResolver] = None,
    ) -> None:
        self._category_resolver = category_resolver or CategoryResolver()
        self._geo_resolver = geo_resolver or GeoResolver()

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        city: str,
        category: str,
        target_qualified_leads: int = 50,
    ) -> list[SearchPlan]:
        """Return a fully-ordered search plan for *city* and *category*.

        Returns an empty list if city or category is blank.
        """
        city = (city or "").strip()
        category = (category or "").strip()
        if not city or not category:
            return []

        # Step 1: taxonomy-aware category variants; primary at index 0.
        variants = self._resolve_variants(category)
        canonical = variants[0]

        # Step 2 + 3: geographic partitions ordered by business-density zone.
        partitions = self._resolve_partitions(city)

        # Step 4 + 5: Cartesian product with deterministic priority.
        plans = self._build_plans(variants, partitions, city, canonical)

        # Step 6: remove plans with equivalent normalised search intent.
        plans = _deduplicate(plans)

        # Step 7: assign 1-based execution_order after deduplication.
        return [
            SearchPlan(**{**plan, "execution_order": idx + 1})
            for idx, plan in enumerate(plans)
        ]

    # ── Private ───────────────────────────────────────────────────────────────

    def _resolve_variants(self, category: str) -> list[str]:
        """Return ordered category variants for *category*.

        When the full taxonomy is available (real CategoryResolver), enhances
        difflib output with token-overlap expansion against all_categories.
        When a stub resolver is injected (testing), falls back to get_variants()
        output unchanged — preserving all Phase 2 test contracts.
        """
        base = self._category_resolver.get_variants(category)

        if hasattr(self._category_resolver, "all_categories"):
            expanded = _expand_from_taxonomy(
                category,
                base,
                self._category_resolver.all_categories,
            )
            return expanded if expanded else [category]

        # Stub resolver path — no taxonomy access; use base as-is.
        return base if base else [category]

    def _resolve_partitions(self, city: str) -> list[str]:
        """Return partitions ordered by business-density zone priority.

        GeoResolver output is stable-sorted: industrial/commercial zones first,
        residential zones last, equal-score zones preserve resolver order.
        """
        partitions = self._geo_resolver.get_neighbourhoods(city)
        if not partitions:
            return [city]
        return _prioritize_geo_partitions(partitions)

    def _build_plans(
        self,
        variants: list[str],
        partitions: list[str],
        city: str,
        canonical: str,
    ) -> list[SearchPlan]:
        """Generate ordered Cartesian combinations with deterministic priority."""
        n_variants = len(variants)
        n_partitions = len(partitions)
        plans: list[SearchPlan] = []

        for v_idx, variant in enumerate(variants):
            # Each variant tier is separated by _VARIANT_TIER_GAP so the
            # worst geo entry in tier N always outscores the best in tier N+1.
            tier_base = (n_variants - v_idx) * _VARIANT_TIER_GAP

            for g_idx, partition in enumerate(partitions):
                # Position within tier reflects geo zone order (already sorted).
                priority = float(tier_base + (n_partitions - g_idx))
                plans.append(
                    SearchPlan(
                        search_query=f"{variant} in {partition}",
                        canonical_category=canonical,
                        geographic_partition=partition,
                        original_city=city,
                        priority_score=priority,
                        execution_order=0,  # placeholder; set after dedup
                    )
                )

        return plans


# ── Module-level helpers ──────────────────────────────────────────────────────


def _tokenize_category(text: str) -> frozenset[str]:
    """Tokenise a category name into significant lowercase words.

    Splits on whitespace and common punctuation, removes stopwords,
    and drops tokens shorter than _MIN_TOKEN_LEN.
    """
    words = re.split(r"[\s\-/&,()]+", text.lower())
    return frozenset(
        w for w in words
        if len(w) >= _MIN_TOKEN_LEN and w not in _CATEGORY_STOPWORDS
    )


def _tokens_match(tok1: str, tok2: str) -> bool:
    """True if two tokens share the same morphological root.

    Three tests applied in order:
      1. Exact equality.
      2. One token is a prefix of the other (e.g. "machine" ⊂ "machinery").
      3. 5-char prefix equality: catches "manuf..." series
         (manufacturer / manufacturing) without triggering on short coincidences.
      4. 4-char prefix equality WITH fraction gate: the 4-char prefix must
         represent ≥ _MATCH_PREFIX_FRACTION (50%) of each token's length.
         This admits "dent..."→dental/dentist (4/6=67%, 4/7=57%) while
         rejecting "rest..."→restaurant/restoration (4/10=40%, 4/11=36%).

    Both tokens must be ≥ 4 chars for any prefix test to apply.
    """
    if tok1 == tok2:
        return True
    if len(tok1) < _TOKEN_PREFIX_LEN_4 or len(tok2) < _TOKEN_PREFIX_LEN_4:
        return False
    shorter, longer = (tok1, tok2) if len(tok1) <= len(tok2) else (tok2, tok1)
    # Full prefix containment.
    if longer.startswith(shorter):
        return True
    # 5-char shared prefix.
    if (len(shorter) >= _TOKEN_PREFIX_LEN_5
            and tok1[:_TOKEN_PREFIX_LEN_5] == tok2[:_TOKEN_PREFIX_LEN_5]):
        return True
    # 4-char shared prefix — fraction gate guards against false positives.
    if tok1[:_TOKEN_PREFIX_LEN_4] == tok2[:_TOKEN_PREFIX_LEN_4]:
        frac1 = _TOKEN_PREFIX_LEN_4 / len(tok1)
        frac2 = _TOKEN_PREFIX_LEN_4 / len(tok2)
        return min(frac1, frac2) >= _MATCH_PREFIX_FRACTION
    return False


def _token_overlap_score(query_tokens: frozenset[str], cat_tokens: frozenset[str]) -> int:
    """Count how many query tokens match at least one token in *cat_tokens*."""
    score = 0
    for qt in query_tokens:
        if any(_tokens_match(qt, ct) for ct in cat_tokens):
            score += 1
    return score


def _expand_from_taxonomy(
    query: str,
    base_variants: list[str],
    all_categories: list[str],
) -> list[str]:
    """Return up to _MAX_EXPANDED_VARIANTS variants ordered by relevance.

    Strategy:
      1. Canonical variant (base_variants[0] or raw query) is always first.
      2. Remaining base_variants (difflib string-similarity matches) follow.
      3. Additional taxonomy categories with positive token-overlap fill the
         remaining slots, sorted by (overlap_score desc, string_sim desc,
         name asc) for full determinism.

    All returned strings originate from the Google Business Category taxonomy.
    No categories are invented; no free-form synonyms are generated.
    """
    query_tokens = _tokenize_category(query)
    canonical = base_variants[0] if base_variants else query

    if not query_tokens:
        return base_variants if base_variants else [query]

    # Score every taxonomy category by token overlap + string similarity.
    scored: list[tuple[str, int, float]] = []
    for cat in all_categories:
        cat_tokens = _tokenize_category(cat)
        overlap = _token_overlap_score(query_tokens, cat_tokens)
        if overlap == 0:
            continue
        sim = difflib.SequenceMatcher(None, query.lower(), cat.lower()).ratio()
        scored.append((cat, overlap, sim))

    # Fully deterministic ordering: most overlap first, then most similar,
    # then alphabetical so identical scores produce identical output.
    scored.sort(key=lambda x: (-x[1], -x[2], x[0]))

    result: list[str] = []
    seen: set[str] = set()

    # 1. Canonical first.
    result.append(canonical)
    seen.add(canonical)

    # 2. Remaining difflib variants — only if semantically plausible.
    # A variant passes if it has positive token overlap with the query (primary)
    # or if its string similarity exceeds _BASE_VARIANT_SIM_THRESHOLD (fallback,
    # catches specialist near-synonyms like "Orthodontist" for "Dentist").
    for v in base_variants[1:]:
        if v not in seen and len(result) < _MAX_EXPANDED_VARIANTS:
            v_tokens = _tokenize_category(v)
            has_overlap = _token_overlap_score(query_tokens, v_tokens) > 0
            has_sim = (
                difflib.SequenceMatcher(None, query.lower(), v.lower()).ratio()
                >= _BASE_VARIANT_SIM_THRESHOLD
            )
            if has_overlap or has_sim:
                result.append(v)
                seen.add(v)

    # 3. Token-overlap matches from the full taxonomy.
    for cat, _overlap, _sim in scored:
        if len(result) >= _MAX_EXPANDED_VARIANTS:
            break
        if cat not in seen:
            result.append(cat)
            seen.add(cat)

    return result if result else [query]


def _geo_zone_score(partition: str) -> int:
    """Assign a business-density score to a geographic partition name.

    Scores:
      3 — industrial / manufacturing zone (highest B2B density)
      2 — commercial / market district
      0 — general / mixed urban (default)
     -1 — residential zone (lowest B2B density)

    Matching is token-based against the lowercased partition name so
    "GIDC Estate" and "Industrial Area" both score 3.
    """
    tokens = frozenset(re.split(r"\W+", partition.lower()))
    if tokens & _GEO_INDUSTRIAL:
        return 3
    if tokens & _GEO_COMMERCIAL:
        return 2
    if tokens & _GEO_RESIDENTIAL:
        return -1
    return 0


def _prioritize_geo_partitions(partitions: list[str]) -> list[str]:
    """Re-order partitions by descending zone score using a stable sort.

    Stability is essential: partitions with equal zone scores preserve the
    GeoResolver's original order, so test contracts that supply synthetic
    partition lists (["First", "Second", "Third"]) remain unaffected.
    """
    return sorted(partitions, key=lambda p: -_geo_zone_score(p))


def _normalize_query(query: str) -> str:
    """Normalise a search query for deduplication comparison.

    Strips apostrophes/possessives, collapses whitespace, and lowercases.
    This catches near-duplicates that differ only in punctuation or spacing.
    """
    q = query.lower()
    q = re.sub(r"'s?\b", "", q)   # remove possessives
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _deduplicate(plans: list[SearchPlan]) -> list[SearchPlan]:
    """Remove plans with equivalent normalised search intent.

    First occurrence (highest priority) is always preserved.
    Normalisation catches: case differences, extra whitespace, apostrophes.
    """
    seen: set[str] = set()
    result: list[SearchPlan] = []
    for plan in plans:
        key = _normalize_query(plan["search_query"])
        if key not in seen:
            seen.add(key)
            result.append(plan)
    return result
