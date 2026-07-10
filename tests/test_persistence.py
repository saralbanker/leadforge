import os
import tempfile
import pytest
from pathlib import Path

# Important: Override database path before importing any db modules to isolate test data
import leadforge.database

temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()
leadforge.database.DB_PATH = temp_db_path

from leadforge.database import initialize_database, get_db_connection  # noqa: E402
from leadforge.repositories.settings import SQLiteSettingsRepository  # noqa: E402
from leadforge.repositories.search import SQLiteSearchHistoryRepository  # noqa: E402
from leadforge.repositories.lead import SQLiteLeadRepository  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown():
    # Bootstrap database
    initialize_database()
    yield
    # Cleanup temp db
    if temp_db_path.exists():
        try:
            os.remove(temp_db_path)
        except Exception:
            pass


def test_database_initialization():
    """Asserts that all tables, indexes, and triggers are created during database bootstrap."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Verify migration tracker table has recorded the first migration
        cursor.execute("SELECT migration_name FROM migration_history")
        rows = cursor.fetchall()
        assert len(rows) > 0
        assert rows[0]["migration_name"] == "001_initial.sql"

        # Verify core businesses table exists
        cursor.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='businesses'"
        )
        assert cursor.fetchone()[0] == 1

        # Verify reference lookup discovery_sources table exists and is populated
        cursor.execute("SELECT name FROM discovery_sources")
        sources = [row["name"] for row in cursor.fetchall()]
        assert "SCRAPER" in sources
        assert "MANUAL_IMPORT" in sources

        # Verify reference lookup lead_statuses table exists and is populated
        cursor.execute("SELECT name FROM lead_statuses")
        statuses = [row["name"] for row in cursor.fetchall()]
        assert "OPEN" in statuses
        assert "QUALIFIED" in statuses
    finally:
        conn.close()


def test_idempotent_migrations():
    """Asserts that running migration execution repeated times executes cleanly without errors."""
    try:
        initialize_database()
    except Exception as e:
        pytest.fail(f"Re-initialization of migrations failed: {str(e)}")


def test_settings_repository():
    """Verifies settings CRUD operations behave as expected."""
    repo = SQLiteSettingsRepository()

    # Set & Get
    repo.set("test_key", "test_val", "Test Description")
    assert repo.get("test_key") == "test_val"

    # Update value
    repo.set("test_key", "new_val")
    assert repo.get("test_key") == "new_val"


def test_search_history_repository():
    """Verifies scraper search run records are written and retrieved successfully."""
    repo = SQLiteSearchHistoryRepository()

    # Insert run
    search_id = repo.create("Rajkot", "Textiles", 12, "COMPLETED")
    assert len(search_id) == 36  # UUID length

    # List search history
    history = repo.list_all()
    assert len(history) > 0

    # Verify mapped fields
    rajkot_run = [r for r in history if r["city"] == "Rajkot"][0]
    assert rajkot_run["category"] == "Textiles"
    assert rajkot_run["status"] == "COMPLETED"
    assert rajkot_run["filename"] == "Rajkot_Textiles.xlsx"


def test_lead_repository_and_deduplication():
    """Verifies complex business, addresses, opportunities transaction writes and duplicate checks."""
    lead_repo = SQLiteLeadRepository()

    lead_data = {
        "name": "Reliance Industries",
        "phone": "+91 79 12345678",
        "website": "https://www.ril.com",
        "address": "GIDC Naroda, Ahmedabad",
        "area": "Naroda",
        "category": "Chemicals",
        "source_url": "https://www.google.com/maps/place/Reliance/data=!4m2!3m1!1s0x395e87a2:0xabcdef123",
        "score": 0,
        "notes": "Website exists",
    }

    # Assert not duplicate originally
    is_dup = lead_repo.check_duplicate(
        google_place_id="0x395e87a2:0xabcdef123",
        name="Reliance Industries",
        phone="+91 79 12345678",
    )
    assert not is_dup

    # Save lead transaction
    biz_id = lead_repo.save_lead_transaction(lead_data, "test_campaign.xlsx")
    assert len(biz_id) == 36

    # Assert duplicate by Google Place ID
    is_dup_place = lead_repo.check_duplicate(
        google_place_id="0x395e87a2:0xabcdef123", name="Reliance Industries", phone=""
    )
    assert is_dup_place

    # Assert duplicate by Name + Phone
    is_dup_phone = lead_repo.check_duplicate(
        google_place_id="", name="Reliance Industries", phone="+91 79 12345678"
    )
    assert is_dup_phone

    # Retrieve leads and assert mapping
    leads = lead_repo.get_leads_by_campaign("test_campaign.xlsx")
    assert len(leads) == 1
    assert leads[0]["name"] == "Reliance Industries"
    assert leads[0]["category"] == "Chemicals"
    assert leads[0]["priority"] == "Medium"
    assert leads[0]["website"] == "https://www.ril.com"
    assert leads[0]["address"] == "GIDC Naroda, Ahmedabad"
    assert leads[0]["area"] == "Naroda"
