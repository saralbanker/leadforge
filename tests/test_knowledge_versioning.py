import os
import sqlite3
import tempfile
import pytest
from leadforge.repositories.knowledge import SQLiteKnowledgeRepository
from leadforge.repositories.base import RepositoryException


@pytest.fixture
def versioned_repo():
    """Fixture initializing temporary DB with migration history and versioning schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    os.environ["LEADFORGE_DB_PATH"] = path

    from leadforge.database import initialize_database
    initialize_database()

    repo = SQLiteKnowledgeRepository()
    yield repo

    if os.path.exists(path):
        os.remove(path)


def test_initial_version_creation(versioned_repo):
    """Verify initial version creation for a knowledge item."""
    v1 = versioned_repo.create_knowledge_item_version(
        key_name="dental_icp_definition",
        topic="TARGETING",
        value={"min_chairs": 3, "target_city": "Ahmedabad"},
        created_by="FOUNDER",
        status="DRAFT",
        change_reason="Initial baseline definition",
        confidence_score=0.9,
    )

    assert v1["id"] is not None
    assert v1["version_number"] == 1
    assert v1["previous_version_id"] is None
    assert v1["status"] == "DRAFT"
    assert v1["value"]["min_chairs"] == 3


def test_multiple_versions_and_activation(versioned_repo):
    """Verify creating v1, v2, activating v1, then activating v2."""
    v1 = versioned_repo.create_knowledge_item_version(
        key_name="hvac_pricing_tier",
        topic="PRICING",
        value={"tier": "STANDARD", "base_price": 1500.0},
        status="DRAFT",
    )
    v2 = versioned_repo.create_knowledge_item_version(
        key_name="hvac_pricing_tier",
        topic="PRICING",
        value={"tier": "PREMIUM", "base_price": 2500.0},
        status="DRAFT",
        change_reason="Updated ACV for summer campaign",
    )

    assert v2["version_number"] == 2
    assert v2["previous_version_id"] == v1["id"]

    # Initially no ACTIVE version
    active_none = versioned_repo.get_active_knowledge_item("hvac_pricing_tier")
    assert active_none is None

    # Activate v1
    v1_activated = versioned_repo.activate_knowledge_item_version(v1["id"])
    assert v1_activated["status"] == "ACTIVE"

    active_v1 = versioned_repo.get_active_knowledge_item("hvac_pricing_tier")
    assert active_v1["id"] == v1["id"]
    assert active_v1["value"]["base_price"] == 1500.0

    # Activate v2 (v1 should become DEPRECATED)
    v2_activated = versioned_repo.activate_knowledge_item_version(v2["id"])
    assert v2_activated["status"] == "ACTIVE"

    active_v2 = versioned_repo.get_active_knowledge_item("hvac_pricing_tier")
    assert active_v2["id"] == v2["id"]
    assert active_v2["value"]["base_price"] == 2500.0

    # Check v1 status in history is DEPRECATED
    v1_history = versioned_repo.get_knowledge_item_version_by_id(v1["id"])
    assert v1_history["status"] == "DEPRECATED"


def test_duplicate_active_version_prevention(versioned_repo):
    """Verify SQLite partial index prevents multiple ACTIVE versions for the same key_name."""
    v1 = versioned_repo.create_knowledge_item_version(
        key_name="single_active_test",
        topic="TEST",
        value={"val": 1},
        status="ACTIVE",
    )
    assert v1["status"] == "ACTIVE"

    # Direct SQL insertion attempting a second ACTIVE version for same key_name
    from leadforge.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()

    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO knowledge_item_versions (id, key_name, version_number, topic, value_json, created_at, status)
            VALUES ('test-id-2', 'single_active_test', 2, 'TEST', '{}', '2026-07-21T00:00:00Z', 'ACTIVE')
            """,
        )
    conn.close()


def test_historical_audit_retrieval(versioned_repo):
    """Verify retrieving full audit history ordered by version_number DESC."""
    key = "history_audit_key"
    versioned_repo.create_knowledge_item_version(key, "AUDIT", {"step": 1})
    versioned_repo.create_knowledge_item_version(key, "AUDIT", {"step": 2})
    versioned_repo.create_knowledge_item_version(key, "AUDIT", {"step": 3})

    history = versioned_repo.get_knowledge_item_history(key)
    assert len(history) == 3
    assert history[0]["version_number"] == 3
    assert history[1]["version_number"] == 2
    assert history[2]["version_number"] == 1


def test_draft_non_interference(versioned_repo):
    """Verify creating a new DRAFT version does not affect the currently ACTIVE version."""
    v1 = versioned_repo.create_knowledge_item_version(
        key_name="active_stability_key",
        topic="CORE",
        value={"stable": True},
        status="ACTIVE",
    )

    # Add a draft v2
    v2_draft = versioned_repo.create_knowledge_item_version(
        key_name="active_stability_key",
        topic="CORE",
        value={"stable": False},
        status="DRAFT",
    )
    assert v2_draft["status"] == "DRAFT"

    active = versioned_repo.get_active_knowledge_item("active_stability_key")
    assert active["id"] == v1["id"]
    assert active["value"]["stable"] is True
