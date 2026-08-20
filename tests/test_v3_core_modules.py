import os
import tempfile
import pytest
from pathlib import Path

# Override DB path before importing DB modules to isolate test database
import leadforge.database

temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()
from leadforge.database import initialize_database  # noqa: E402
from leadforge.validator import BusinessValidator  # noqa: E402
from leadforge.confidence_engine import ConfidenceEngine  # noqa: E402
from leadforge.merge import BusinessMerger  # noqa: E402
from leadforge.execution_state import ScraperExecutionState  # noqa: E402
from leadforge.normalizer import canonical_phone  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown():
    mp = pytest.MonkeyPatch()
    mp.setattr(leadforge.database, "DB_PATH", temp_db_path)
    initialize_database()
    yield
    mp.undo()
    if temp_db_path.exists():
        try:
            os.remove(temp_db_path)
        except Exception:
            pass


def test_business_validator():
    validator = BusinessValidator()

    # 1. Valid operational business with website and phone.
    # google_primary_category is the SCRAPED category — validation never
    # compares the requested category against itself.
    biz_ok = {
        "name": "Test Clinic",
        "website": "https://testclinic.com",
        "phone": "+91 98765 43210",
        "business_status": "OPERATIONAL",
        "google_primary_category": "Dentist",
        "address": "Ahmedabad, Gujarat",
    }
    assert (
        validator.validate(biz_ok, target_city="Ahmedabad", target_category="Dentist")
        == "PASS"
    )

    # 2. Invalid business: empty name → specific reason NO_NAME
    biz_no_name = {
        "name": "",
        "website": "https://testclinic.com",
        "phone": "+91 98765 43210",
    }
    result = validator.validate(biz_no_name)
    assert result != "PASS"
    assert result == "NO_NAME"

    # 3. Invalid business: phone missing → specific reason NO_PHONE
    biz_no_phone = {
        "name": "Test Clinic",
        "website": "https://testclinic.com",
        "phone": "",
        "business_status": "OPERATIONAL",
    }
    result = validator.validate(biz_no_phone)
    assert result != "PASS"
    assert result == "NO_PHONE"

    # 4. Invalid business: permanently closed → PERMANENTLY_CLOSED
    biz_closed = {
        "name": "Closed Shop",
        "phone": "+91 98765 43210",
        "business_status": "PERMANENTLY_CLOSED",
    }
    result = validator.validate(biz_closed)
    assert result != "PASS"
    assert result == "PERMANENTLY_CLOSED"

    # 5. no_website_only check → HAS_WEBSITE when filter active
    # (address + rating present so ghost-listing detection does not trigger)
    biz_with_site = {
        "name": "Site Shop",
        "phone": "+91 98765 43210",
        "website": "https://siteshop.com",
        "address": "SG Highway, Ahmedabad",
        "rating": 4.1,
    }
    result = validator.validate(biz_with_site, no_website_only=True)
    assert result != "PASS"
    assert result == "HAS_WEBSITE"
    assert validator.validate(biz_with_site, no_website_only=False) == "PASS"

    # 6. City mismatch → WRONG_CITY
    biz_diff_city = {
        "name": "Test Clinic",
        "phone": "+91 98765 43210",
        "address": "Baroda, Gujarat",
    }
    result = validator.validate(biz_diff_city, target_city="Ahmedabad")
    assert result != "PASS"
    assert result == "WRONG_CITY"

    # 7. Category mismatch (scraped Google category differs) → WRONG_CATEGORY
    biz_diff_cat = {
        "name": "Test Clinic",
        "phone": "+91 98765 43210",
        "google_primary_category": "Restaurant",
    }
    result = validator.validate(biz_diff_cat, target_category="Dentist")
    assert result != "PASS"
    assert result == "WRONG_CATEGORY"


def test_validator_category_unverified():
    """Missing Google category evidence must reject as CATEGORY_UNVERIFIED,
    never fall back to comparing the requested category against itself."""
    validator = BusinessValidator()
    biz = {
        "name": "Test Clinic",
        "phone": "+91 98765 43210",
        "business_status": "OPERATIONAL",
        "address": "Navrangpura, Ahmedabad",
        "rating": 4.0,
        # requested-category echo must NOT be used as evidence:
        "category": "Dentist",
    }
    assert validator.validate(biz, target_category="Dentist") == "CATEGORY_UNVERIFIED"

    # Scraped categories list also counts as evidence
    biz["categories"] = '["Dental Clinic"]'
    assert validator.validate(biz, target_category="Dentist") == "PASS"


