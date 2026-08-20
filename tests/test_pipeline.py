import os
import tempfile
import pytest
from pathlib import Path

# Override DB path before importing DB modules
import leadforge.database

temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()
from leadforge.database import initialize_database, get_db_connection  # noqa: E402
from leadforge.normalizer import (  # noqa: E402
    normalize_phone,
    normalize_website,
    normalize_domain,
    normalize_category,
    normalize_status,
)
from leadforge.repositories.settings import SQLiteSettingsRepository  # noqa: E402
from leadforge.repositories.search import SQLiteSearchHistoryRepository  # noqa: E402
from leadforge.repositories.lead import SQLiteLeadRepository  # noqa: E402


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


def test_normalization_rules():
    # Phone
    assert normalize_phone("+91 79 1234-5678") == "+917912345678"
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("919876543210") == "+919876543210"
    assert normalize_phone("") == ""

    # Website
    assert (
        normalize_website("google.com/search?q=test")
        == "https://google.com/search?q=test"
    )
    assert normalize_website("http://www.TEST.com/") == "http://www.test.com"
    assert normalize_website("") == ""

    # Domain
    assert (
        normalize_domain("https://sub.domain.co.in/path/to/page?query=1")
        == "sub.domain.co.in"
    )
    assert normalize_domain("http://www.google.com") == "google.com"

    # Category
    assert normalize_category("  chemical   manufacturers ") == "Chemical Manufacturers"
    assert normalize_category("") == ""

    # Status
    assert normalize_status("Temporarily Closed") == "TEMPORARILY_CLOSED"
    assert normalize_status("Permanently closed") == "PERMANENTLY_CLOSED"
    assert normalize_status("Open") == "OPERATIONAL"


def test_typed_settings():
    repo = SQLiteSettingsRepository()
    repo.set("TEST_INT", "42")
    repo.set("TEST_FLOAT", "3.14")
    repo.set("TEST_STR", "hello")

    assert repo.get_int("TEST_INT", 0) == 42
    assert repo.get_int("MISSING_INT", 100) == 100
    assert repo.get_int("TEST_STR", 10) == 10

    assert repo.get_float("TEST_FLOAT", 0.0) == 3.14
    assert repo.get_float("MISSING_FLOAT", 1.23) == 1.23

    assert repo.get_str("TEST_STR", "") == "hello"
    assert repo.get_str("MISSING_STR", "fallback") == "fallback"


def test_search_history_metrics():
    search_repo = SQLiteSearchHistoryRepository()

    search_id = search_repo.create(
        city="Baroda",
        category="Machinery",
        results_count=0,
        status="RUNNING",
        limit_requested=25,
        started_at="2026-07-04T12:00:00Z",
    )
    assert len(search_id) == 36

    # Verify RUNNING state
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status, limit_requested, started_at, scraper_version FROM search_history WHERE id = ?",
        (search_id,),
    )
    row = cursor.fetchone()
    assert row["status"] == "RUNNING"
    assert row["limit_requested"] == 25
    assert row["started_at"] == "2026-07-04T12:00:00Z"
    assert row["scraper_version"] == "2.0"
    conn.close()

    # Complete run
    search_repo.complete(
        search_id=search_id,
        results_count=15,
        new_count=10,
        updated_count=3,
        failed_count=2,
        duplicate_count=2,
        finished_at="2026-07-04T12:01:30Z",
        duration=90.0,
        status="COMPLETED",
        metadata='{"info": "test"}',
    )

    # Verify completed state
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM search_history WHERE id = ?", (search_id,))
    row = cursor.fetchone()
    assert row["status"] == "COMPLETED"
    assert row["results_count"] == 15
    assert row["new_businesses"] == 10
    assert row["updated_businesses"] == 3
    assert row["failed_businesses"] == 2
    assert row["duplicate_detections"] == 2
    assert row["execution_duration"] == 90.0
    assert row["finished_at"] == "2026-07-04T12:01:30Z"
    assert row["scraper_metadata"] == '{"info": "test"}'
    conn.close()


def test_deduplication_and_conflict_auditing():
    lead_repo = SQLiteLeadRepository()

    biz_a = {
        "name": "Mahavir Enterprise",
        "phone": "+91 99999 88888",
        "website": "https://mahavir.com",
        "address": "12 GIDC Estate, Ahmedabad",
        "area": "GIDC",
        "category": "Metal Works",
        "source_url": "https://www.google.com/maps/place/Mahavir/data=!4m2!3m1!1s0x395e87a2:0x9999999",
        "rating": 4.2,
        "review_count": 45,
        "business_status": "Operational",
        "opening_hours": "Open 9 AM - 6 PM",
        "categories": '["Metal Works", "Steel Fabrication"]',
        "score": 80,
        "notes": "Excellent opportunity",
    }

    # 1. First insert (new business)
    biz_id = lead_repo.save_lead_transaction(biz_a, "campaign_mahavir.xlsx")
    assert len(biz_id) == 36

    # 2. Match duplicate by Phone and check merge/enrich conflict checks
    biz_b = {
        "name": "Mahavir Enterprise",
        "phone": "+91-99999-88888",
        "website": "",  # empty, should not overwrite mahavir.com
        "address": "12 GIDC Estate, Ahmedabad",
        "area": "GIDC",
        "category": "Metal Works",
        "source_url": "https://www.google.com/maps/place/Mahavir/data=!4m2!3m1!1s0x395e87a2:0x9999999",
        "rating": 4.5,  # changed rating (conflict)
        "review_count": 50,  # changed reviews (conflict)
        "business_status": "Operational",
        "opening_hours": "Open 9 AM - 6 PM",
        "categories": '["Metal Works", "Steel Fabrication"]',
        "score": 85,
        "notes": "Rating improved",
    }

    biz_id_2 = lead_repo.save_lead_transaction(biz_b, "campaign_mahavir_v2.xlsx")
    assert biz_id_2 == biz_id

    # Verify that website in DB remains mahavir.com (not overwritten by empty string)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT website_url FROM digital_presences WHERE business_id = ?", (biz_id,)
    )
    assert cursor.fetchone()[0] == "https://mahavir.com"

    # Verify rating in DB remains 4.2 (preserved due to conflict rule)
    cursor.execute(
        "SELECT rating, review_count FROM businesses WHERE id = ?", (biz_id,)
    )
    row = cursor.fetchone()
    assert row["rating"] == 4.2
    assert row["review_count"] == 45

    # Verify conflict was recorded in audit_logs
    cursor.execute(
        "SELECT entity_id, before_state_json, after_state_json FROM audit_logs WHERE entity_id = ?",
        (biz_id,),
    )
    logs = cursor.fetchall()
    assert len(logs) > 0

    # Verify conflict was recorded in activity_timeline
    cursor.execute(
        "SELECT title, description FROM activity_timeline WHERE business_id = ? AND title = 'Data Conflict Detected'",
        (biz_id,),
    )
    timeline = cursor.fetchall()
    assert len(timeline) > 0
    assert "rating" in timeline[0]["description"]

    # Phase 3: engine generates 1+ opportunities per business (one per mapped service).
    # Duplicate prevention ensures repeat calls do not inflate the count.
    cursor.execute(
        "SELECT count(*) FROM opportunities WHERE business_id = ?", (biz_id,)
    )
    assert cursor.fetchone()[0] >= 1

    conn.close()
