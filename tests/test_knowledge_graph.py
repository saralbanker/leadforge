import os
import tempfile
import pytest
from leadforge.repositories.knowledge import SQLiteKnowledgeRepository
from leadforge.repositories.base import RepositoryException


@pytest.fixture
def knowledge_repo():
    """Fixture initializing temporary DB with Knowledge Graph schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    os.environ["LEADFORGE_DB_PATH"] = path

    from leadforge.database import initialize_database
    initialize_database()

    repo = SQLiteKnowledgeRepository()
    yield repo

    if os.path.exists(path):
        os.remove(path)


def test_industry_profile_crud(knowledge_repo):
    """Verify creation and retrieval of Industry Profiles."""
    profile = knowledge_repo.create_industry_profile(
        name="Dental Practice",
        code="IND_DENTAL",
        description="Private dental clinics and orthodontists",
        avg_contract_value=5000.0,
    )
    assert profile["id"] is not None
    assert profile["name"] == "Dental Practice"
    assert profile["code"] == "IND_DENTAL"
    assert profile["avg_contract_value"] == 5000.0

    fetched = knowledge_repo.get_industry_profile_by_code("IND_DENTAL")
    assert fetched is not None
    assert fetched["id"] == profile["id"]


def test_pain_pattern_creation_and_query(knowledge_repo):
    """Verify pain pattern creation associated with an industry profile."""
    profile = knowledge_repo.create_industry_profile(
        name="HVAC Services",
        code="IND_HVAC",
    )
    pain = knowledge_repo.create_pain_pattern(
        industry_profile_id=profile["id"],
        title="High Emergency Booking Abandonment",
        description="After-hours phone calls unanswered",
        severity="HIGH",
    )
    assert pain["id"] is not None

    pains = knowledge_repo.get_pain_patterns_by_industry(profile["id"])
    assert len(pains) == 1
    assert pains[0]["title"] == "High Emergency Booking Abandonment"


def test_offer_pain_mapping(knowledge_repo):
    """Verify mapping relationship between offer patterns and pain patterns."""
    profile = knowledge_repo.create_industry_profile(name="Legal", code="IND_LEGAL")
    pain = knowledge_repo.create_pain_pattern(profile["id"], "No Consultation Scheduling")
    offer = knowledge_repo.create_offer_pattern(
        profile["id"], "Automated Booking Portal", "Capture 24/7 client appointments", 2500.0
    )

    success = knowledge_repo.map_offer_to_pain(offer["id"], pain["id"], relevance_score=0.95)
    assert success is True


def test_unique_constraint_violation(knowledge_repo):
    """Verify duplicate Industry Profile code raises RepositoryException."""
    knowledge_repo.create_industry_profile(name="Plumbing 1", code="IND_PLUMB")
    with pytest.raises(RepositoryException):
        knowledge_repo.create_industry_profile(name="Plumbing 2", code="IND_PLUMB")


def test_cascade_delete(knowledge_repo):
    """Verify deleting an Industry Profile cascades to associated Pain Patterns."""
    profile = knowledge_repo.create_industry_profile(name="Roofing", code="IND_ROOF")
    pain = knowledge_repo.create_pain_pattern(profile["id"], "Storm Season Demand Overflow")

    # Manually delete industry profile via SQL
    from leadforge.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("DELETE FROM industry_profiles WHERE id = ?", (profile["id"],))
    conn.commit()

    pains = knowledge_repo.get_pain_patterns_by_industry(profile["id"])
    assert len(pains) == 0
    conn.close()


def test_knowledge_item_upsert(knowledge_repo):
    """Verify Knowledge Item key-value document persistence and updating."""
    item1 = knowledge_repo.set_knowledge_item("BENCHMARKS", "avg_conversion_dental", {"rate": 0.12})
    assert item1["value"]["rate"] == 0.12

    # Update same key
    item2 = knowledge_repo.set_knowledge_item("BENCHMARKS", "avg_conversion_dental", {"rate": 0.15})
    assert item2["value"]["rate"] == 0.15

    fetched = knowledge_repo.get_knowledge_item("avg_conversion_dental")
    assert fetched["value"]["rate"] == 0.15