def test_validator_city_pin_prefix():
    """PIN-prefix mapping is authoritative; address comparison is fallback only."""
    validator = BusinessValidator()
    base = {
        "name": "Pin Test",
        "phone": "+91 98765 43210",
        "business_status": "OPERATIONAL",
        "rating": 4.0,
    }

    # Correct PIN prefix passes even when the city name is absent from the address
    biz_pin_ok = dict(base, address="12 GIDC Estate, Vatva, Gujarat 382445")
    assert validator.validate(biz_pin_ok, target_city="Ahmedabad") == "PASS"

    # Wrong PIN prefix fails even when the city name appears in the address
    biz_pin_wrong = dict(base, address="Ahmedabad Road, Surat, Gujarat 395003")
    assert validator.validate(biz_pin_wrong, target_city="Ahmedabad") == "WRONG_CITY"

    # No PIN in address → deterministic address-substring fallback
    biz_no_pin = dict(base, address="Navrangpura, Ahmedabad, Gujarat")
    assert validator.validate(biz_no_pin, target_city="Ahmedabad") == "PASS"

    # No address at all → NO_ADDRESS
    biz_no_addr = dict(base)
    assert validator.validate(biz_no_addr, target_city="Ahmedabad") == "NO_ADDRESS"

    # Custom pin_prefix_map is honoured
    biz_custom = dict(base, address="Somewhere 123456")
    assert (
        validator.validate(
            biz_custom, target_city="Testville", pin_prefix_map={"testville": ["123"]}
        )
        == "PASS"
    )


def test_validator_ghost_listing():
    """Businesses with no enrichment evidence at all must be rejected."""
    validator = BusinessValidator()
    ghost = {
        "name": "Ghost Biz",
        "phone": "+91 98765 43210",
        "business_status": "OPERATIONAL",
    }
    assert validator.validate(ghost) == "GHOST_LISTING"

    # A single enrichment field (opening hours) rescues the listing
    not_ghost = dict(ghost, opening_hours="Open 9 AM - 6 PM")
    assert validator.validate(not_ghost) == "PASS"


def test_validator_business_status():
    """Default accepted status is OPERATIONAL; TEMPORARILY_CLOSED must fail
    unless explicitly allowed."""
    validator = BusinessValidator()
    biz = {
        "name": "Temp Closed Biz",
        "phone": "+91 98765 43210",
        "business_status": "TEMPORARILY_CLOSED",
        "address": "Maninagar, Ahmedabad",
        "rating": 3.9,
    }
    assert validator.validate(biz) == "WRONG_STATUS"
    assert validator.validate(biz, allow_temporarily_closed=True) == "PASS"

    biz_unknown = dict(biz, business_status="UNKNOWN")
    assert validator.validate(biz_unknown) == "WRONG_STATUS"


def test_validator_strict_rating_review_filters():
    """Enabled min_rating/min_reviews filters must fail on missing values."""
    validator = BusinessValidator()
    biz = {
        "name": "No Signals Biz",
        "phone": "+91 98765 43210",
        "business_status": "OPERATIONAL",
        "address": "Bopal, Ahmedabad",
    }
    assert validator.validate(biz, min_rating=4.0) == "BELOW_MIN_RATING"
    assert validator.validate(biz, min_reviews=10) == "BELOW_MIN_REVIEWS"

    biz_with_signals = dict(biz, rating=4.5, review_count=25)
    assert (
        validator.validate(biz_with_signals, min_rating=4.0, min_reviews=10) == "PASS"
    )
    assert validator.validate(biz_with_signals, min_rating=4.8) == "BELOW_MIN_RATING"
    assert validator.validate(biz_with_signals, min_reviews=100) == "BELOW_MIN_REVIEWS"


