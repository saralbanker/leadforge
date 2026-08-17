import os
import sqlite3
import tempfile
import pytest
from leadforge.database import (
    initialize_database,
    append_event,
    uuidv7,
)
from leadforge.utils import append_event as utils_append_event, uuidv7 as utils_uuidv7


@pytest.fixture
def temp_db():
    """Provides a temporary SQLite database initialized with all schemas and migrations."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    # Apply canonical schema script
    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "schema.sql"
    )
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    
    yield conn, path

    conn.close()
    if os.path.exists(path):
        os.remove(path)


def test_uuidv7_lexicographical_ordering():
    """Verify that generated UUIDv7 identifiers are lexicographically sortable."""
    id1 = uuidv7()
    id2 = utils_uuidv7()
    assert len(id1) == 36
    assert len(id2) == 36
    assert id1 != id2


def test_append_event_success(temp_db):
    """Verify append_event writes valid event_store records."""
    conn, _ = temp_db
    event_id = append_event(
        event_type="LEAD_CREATED",
        entity_type="Lead",
        entity_id="01907de3-bc42-7c89-8d76-5a507db4f111",
        payload={"campaign": "Test Campaign", "score": 95},
        event_version=1,
        conn=conn,
    )
    assert len(event_id) == 36

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM event_store WHERE event_id = ?", (event_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == event_id  # event_id
    assert row[1] == "LEAD_CREATED"  # event_type
    assert row[2] == "Lead"  # entity_type
    assert row[3] == "01907de3-bc42-7c89-8d76-5a507db4f111"  # entity_id
    assert "Test Campaign" in row[5]  # payload
    assert row[6] == 1  # event_version
    assert row[7] == 0  # processed_status


def test_utils_append_event_wrapper(temp_db):
    """Verify utils.append_event delegates correctly."""
    conn, _ = temp_db
    event_id = utils_append_event(
        event_type="EMAIL_SENT",
        entity_type="Opportunity",
        entity_id="01907de3-bc42-7c89-8d76-5a507db4f222",
        payload={"recipient": "prospect@example.com"},
        conn=conn,
    )
    cursor = conn.cursor()
    cursor.execute("SELECT event_type FROM event_store WHERE event_id = ?", (event_id,))
    assert cursor.fetchone()[0] == "EMAIL_SENT"


def test_event_store_immutability_update(temp_db):
    """Verify that UPDATE operations on event_store raise database errors via trigger."""
    conn, _ = temp_db
    event_id = append_event(
        event_type="STATE_CHANGED",
        entity_type="Lead",
        entity_id="01907de3-bc42-7c89-8d76-5a507db4f333",
        payload={"from": "OPEN", "to": "QUALIFIED"},
        conn=conn,
    )

    with pytest.raises(sqlite3.Error) as exc_info:
        conn.execute(
            "UPDATE event_store SET processed_status = 1 WHERE event_id = ?",
            (event_id,),
        )
    assert "immutable" in str(exc_info.value).lower()


def test_event_store_immutability_delete(temp_db):
    """Verify that DELETE operations on event_store raise database errors via trigger."""
    conn, _ = temp_db
    event_id = append_event(
        event_type="STATE_CHANGED",
        entity_type="Lead",
        entity_id="01907de3-bc42-7c89-8d76-5a507db4f444",
        payload={"from": "OPEN", "to": "QUALIFIED"},
        conn=conn,
    )

    with pytest.raises(sqlite3.Error) as exc_info:
        conn.execute(
            "DELETE FROM event_store WHERE event_id = ?",
            (event_id,),
        )
    assert "immutable" in str(exc_info.value).lower()


def test_append_event_payload_edge_cases(temp_db):
    """Verify handling of None, string, dict, list, and non-serializable payloads."""
    conn, _ = temp_db

    # None payload
    id1 = append_event("TEST_1", "Entity", "123", payload=None, conn=conn)
    cursor = conn.cursor()
    cursor.execute("SELECT payload FROM event_store WHERE event_id = ?", (id1,))
    assert cursor.fetchone()[0] == "{}"

    # String payload
    id2 = append_event("TEST_2", "Entity", "123", payload="raw_string_data", conn=conn)
    cursor.execute("SELECT payload FROM event_store WHERE event_id = ?", (id2,))
    assert cursor.fetchone()[0] == "raw_string_data"

    # Non-serializable object payload (uses default=str)
    class CustomObj:
        def __str__(self):
            return "CustomObjValue"

    id3 = append_event("TEST_3", "Entity", "123", payload={"obj": CustomObj()}, conn=conn)
    cursor.execute("SELECT payload FROM event_store WHERE event_id = ?", (id3,))
    assert "CustomObjValue" in cursor.fetchone()[0]


def test_event_store_indexes(temp_db):
    """Verify idx_events_type_entity and idx_events_unprocessed indexes exist."""
    conn, _ = temp_db
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_events_%'"
    )
    indexes = [row[0] for row in cursor.fetchall()]
    assert "idx_events_type_entity" in indexes
    assert "idx_events_unprocessed" in indexes


def test_domain_event_types_integration(temp_db):
    """Verify all 9 candidate domain events can be appended and queried by type."""
    conn, _ = temp_db
    events_to_test = [
        ("BUSINESS_DISCOVERED", "Business", "b1", {"name": "Biz 1"}),
        ("OPPORTUNITY_CREATED", "Opportunity", "o1", {"title": "Opp 1"}),
        ("WEBSITE_AUDITED", "Business", "b1", {"has_website": True}),
        ("EMAIL_DISCOVERED", "Business", "b1", {"discovered_email": "a@b.com"}),
        ("EMAIL_DRAFT_GENERATED", "EmailDraft", "d1", {"subject": "Subj"}),
        ("EMAIL_APPROVED", "EmailDraft", "d1", {"status": "APPROVED"}),
        ("EMAIL_REJECTED", "EmailDraft", "d2", {"status": "REJECTED"}),
        ("EMAIL_SENT", "EmailDraft", "d1", {"sent_at": "2026-07-21T00:00:00Z"}),
        ("EMAIL_SEND_FAILED", "EmailDraft", "d3", {"error_message": "Timeout"}),
    ]

    for event_type, entity_type, entity_id, payload in events_to_test:
        event_id = append_event(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            conn=conn,
        )
        assert event_id is not None

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM event_store")
    assert cursor.fetchone()[0] == 9

