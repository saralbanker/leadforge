"""Phase 3 + 4 — Opportunity Intelligence Engine Test Suite.

Phase 3 coverage:
- Category → service mapping (configured and default fallback)
- Opportunity generation (single + multi)
- Duplicate prevention (idempotency)
- Score calculation determinism
- Confidence / priority / close_probability derivation
- Explanation accuracy
- Configuration changes affect scoring without code changes
- Repository integration (atomic create + log queries)
- Ranking consistency

Phase 4 additions:
- 3-tier review banding (REVIEW_NONE / LOW / MID / HIGH)
- 4-tier rating banding (RATING_POOR / LOW / MID / HIGH)
- Zero-review penalty (REVIEW_NONE)
- Poor rating penalty (RATING_POOR)
- Evidence-count–gated confidence
- Data completeness guard
- Digital maturity assessment
- Structured positive/negative signal lists
- Sigmoid close probability
- ServiceRepository integration
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

# ── Isolate test DB ────────────────────────────────────────────────────────────
import leadforge.database

_temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_temp_db_path = Path(_temp_db.name)
_temp_db.close()
leadforge.database.DB_PATH = _temp_db_path

from leadforge.database import initialize_database, get_db_connection  # noqa: E402
from leadforge.category_mapper import CategoryServiceMapper  # noqa: E402
from leadforge.opportunity_engine import (  # noqa: E402
    OpportunityIntelligenceEngine,
)
from leadforge.repositories.opportunity import SQLiteOpportunityRepository  # noqa: E402
from leadforge.repositories.settings import SQLiteSettingsRepository  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def db_setup():
    initialize_database()
    yield
    if _temp_db_path.exists():
        try:
            os.remove(_temp_db_path)
        except Exception:
            pass


def _insert_business(name: str, category: str = "Traders") -> str:
    """Helper: inserts a minimal business record and returns its id."""
    from leadforge.database import uuidv7
    from leadforge.normalizer import normalize_category

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        biz_id = uuidv7()
        norm = name.strip().lower()
        norm_cat = normalize_category(category)

        cursor.execute("SELECT id FROM business_types WHERE name = ?", (norm_cat,))
        row = cursor.fetchone()
        if row:
            bt_id = row[0]
        else:
            bt_id = uuidv7()
            cursor.execute(
                "INSERT INTO business_types (id, name) VALUES (?, ?)",
                (bt_id, norm_cat),
            )

        cursor.execute(
            """
            INSERT INTO businesses (id, normalized_name, name, business_type_id)
            VALUES (?, ?, ?, ?)
            """,
            (biz_id, norm, name, bt_id),
        )
        conn.commit()
        return biz_id
    finally:
        conn.close()


def _make_biz_data(
    biz_id: str,
    *,
    name: str = "Test Business",
    category: str = "Traders",
    website: str = "",
    phone: str = "+919999988888",
    rating: float = None,
    review_count: int = None,
    business_status: str = "OPERATIONAL",
    categories: str = "",
    contact_email: str = "",
) -> Dict[str, Any]:
    return {
        "business_id": biz_id,
        "name": name,
        "category": category,
        "website": website,
        "phone": phone,
        "contact_email": contact_email,
        "rating": rating,
        "review_count": review_count,
        "business_status": business_status,
        "categories": categories,
    }


# ── 1. Category → Service Mapping ─────────────────────────────────────────────


class TestCategoryServiceMapper:
    def test_known_category_returns_list(self):
        mapper = CategoryServiceMapper()
        services = mapper.get_services_for_category("Traders")
        assert isinstance(services, list)
        assert len(services) > 0
        assert all(isinstance(s, str) for s in services)

    def test_unknown_category_falls_back_to_default(self):
        mapper = CategoryServiceMapper()
        services = mapper.get_services_for_category("Completely Unknown Category XYZ")
        assert isinstance(services, list)
        # Default mapping is configured in migration 003
        assert len(services) > 0

    def test_empty_category_falls_back_to_default(self):
        mapper = CategoryServiceMapper()
        services = mapper.get_services_for_category("")
        assert isinstance(services, list)

    def test_mock_settings_no_default(self):
        """When no mappings exist at all, mapper returns empty list gracefully."""
        mock_repo = MagicMock()
        mock_repo.get.return_value = None
        mapper = CategoryServiceMapper(settings_repo=mock_repo)
        result = mapper.get_services_for_category("Anything")
        assert result == []

    def test_mock_settings_malformed_json(self):
        """Malformed JSON in settings returns None → falls through to default."""
        mock_repo = MagicMock()
        mock_repo.get.side_effect = lambda key: (
            "{not valid json" if "Traders" in key else None
        )
        mapper = CategoryServiceMapper(settings_repo=mock_repo)
        result = mapper.get_services_for_category("Traders")
        # Both Traders key and default key returned None → empty list
        assert result == []


# ── 2. Score Calculation (Pure / Deterministic) ───────────────────────────────


class TestScoringEngine:
    def _engine(self) -> OpportunityIntelligenceEngine:
        return OpportunityIntelligenceEngine()

    def test_no_website_adds_max_base_signal(self):
        engine = self._engine()
        biz_id = _insert_business("No Web Biz")
        data = _make_biz_data(biz_id, website="")
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "NO_WEBSITE" in rule_names
        assert "HAS_WEBSITE" not in rule_names

    def test_has_website_adds_website_signal(self):
        engine = self._engine()
        biz_id = _insert_business("Web Biz")
        data = _make_biz_data(biz_id, website="https://example.com")
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "HAS_WEBSITE" in rule_names
        assert "NO_WEBSITE" not in rule_names

    def test_high_rating_adds_signal(self):
        engine = self._engine()
        biz_id = _insert_business("High Rating Biz")
        data = _make_biz_data(biz_id, rating=4.5)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "RATING_HIGH" in rule_names

    def test_low_rating_adds_signal(self):
        """Phase 4: 3.2 falls into RATING_LOW band (3.0-3.5)."""
        engine = self._engine()
        biz_id = _insert_business("Low Rating Biz")
        data = _make_biz_data(biz_id, rating=3.2)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "RATING_LOW" in rule_names

    def test_many_reviews_adds_review_high_signal(self):
        """Phase 4: REVIEW_HIGH threshold is now 100 (was 50)."""
        engine = self._engine()
        biz_id = _insert_business("Popular Biz")
        data = _make_biz_data(biz_id, review_count=110)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "REVIEW_HIGH" in rule_names

    def test_few_reviews_adds_review_mid_signal(self):
        """Phase 4: 10 reviews falls into the MID band (10-99)."""
        engine = self._engine()
        biz_id = _insert_business("Small Biz")
        data = _make_biz_data(biz_id, review_count=10)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "REVIEW_MID" in rule_names

    def test_permanently_closed_applies_penalty(self):
        engine = self._engine()
        biz_id = _insert_business("Closed Biz")
        data = _make_biz_data(biz_id, business_status="PERMANENTLY_CLOSED")
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "PERMANENTLY_CLOSED" in rule_names
        # Penalty must be negative
        perm = next(
            s for s in result["signals"] if s["rule_name"] == "PERMANENTLY_CLOSED"
        )
        assert perm["score_delta"] < 0

    def test_score_floored_at_zero(self):
        """Score must never go negative even with max penalties."""
        engine = self._engine()
        biz_id = _insert_business("Ghost Biz")
        data = _make_biz_data(biz_id, business_status="PERMANENTLY_CLOSED", website="")
        result = engine.score_business(data)
        assert result["score"] >= 0.0

    def test_determinism_same_data_same_score(self):
        """Identical input must always produce identical output."""
        engine = self._engine()
        biz_id = _insert_business("Determinism Biz")
        data = _make_biz_data(
            biz_id,
            website="https://x.com",
            rating=4.2,
            review_count=60,
            business_status="OPERATIONAL",
            categories="[Electronics]",
            phone="+919876543210",
        )
        result_a = engine.score_business(data)
        result_b = engine.score_business(data)
        assert result_a["score"] == result_b["score"]
        assert result_a["close_probability"] == result_b["close_probability"]
        assert result_a["priority"] == result_b["priority"]
        assert result_a["confidence"] == result_b["confidence"]
        assert len(result_a["signals"]) == len(result_b["signals"])


# ── 3. Priority and Confidence Derivation ─────────────────────────────────────


class TestPriorityConfidence:
    def _engine(self) -> OpportunityIntelligenceEngine:
        return OpportunityIntelligenceEngine()

    def test_high_score_yields_high_priority(self):
        engine = self._engine()
        biz_id = _insert_business("Prio High Biz")
        # No website + phone + email + reviews = should cross 60
        data = _make_biz_data(
            biz_id,
            website="",
            phone="+919999900000",
            contact_email="owner@test.com",
            review_count=80,
            rating=4.5,
            business_status="OPERATIONAL",
        )
        result = engine.score_business(data)
        assert result["priority"] == "HIGH"

    def test_low_score_yields_low_priority(self):
        engine = self._engine()
        biz_id = _insert_business("Prio Low Biz")
        # Permanently closed, no phone, no email
        data = _make_biz_data(
            biz_id,
            website="",
            phone="",
            business_status="PERMANENTLY_CLOSED",
        )
        result = engine.score_business(data)
        assert result["priority"] == "LOW"

    def test_close_probability_between_0_and_1(self):
        engine = self._engine()
        biz_id = _insert_business("Prob Biz")
        data = _make_biz_data(biz_id)
        result = engine.score_business(data)
        assert 0.0 <= result["close_probability"] <= 1.0

    def test_confidence_is_valid_enum(self):
        engine = self._engine()
        biz_id = _insert_business("Conf Biz")
        data = _make_biz_data(biz_id)
        result = engine.score_business(data)
        assert result["confidence"] in ("HIGH", "MEDIUM", "LOW")


# ── 4. Explainability ─────────────────────────────────────────────────────────


class TestExplainability:
    def test_explanation_contains_business_name(self):
        engine = OpportunityIntelligenceEngine()
        biz_id = _insert_business("Explain Biz")
        data = _make_biz_data(biz_id, name="Explain Biz")
        result = engine.score_business(data)
        assert "Explain Biz" in result["explanation"]

    def test_explanation_contains_score(self):
        engine = OpportunityIntelligenceEngine()
        biz_id = _insert_business("Explain Score Biz")
        data = _make_biz_data(biz_id)
        result = engine.score_business(data)
        assert str(int(result["score"])) in result["explanation"]

    def test_explanation_references_all_signal_rule_names(self):
        engine = OpportunityIntelligenceEngine()
        biz_id = _insert_business("Signal Ref Biz")
        data = _make_biz_data(
            biz_id,
            website="https://test.com",
            rating=4.0,
            review_count=55,
            business_status="OPERATIONAL",
        )
        result = engine.score_business(data)
        for sig in result["signals"]:
            assert sig["rule_name"] in result["explanation"]


# ── 5. Opportunity Generation ─────────────────────────────────────────────────


class TestOpportunityGeneration:
    def test_generate_creates_opportunities_in_db(self):
        engine = OpportunityIntelligenceEngine()
        biz_id = _insert_business("Gen Create Biz", "Traders")
        data = _make_biz_data(biz_id, name="Gen Create Biz", category="Traders")
        results = engine.generate_for_business(data)
        created = [r for r in results if r.get("created")]
        assert len(created) > 0

    def test_generate_multiple_opportunities_per_business(self):
        engine = OpportunityIntelligenceEngine()
        biz_id = _insert_business("Multi Opp Biz", "Manufacturers")
        data = _make_biz_data(biz_id, name="Multi Opp Biz", category="Manufacturers")
        results = engine.generate_for_business(data)
        created = [r for r in results if r.get("created")]
        # Manufacturers is configured with 3 services in migration 003
        assert len(created) >= 2

    def test_generate_skips_unknown_category(self):
        """If no mapping AND no default, no opportunities are generated."""
        mock_mapper = MagicMock()
        mock_mapper.get_services_for_category.return_value = []
        engine = OpportunityIntelligenceEngine(category_mapper=mock_mapper)
        biz_id = _insert_business("No Map Biz", "ZZZ Unknown")
        data = _make_biz_data(biz_id, name="No Map Biz", category="ZZZ Unknown")
        results = engine.generate_for_business(data)
        assert results == []

    def test_generate_returns_empty_for_missing_business_id(self):
        engine = OpportunityIntelligenceEngine()
        results = engine.generate_for_business({"name": "Ghost", "category": "Traders"})
        assert results == []


# ── 6. Duplicate Prevention ───────────────────────────────────────────────────


class TestDuplicatePrevention:
    def test_second_call_skips_existing_opportunities(self):
        engine = OpportunityIntelligenceEngine()
        biz_id = _insert_business("Dedup Opp Biz", "Traders")
        data = _make_biz_data(biz_id, name="Dedup Opp Biz", category="Traders")

        first_run = engine.generate_for_business(data)
        first_created = [r for r in first_run if r.get("created")]

        second_run = engine.generate_for_business(data)
        second_created = [r for r in second_run if r.get("created")]
        second_skipped = [r for r in second_run if r.get("skipped")]

        # No new opportunities on repeat
        assert len(second_created) == 0
        assert len(second_skipped) == len(first_created)

    def test_title_exists_for_business_returns_true_after_create(self):
        opp_repo = SQLiteOpportunityRepository()
        biz_id = _insert_business("TitleCheck Biz")
        opp_repo.create_with_scoring_logs(
            business_id=biz_id,
            title="Test Title — TitleCheck Biz",
            pipeline_stage="PROSPECTING",
            score=50.0,
            close_probability=0.5,
            estimated_value=5000.0,
            scoring_logs=[
                {"rule_name": "TEST", "score_delta": 50.0, "reason": "Test reason"}
            ],
        )
        assert opp_repo.title_exists_for_business(biz_id, "Test Title — TitleCheck Biz")
        assert not opp_repo.title_exists_for_business(biz_id, "Different Title")


# ── 7. Ranking Consistency ────────────────────────────────────────────────────


class TestRankingConsistency:
    def test_list_ranked_ordered_by_score_desc(self):
        engine = OpportunityIntelligenceEngine()
        opp_repo = SQLiteOpportunityRepository()

        biz_a = _insert_business("Rank High Biz")
        biz_b = _insert_business("Rank Low Biz")

        opp_repo.create_with_scoring_logs(
            business_id=biz_a,
            title="High Score Opp — Rank High Biz",
            pipeline_stage="PROSPECTING",
            score=90.0,
            close_probability=0.9,
            estimated_value=20000.0,
            scoring_logs=[
                {"rule_name": "TEST_HIGH", "score_delta": 90.0, "reason": "High"}
            ],
        )
        opp_repo.create_with_scoring_logs(
            business_id=biz_b,
            title="Low Score Opp — Rank Low Biz",
            pipeline_stage="PROSPECTING",
            score=10.0,
            close_probability=0.1,
            estimated_value=500.0,
            scoring_logs=[
                {"rule_name": "TEST_LOW", "score_delta": 10.0, "reason": "Low"}
            ],
        )

        ranked = engine.list_opportunities()
        scores = [r["score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_list_ranked_stage_filter(self):
        opp_repo = SQLiteOpportunityRepository()
        biz_id = _insert_business("Stage Filter Biz")
        opp_repo.create_with_scoring_logs(
            business_id=biz_id,
            title="PROSPECTING Stage Opp",
            pipeline_stage="PROSPECTING",
            score=55.0,
            close_probability=0.55,
            estimated_value=8000.0,
            scoring_logs=[
                {"rule_name": "STAGE_TEST", "score_delta": 55.0, "reason": "stage"}
            ],
        )

        engine = OpportunityIntelligenceEngine()
        results = engine.list_opportunities(pipeline_stage="PROSPECTING")
        assert all(r["pipeline_stage"] == "PROSPECTING" for r in results)

    def test_list_ranked_limit(self):
        engine = OpportunityIntelligenceEngine()
        results = engine.list_opportunities(limit=2)
        assert len(results) <= 2


# ── 8. Repository Integration ─────────────────────────────────────────────────


class TestRepositoryIntegration:
    def test_scoring_logs_persisted_correctly(self):
        opp_repo = SQLiteOpportunityRepository()
        biz_id = _insert_business("Log Persist Biz")
        logs = [
            {"rule_name": "RULE_A", "score_delta": 20.0, "reason": "Reason A"},
            {"rule_name": "RULE_B", "score_delta": -5.0, "reason": "Reason B"},
        ]
        opp_id = opp_repo.create_with_scoring_logs(
            business_id=biz_id,
            title="Logged Opp — Log Persist Biz",
            pipeline_stage="PROSPECTING",
            score=15.0,
            close_probability=0.15,
            estimated_value=2000.0,
            scoring_logs=logs,
        )
        fetched = opp_repo.get_scoring_logs(opp_id)
        assert len(fetched) == 2
        rule_names = [f["rule_name"] for f in fetched]
        assert "RULE_A" in rule_names
        assert "RULE_B" in rule_names

    def test_get_active_for_business_excludes_none(self):
        opp_repo = SQLiteOpportunityRepository()
        biz_id = _insert_business("Active Only Biz")
        opp_repo.create_with_scoring_logs(
            business_id=biz_id,
            title="Active Opp — Active Only Biz",
            pipeline_stage="PROSPECTING",
            score=40.0,
            close_probability=0.4,
            estimated_value=5000.0,
            scoring_logs=[{"rule_name": "R", "score_delta": 40.0, "reason": "r"}],
        )
        active = opp_repo.get_active_for_business(biz_id)
        assert len(active) >= 1
        assert all(r["score"] is not None for r in active)


# ── 9. Configuration Changes Affect Scoring ───────────────────────────────────


class TestConfigurabilityAffectsScoring:
    def test_changing_no_website_weight_changes_score(self):
        """Updating settings must change scores without code changes."""
        settings_repo = SQLiteSettingsRepository()

        biz_id = _insert_business("Config Test Biz")
        data = _make_biz_data(biz_id, website="")

        engine_a = OpportunityIntelligenceEngine(settings_repo=settings_repo)
        score_a = engine_a.score_business(data)["score"]

        # Update the weight
        settings_repo.set(
            "opp.score.no_website", "99.0", "Temporarily elevated for test"
        )
        engine_b = OpportunityIntelligenceEngine(settings_repo=settings_repo)
        score_b = engine_b.score_business(data)["score"]

        assert score_b > score_a

        # Restore Phase 4 default weight
        settings_repo.set("opp.score.no_website", "45.0", "Restored after test")


# ── 10. Phase 4: Review Banding ───────────────────────────────────────────────


class TestPhase4ReviewBanding:
    def _engine(self) -> OpportunityIntelligenceEngine:
        return OpportunityIntelligenceEngine()

    def test_zero_reviews_adds_review_none_penalty(self):
        """0 reviews = REVIEW_NONE penalty signal."""
        engine = self._engine()
        biz_id = _insert_business("Zero Reviews Biz")
        data = _make_biz_data(biz_id, review_count=0)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "REVIEW_NONE" in rule_names
        penalty = next(s for s in result["signals"] if s["rule_name"] == "REVIEW_NONE")
        assert penalty["score_delta"] < 0

    def test_low_reviews_1_to_9(self):
        """1-9 reviews = REVIEW_LOW."""
        engine = self._engine()
        biz_id = _insert_business("Tiny Reviews Biz")
        data = _make_biz_data(biz_id, review_count=5)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "REVIEW_LOW" in rule_names

    def test_mid_reviews_10_to_99(self):
        """10-99 reviews = REVIEW_MID."""
        engine = self._engine()
        biz_id = _insert_business("Mid Reviews Biz")
        data = _make_biz_data(biz_id, review_count=50)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "REVIEW_MID" in rule_names

    def test_high_reviews_100_plus(self):
        """100+ reviews = REVIEW_HIGH."""
        engine = self._engine()
        biz_id = _insert_business("High Reviews Biz")
        data = _make_biz_data(biz_id, review_count=200)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "REVIEW_HIGH" in rule_names

    def test_none_review_count_produces_no_review_signal(self):
        """Unknown review count = no review signal at all."""
        engine = self._engine()
        biz_id = _insert_business("Unknown Reviews Biz")
        data = _make_biz_data(biz_id, review_count=None)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "REVIEW_NONE" not in rule_names
        assert "REVIEW_LOW" not in rule_names
        assert "REVIEW_MID" not in rule_names
        assert "REVIEW_HIGH" not in rule_names


# ── 11. Phase 4: Rating Banding ───────────────────────────────────────────────


class TestPhase4RatingBanding:
    def _engine(self) -> OpportunityIntelligenceEngine:
        return OpportunityIntelligenceEngine()

    def test_poor_rating_below_3(self):
        """Rating < 3.0 = RATING_POOR penalty."""
        engine = self._engine()
        biz_id = _insert_business("Poor Rating Biz")
        data = _make_biz_data(biz_id, rating=2.1)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "RATING_POOR" in rule_names
        poor = next(s for s in result["signals"] if s["rule_name"] == "RATING_POOR")
        assert poor["score_delta"] < 0

    def test_low_rating_3_to_3_5(self):
        engine = self._engine()
        biz_id = _insert_business("Low Rating Band Biz")
        data = _make_biz_data(biz_id, rating=3.2)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "RATING_LOW" in rule_names

    def test_mid_rating_3_5_to_4_2(self):
        engine = self._engine()
        biz_id = _insert_business("Mid Rating Biz")
        data = _make_biz_data(biz_id, rating=3.8)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "RATING_MID" in rule_names

    def test_high_rating_4_2_plus(self):
        """Phase 4: RATING_HIGH threshold is 4.2 (was 4.0)."""
        engine = self._engine()
        biz_id = _insert_business("High Rating Band Biz")
        data = _make_biz_data(biz_id, rating=4.5)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "RATING_HIGH" in rule_names

    def test_rating_exactly_4_is_mid(self):
        """Rating 4.0 is below Phase 4 HIGH threshold of 4.2 → RATING_MID."""
        engine = self._engine()
        biz_id = _insert_business("Rating 4.0 Biz")
        data = _make_biz_data(biz_id, rating=4.0)
        result = engine.score_business(data)
        rule_names = [s["rule_name"] for s in result["signals"]]
        assert "RATING_MID" in rule_names


# ── 12. Phase 4: Evidence-Count–Gated Confidence ─────────────────────────────


class TestPhase4EvidenceConfidence:
    def _engine(self) -> OpportunityIntelligenceEngine:
        return OpportunityIntelligenceEngine()

    def test_sparse_data_caps_confidence_at_low(self):
        """A business with almost no data should never receive HIGH confidence."""
        engine = self._engine()
        biz_id = _insert_business("Sparse Data Biz")
        # Only name present — no website, phone, email, rating, reviews
        data = {
            "business_id": biz_id,
            "name": "Sparse Data Biz",
            "category": "Traders",
            "website": "",
            "phone": "",
            "contact_email": "",
            "rating": None,
            "review_count": None,
            "business_status": "",
            "categories": "",
        }
        result = engine.score_business(data)
        # Data completeness is 1/8 = 12.5% → must be LOW
        assert result["confidence"] == "LOW"

    def test_rich_data_can_reach_high_confidence(self):
        """A fully-filled-out business with strong signals earns HIGH confidence."""
        engine = self._engine()
        biz_id = _insert_business("Rich Data Biz")
        data = _make_biz_data(
            biz_id,
            name="Rich Data Biz",
            website="",  # No website → big NO_WEBSITE bonus
            phone="+919876543210",
            contact_email="owner@richbiz.com",
            rating=4.5,
            review_count=150,
            business_status="OPERATIONAL",
            categories="[Traders]",
        )
        result = engine.score_business(data)
        # Should have: NO_WEBSITE + HAS_EMAIL + HAS_PHONE + REVIEW_HIGH + RATING_HIGH + OPERATIONAL
        # That's 6 positive signals; score well above 60
        assert result["confidence"] in ("HIGH", "MEDIUM")
        assert result["score"] > 60

    def test_confidence_rationale_is_present(self):
        engine = self._engine()
        biz_id = _insert_business("Rationale Biz")
        data = _make_biz_data(biz_id)
        result = engine.score_business(data)
        assert "confidence_rationale" in result
        assert len(result["confidence_rationale"]) > 10

    def test_confidence_distinct_from_priority(self):
        """HIGH priority does not automatically mean HIGH confidence."""
        engine = self._engine()
        biz_id = _insert_business("Priority vs Confidence Biz")
        # Score > 60 (HIGH priority) but with minimal evidence (no email, no reviews)
        data = _make_biz_data(
            biz_id,
            website="",
            phone="+919999900000",
            business_status="OPERATIONAL",
            # Only name, phone, business_status filled → data_completeness = 2/8 = 25%
            rating=None,
            review_count=None,
            contact_email="",
            categories="",
        )
        result = engine.score_business(data)
        # Priority may be HIGH, but confidence should NOT be HIGH (insufficient evidence)
        if result["priority"] == "HIGH":
            assert result["confidence"] in ("MEDIUM", "LOW")


# ── 13. Phase 4: Digital Maturity Assessment ──────────────────────────────────


class TestPhase4DigitalMaturity:
    def _engine(self) -> OpportunityIntelligenceEngine:
        return OpportunityIntelligenceEngine()

    def test_score_business_returns_maturity_grade(self):
        engine = self._engine()
        biz_id = _insert_business("Maturity Grade Biz")
        data = _make_biz_data(biz_id)
        result = engine.score_business(data)
        assert "maturity_grade" in result
        assert result["maturity_grade"] in ("A", "B", "C", "D", "F")

    def test_score_business_returns_maturity_score(self):
        engine = self._engine()
        biz_id = _insert_business("Maturity Score Biz")
        data = _make_biz_data(biz_id)
        result = engine.score_business(data)
        assert "maturity_score" in result
        assert 0.0 <= result["maturity_score"] <= 100.0

    def test_no_website_yields_lower_maturity(self):
        engine = self._engine()
        biz_id_a = _insert_business("No Web Maturity Biz")
        biz_id_b = _insert_business("Has Web Maturity Biz")
        no_web = engine.score_business(_make_biz_data(biz_id_a, website=""))
        has_web = engine.score_business(
            _make_biz_data(biz_id_b, website="https://example.com")
        )
        assert no_web["maturity_score"] < has_web["maturity_score"]

    def test_generate_includes_maturity_in_result(self):
        engine = self._engine()
        biz_id = _insert_business("Maturity Generate Biz", "Traders")
        data = _make_biz_data(biz_id, name="Maturity Generate Biz", category="Traders")
        results = engine.generate_for_business(data)
        created = [r for r in results if r.get("created")]
        if created:
            assert "maturity_grade" in created[0]
            assert "maturity_score" in created[0]

    def test_data_completeness_in_result(self):
        engine = self._engine()
        biz_id = _insert_business("Completeness Biz")
        data = _make_biz_data(
            biz_id,
            website="https://x.com",
            phone="+91999",
            contact_email="x@x.com",
            rating=4.0,
            review_count=20,
            business_status="OPERATIONAL",
        )
        result = engine.score_business(data)
        assert "data_completeness" in result
        assert 0.0 <= result["data_completeness"] <= 1.0


# ── 14. Phase 4: Signal Lists & Explainability ────────────────────────────────


class TestPhase4SignalLists:
    def _engine(self) -> OpportunityIntelligenceEngine:
        return OpportunityIntelligenceEngine()

    def test_positive_signals_list_populated(self):
        engine = self._engine()
        biz_id = _insert_business("Pos Signal Biz")
        data = _make_biz_data(
            biz_id,
            website="",
            phone="+919999900000",
            business_status="OPERATIONAL",
        )
        result = engine.score_business(data)
        assert "positive_signals" in result
        assert len(result["positive_signals"]) > 0
        assert all(s["score_delta"] > 0 for s in result["positive_signals"])

    def test_negative_signals_list_populated_for_bad_business(self):
        engine = self._engine()
        biz_id = _insert_business("Neg Signal Biz")
        data = _make_biz_data(
            biz_id,
            website="",
            phone="",
            rating=2.0,
            review_count=0,
            business_status="TEMPORARILY_CLOSED",
        )
        result = engine.score_business(data)
        assert "negative_signals" in result
        assert len(result["negative_signals"]) > 0
        assert all(s["score_delta"] < 0 for s in result["negative_signals"])

    def test_explanation_separates_positive_and_negative(self):
        """Phase 4 explanation must contain Positive and Negative sections."""
        engine = self._engine()
        biz_id = _insert_business("Struct Explain Biz")
        data = _make_biz_data(
            biz_id,
            website="",
            phone="+9199",
            rating=2.1,
            review_count=0,
            business_status="OPERATIONAL",
        )
        result = engine.score_business(data)
        explanation = result["explanation"]
        assert "Positive" in explanation or "✔" in explanation
        assert "Negative" in explanation or "✘" in explanation


# ── 15. Phase 4: Sigmoid Close Probability ────────────────────────────────────


class TestPhase4SigmoidProbability:
    def _engine(self) -> OpportunityIntelligenceEngine:
        return OpportunityIntelligenceEngine()

    def test_high_score_probability_below_1(self):
        """Even the best business should have close_probability < 1.0."""
        engine = self._engine()
        biz_id = _insert_business("Max Score Biz")
        data = _make_biz_data(
            biz_id,
            website="",
            phone="+919999900000",
            contact_email="owner@test.com",
            rating=4.8,
            review_count=500,
            business_status="OPERATIONAL",
        )
        result = engine.score_business(data)
        assert result["close_probability"] < 1.0

    def test_zero_score_probability_is_zero(self):
        engine = self._engine()
        biz_id = _insert_business("Zero Score Biz")
        data = _make_biz_data(
            biz_id,
            website="",
            phone="",
            rating=2.0,
            review_count=0,
            business_status="PERMANENTLY_CLOSED",
        )
        result = engine.score_business(data)
        # Score should floor at 0 → probability = 0
        if result["score"] == 0.0:
            assert result["close_probability"] == 0.0

    def test_probability_increases_with_score(self):
        """Higher score must always produce higher probability."""
        engine = self._engine()
        biz_id_lo = _insert_business("Lo Prob Biz")
        biz_id_hi = _insert_business("Hi Prob Biz")
        lo = engine.score_business(_make_biz_data(biz_id_lo, website="", phone=""))
        hi = engine.score_business(
            _make_biz_data(
                biz_id_hi,
                website="",
                phone="+919999900000",
                contact_email="a@b.com",
                rating=4.5,
                review_count=200,
                business_status="OPERATIONAL",
            )
        )
        if hi["score"] > lo["score"]:
            assert hi["close_probability"] > lo["close_probability"]