def test_extract_place_id_variants():
    """Place ID extraction must support all known Google Maps URL variants."""
    from leadforge.utils import extract_place_id

    hex_url = (
        "https://www.google.com/maps/place/Biz/data=!4m2!3m1!1s0x395e87a2:0x9999999"
    )
    assert extract_place_id(hex_url) == "0x395e87a2:0x9999999"

    ftid_url = "https://www.google.com/maps/place/Biz?ftid=0x395e87a2:0xabc123"
    assert extract_place_id(ftid_url) == "0x395e87a2:0xabc123"

    chij_data_url = "https://www.google.com/maps/place/Biz/data=!4m5!3m4!19sChIJd8BlQ2BZwokRAFUEcm_qrcA"
    assert extract_place_id(chij_data_url) == "ChIJd8BlQ2BZwokRAFUEcm_qrcA"

    place_id_param = (
        "https://www.google.com/maps/place/?q=place_id:ChIJN1t_tDeuEmsRUsoyG83frY4"
    )
    assert extract_place_id(place_id_param) == "ChIJN1t_tDeuEmsRUsoyG83frY4"

    assert extract_place_id("https://www.google.com/maps/place/NoId") is None
    assert extract_place_id("") is None


def test_collector_aria_parsing():
    """Rating and review count must parse deterministically from aria-labels."""
    from leadforge.collector import (
        _rating_from_aria,
        _reviews_from_aria,
        _with_english_locale,
    )

    labels = ["Menu", "4.6 stars 1,234 Reviews", "Photos"]
    assert _rating_from_aria(labels) == 4.6
    assert _reviews_from_aria(labels) == 1234

    # Exact review-button label takes priority
    labels_exact = ["987 reviews", "4.6 stars 1,234 Reviews"]
    assert _reviews_from_aria(labels_exact) == 987

    # Implausible / absent values → None (never invented)
    assert _rating_from_aria(["0.5 stars"]) is None
    assert _rating_from_aria([]) is None
    assert _reviews_from_aria(["Open now"]) is None

    # hl=en appended without clobbering existing params
    assert _with_english_locale("https://maps.google.com/maps/place/X").endswith(
        "?hl=en"
    )
    assert _with_english_locale("https://maps.google.com/place/X?q=1").endswith(
        "&hl=en"
    )
    url_with_hl = "https://maps.google.com/place/X?hl=en"
    assert _with_english_locale(url_with_hl) == url_with_hl


def test_execution_state_quality_tracking():
    """Tier-1 counters, extraction rates, and confidence averaging must be
    deterministic and surfaced through metrics and the rejection breakdown."""
    state = ScraperExecutionState(limit=10)

    # New rejection reasons route to dedicated counters
    state.record_rejection("CATEGORY_UNVERIFIED")
    state.record_rejection("GHOST_LISTING")
    state.record_rejection("NO_ADDRESS")
    breakdown = state.rejection_breakdown()
    assert breakdown["category_unverified"] == 1
    assert breakdown["ghost_listing"] == 1
    assert breakdown["no_address"] == 1

    # Tier-1 counters are plain dict increments (shared with the collector)
    state.tier1_rejections["NO_PHONE"] += 3
    state.tier1_rejections["HAS_WEBSITE"] += 1
    assert breakdown != state.rejection_breakdown()  # tier1 included in breakdown
    assert state.rejection_breakdown()["tier1"]["NO_PHONE"] == 3

    # Extraction rates
    state.extraction_stats["attempts"] = 4
    state.extraction_stats["rating"] = 4
    state.extraction_stats["reviews"] = 2
    rates = state.extraction_rates()
    assert rates["rating"] == 1.0
    assert rates["reviews"] == 0.5
    assert rates["address"] == 0.0

    # Confidence averaging: HIGH=1.0, MEDIUM=0.5
    state.record_confidence("HIGH")
    state.record_confidence("MEDIUM")
    assert state.avg_confidence() == pytest.approx(0.75)

    metrics = state.to_metrics()
    assert metrics["tier1_rejections"]["NO_PHONE"] == 3
    assert metrics["extraction_rates"]["rating"] == 1.0
    assert metrics["avg_confidence"] == pytest.approx(0.75)


