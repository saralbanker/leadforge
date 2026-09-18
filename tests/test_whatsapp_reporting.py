"""Tests for WhatsApp reporting repository and server endpoints."""

from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from leadforge.repositories.whatsapp_reporting import (
    get_whatsapp_summary,
    get_whatsapp_db_path,
)
from leadforge.server import app


@pytest.fixture
def mock_whatsapp_db(tmp_path):
    """Creates a temporary mock whatsapp_outreach.db with known fixtures."""
    db_file = tmp_path / "whatsapp_outreach.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE wa_contacts (
            id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            normalized_phone TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE wa_dispatch_logs (
            id TEXT PRIMARY KEY,
            contact_id TEXT NOT NULL,
            dispatch_status TEXT NOT NULL,
            dispatched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            response_received INTEGER DEFAULT 0
        )
    """)

    # Seed 3 contacts: 2 PENDING, 1 SENT
    cur.execute("INSERT INTO wa_contacts VALUES ('c1', 'Alpha Corp', '9825011111', 'PENDING')")
    cur.execute("INSERT INTO wa_contacts VALUES ('c2', 'Beta Ltd', '9825022222', 'PENDING')")
    cur.execute("INSERT INTO wa_contacts VALUES ('c3', 'Gamma Inc', '9825033333', 'SENT')")

    # Seed 1 dispatch log
    cur.execute(
        "INSERT INTO wa_dispatch_logs VALUES ('d1', 'c3', 'SENT', CURRENT_TIMESTAMP, 0)"
    )

    conn.commit()
    conn.close()
    return db_file


def test_get_whatsapp_summary_nonexistent_db(tmp_path):
    """Returns None gracefully when the database file does not exist."""
    summary = get_whatsapp_summary(tmp_path / "nonexistent.db")
    assert summary is None


def test_get_whatsapp_summary_valid_db(mock_whatsapp_db):
    """Accurately calculates summary metrics from a valid SQLite DB."""
    summary = get_whatsapp_summary(mock_whatsapp_db)
    assert summary is not None
    assert summary["total_contacts"] == 3
    assert summary["pending"] == 2
    assert summary["sent"] == 1
    assert summary["sent_today"] == 1
    assert summary["total_sent"] == 1
    assert summary["replied"] == 0
    assert summary["opt_outs"] == 0


def test_get_whatsapp_summary_empty_or_corrupted(tmp_path):
    """Handles an empty database missing required tables without crashing."""
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(empty_db)
    conn.close()

    summary = get_whatsapp_summary(empty_db)
    assert summary is None


def test_api_whatsapp_metrics_endpoint(mock_whatsapp_db, monkeypatch):
    """Tests GET /api/whatsapp/metrics with database configured."""
    monkeypatch.setenv("WHATSAPP_OUTREACH_DB_PATH", str(mock_whatsapp_db))
    client = TestClient(app)

    response = client.get("/api/whatsapp/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["total_contacts"] == 3
    assert data["pending"] == 2


def test_api_whatsapp_metrics_endpoint_unavailable(tmp_path, monkeypatch):
    """Tests GET /api/whatsapp/metrics when database is unavailable."""
    monkeypatch.setenv("WHATSAPP_OUTREACH_DB_PATH", str(tmp_path / "missing.db"))
    client = TestClient(app)

    response = client.get("/api/whatsapp/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unavailable"


def test_outreach_metrics_includes_whatsapp(mock_whatsapp_db, monkeypatch):
    """Tests GET /api/outreach/metrics includes whatsapp summary without breaking core fields."""
    monkeypatch.setenv("WHATSAPP_OUTREACH_DB_PATH", str(mock_whatsapp_db))
    client = TestClient(app)

    response = client.get("/api/outreach/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "sent_today" in data
    assert "daily_send_limit" in data
    assert "whatsapp" in data
    assert data["whatsapp"]["total_contacts"] == 3