def test_confidence_engine():
    engine = ConfidenceEngine()
    weights = {
        "confidence_high": 60.0,
        "confidence_medium": 30.0,
        "min_signals_high": 4,
        "min_signals_medium": 2,
    }

    # 1. High confidence: high score, sufficient positive signals and completeness
    level, rationale = engine.calculate(65.0, 5, 0.6, weights)
    assert level == "HIGH"

    # 2. Low data completeness guard (< 0.25) forces LOW confidence
    level, rationale = engine.calculate(65.0, 5, 0.2, weights)
    assert level == "LOW"
    assert "Data completeness" in rationale

    # 3. Medium confidence: score >= 30, at least 2 positive signals
    level, rationale = engine.calculate(35.0, 2, 0.4, weights)
    assert level == "MEDIUM"

    # 4. Low confidence: low score or low signal count
    level, rationale = engine.calculate(20.0, 1, 0.4, weights)
    assert level == "LOW"


def test_business_merger():
    merger = BusinessMerger()

    existing = {
        "google_place_id": "",
        "display_phone": "+919876543210",
        "website_domain": "test.com",
        "rating": 4.0,
        "review_count": 50,
        "business_status": "OPERATIONAL",
    }

    incoming = {
        "google_place_id": "google_place_123",
        "phone": "+919876543210",  # no change
        "website_domain": "test.com",  # no change
        "rating": 4.5,  # conflict
        "review_count": 55,  # conflict
        "business_status": "TEMPORARILY_CLOSED",  # conflict
    }

    updates, conflicts = merger.merge(existing, incoming)

    # google_place_id was empty in existing → filled; business_status uses overwrite=True → updated
    assert updates.get("google_place_id") == "google_place_123"
    assert updates.get("business_status") == "TEMPORARILY_CLOSED"

    # rating and review_count differ → logged as conflicts (not auto-overwritten)
    conflict_fields = [c[0] for c in conflicts]
    assert "rating" in conflict_fields
    assert "review_count" in conflict_fields
    assert "business_status" not in conflict_fields


def test_execution_state():
    state = ScraperExecutionState(limit=5)

    assert state.limit == 5
    assert state.search_budget == 15
    assert state.should_continue() is True

    # Increment qualified count to limit
    for _ in range(5):
        state.increment_qualified()
    assert state.should_continue() is False
    assert state.termination_reason == "REQUESTED_COUNT_REACHED"

    # Test budget exhaust
    state2 = ScraperExecutionState(limit=5, search_budget=3)
    state2.consume_budget()
    state2.consume_budget()
    assert state2.should_continue() is True
    state2.consume_budget()
    assert state2.should_continue() is False
    assert state2.termination_reason == "SEARCH_BUDGET_EXHAUSTED"

    # Test search space exhaustion detection
    state3 = ScraperExecutionState(limit=10)
    state3.mark_search_space_exhausted()
    assert state3.should_continue() is False
    assert state3.termination_reason == "SEARCH_SPACE_EXHAUSTED"

    # Test rejection counters
    state4 = ScraperExecutionState(limit=10)
    state4.record_rejection("NO_PHONE")
    state4.record_rejection("NO_PHONE")
    state4.record_rejection("HAS_WEBSITE")
    state4.record_rejection("WRONG_CITY")
    state4.record_duplicate()
    breakdown = state4.rejection_breakdown()
    assert breakdown["rejected_total"] == 4
    assert breakdown["no_phone"] == 2
    assert breakdown["has_website"] == 1
    assert breakdown["wrong_city"] == 1
    assert breakdown["duplicates"] == 1


def test_canonical_phone():
    """canonical_phone() must produce the same string for all representations of the same number."""
    # All of these are the same phone number
    variants = [
        "+91 98765 43210",
        "+919876543210",
        "919876543210",
        "9876543210",
        "98765 43210",
        "98765-43210",
        "+91-98765-43210",
        "(91)9876543210",
    ]
    canonical = canonical_phone(variants[0])
    assert canonical == "919876543210"
    for v in variants:
        assert canonical_phone(v) == canonical, (
            f"Variant '{v}' produced wrong canonical: {canonical_phone(v)}"
        )

    # 00-prefix international format
    assert canonical_phone("00919876543210") == "919876543210"

    # Empty / None-like inputs
    assert canonical_phone("") == ""
    assert canonical_phone(None) == ""

    # Short / invalid → not expanded
    result = canonical_phone("12345")
    assert result == "12345"  # less than 10 digits, no expansion


def test_duplicate_detection_same_phone_different_formats():
    """check_duplicate() must recognise the same phone in different formats as one business."""
    from leadforge.repositories.lead import SQLiteLeadRepository

    repo = SQLiteLeadRepository()

    lead_a = {
        "name": "Phase2 Test Biz Alpha",
        "phone": "+91 77777 11111",  # display format
        "website": "",
        "website_domain": "",
        "address": "Ahmedabad",
        "area": "SG Highway",
        "category": "Manufacturers",
        "source_url": "https://maps.google.com/place/p2alpha",
        "rating": 4.0,
        "review_count": 20,
        "business_status": "OPERATIONAL",
        "opening_hours": "",
        "categories": "[]",
        "email": "",
        "social_links": "",
        "city": "Ahmedabad",
        "google_place_id": None,
        "normalized_phone": None,
    }

    from leadforge.opportunity_engine import OpportunityIntelligenceEngine

    engine = OpportunityIntelligenceEngine()
    opp_drafts, maturity = engine.evaluate_opportunities(lead_a)
    repo.save_new_qualified_lead(lead_a, opp_drafts, maturity, "test_phase2_dedup.xlsx")

    # Same phone, different formats — must all be detected as duplicate
    same_phone_variants = [
        "+91 77777 11111",
        "+917777711111",
        "7777711111",
        "917777711111",
    ]
    for variant in same_phone_variants:
        assert repo.check_duplicate(
            google_place_id=None, name="Phase2 Test Biz Alpha", phone=variant
        ), f"Phone variant '{variant}' was not detected as a duplicate"


def test_campaign_idempotency():
    """A business scraped twice for the same campaign must produce exactly one leads row."""
    from leadforge.database import get_db_connection
    from leadforge.repositories.lead import SQLiteLeadRepository
    from leadforge.opportunity_engine import OpportunityIntelligenceEngine

    repo = SQLiteLeadRepository()
    engine = OpportunityIntelligenceEngine()

    lead = {
        "name": "Phase2 Idempotent Corp",
        "phone": "+91 88888 22222",
        "website": "",
        "website_domain": "",
        "address": "Surat",
        "area": "Ring Road",
        "category": "Manufacturers",
        "source_url": "https://maps.google.com/place/p2idem",
        "rating": 3.8,
        "review_count": 10,
        "business_status": "OPERATIONAL",
        "opening_hours": "",
        "categories": "[]",
        "email": "",
        "social_links": "",
        "city": "Surat",
        "google_place_id": None,
    }
    campaign = "idempotency_test.xlsx"

    # First insert: new qualified lead
    opp_drafts, maturity = engine.evaluate_opportunities(lead)
    biz_id = repo.save_new_qualified_lead(lead, opp_drafts, maturity, campaign)

    # Second insert: simulate duplicate detection path calling save_merged_lead
    existing = repo._get_existing_business_by_id(biz_id)
    updates, conflicts = BusinessMerger().merge(existing, lead)
    repo.save_merged_lead(biz_id, updates, conflicts, lead, campaign)

    # Exactly one leads row must exist for this business+campaign pair
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM leads WHERE business_id = ? AND campaign_name = ?",
            (biz_id, campaign),
        )
        count = cursor.fetchone()[0]
    finally:
        conn.close()

    assert count == 1, f"Expected 1 leads row, got {count} (idempotency broken)"


@pytest.mark.anyio
async def test_scraper_orchestrator_mock():
    from unittest.mock import AsyncMock, MagicMock, patch
    from leadforge.control_plane import SearchOrchestrator

    orchestrator = SearchOrchestrator()

    mock_links = [
        "https://google.com/maps/place/UniqueBiz/data=!4m2!3m1!1s0x395e87a2:0x7777777"
    ]
    mock_raw_details = [
        {
            "name": "Super Unique V3 Enterprise",
            "phone": "+91 99999 11111",
            "website": "",
            "address": "12 GIDC Estate, Ahmedabad",
            "area": "GIDC",
            "category": "Metal Works",
            "source_url": "https://www.google.com/maps/place/UniqueBiz/data=!4m2!3m1!1s0x395e87a2:0x7777777",
            "rating": 4.2,
            "review_count": 45,
            "business_status": "Operational",
            "opening_hours": "Open 9 AM - 6 PM",
            "categories": '["Metal Works", "Steel Fabrication"]',
        }
    ]

    # Phase 3: mock the shared Playwright browser so no real Chromium is launched.
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=MagicMock())
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()
    mock_pw = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()
    mock_ap_instance = MagicMock()
    mock_ap_instance.start = AsyncMock(return_value=mock_pw)
    mock_async_playwright = MagicMock(return_value=mock_ap_instance)

    # Phase 3 generator signatures include context= and no_website_only=.
    async def _mock_discovery_stream(
        city, category, limit=50, settings_cache=None, context=None
    ):
        for url in mock_links:
            yield url

    async def _mock_stream(
        links,
        category,
        city="",
        settings_cache=None,
        context=None,
        no_website_only=False,
        website_filter="ALL",
        tier1_stats=None,
        extraction_stats=None,
    ):
        for detail in mock_raw_details:
            yield detail

    with (
        patch("leadforge.control_plane.async_playwright", mock_async_playwright),
        patch(
            "leadforge.control_plane.discover_business_links_stream",
            _mock_discovery_stream,
        ),
        patch("leadforge.control_plane.collect_business_details_stream", _mock_stream),
    ):
        results = await orchestrator.run_qualified_campaign(
            city="Ahmedabad",
            category="Metal Works",
            limit=1,
            no_website_only=True,
            campaign_name="test_campaign_plane.xlsx",
        )

        assert len(results) == 1
        assert results[0]["name"] == "Super Unique V3 Enterprise"
        assert results[0]["score"] > 0


def test_adaptive_budget_reduces_on_high_yield():
    """update_adaptive_budget() must tighten the budget when yield exceeds expectation."""
    state = ScraperExecutionState(limit=10, search_budget=40)
    assert state._initial_budget == 40

    # Fewer than YIELD_SAMPLE_INTERVAL visits — no change yet
    assert state.update_adaptive_budget() is False

    # Simulate 60% yield (3 qualified out of 5 visited)
    for _ in range(5):
        state.consume_budget()
    for _ in range(3):
        state.increment_qualified()

    changed = state.update_adaptive_budget()
    assert changed is True, "Budget should be reduced when yield is better than assumed"
    assert state.search_budget < 40, "Adaptive budget must be less than initial 40"
    # estimated_remaining = ceil((10-3)/0.6) + 5 ≈ 17 → new budget = 5+17 = 22
    assert state.search_budget <= 22


def test_adaptive_budget_no_change_on_zero_yield():
    """update_adaptive_budget() must not reduce budget when no leads qualify yet."""
    state = ScraperExecutionState(limit=10, search_budget=40)
    for _ in range(5):
        state.consume_budget()
    # zero qualifications → yield = 0 → should not modify budget
    changed = state.update_adaptive_budget()
    assert changed is False
    assert state.search_budget == 40


def test_campaign_metrics_accuracy():
    """Runtime metric methods must compute correct values from state counters."""
    state = ScraperExecutionState(limit=10, search_budget=40)

    # Simulate 6 visited, 3 qualified, 2 rejected, 1 duplicate
    for _ in range(6):
        state.consume_budget()
    for _ in range(3):
        state.increment_qualified()
    state.record_rejection("NO_PHONE")
    state.record_rejection("HAS_WEBSITE")
    state.record_duplicate()

    import pytest

    assert state.qualification_yield() == pytest.approx(3 / 6)
    assert state.elapsed() >= 0.0
    assert state.avg_seconds_per_business() >= 0.0
    assert state.avg_seconds_per_qualified_lead() >= 0.0

    # estimated_remaining: remaining=7, yield=0.5 → 7/0.5+5=19 → 19 visits
    assert state.estimated_remaining_visits() == 19

    metrics = state.to_metrics()
    assert metrics["qualified"] == 3
    assert metrics["visited"] == 6
    assert metrics["rejected"] == 2
    assert metrics["duplicates"] == 1
    assert metrics["yield_rate"] == pytest.approx(0.5)
    assert metrics["adaptive_budget"] == 40
    assert metrics["initial_budget"] == 40
    assert metrics["active_termination_condition"] == "IN_PROGRESS"
    assert "elapsed_sec" in metrics
    assert "estimated_remaining_visits" in metrics
    assert "estimated_remaining_sec" in metrics
