from leadforge.config import get_smtp_config
from leadforge.outreach.deliverer import SMTPEmailDeliverer
from leadforge.repositories.settings import SQLiteSettingsRepository


def test_get_smtp_config_from_environment(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.testserver.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "testuser")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "sender@testserver.com")

    cfg = get_smtp_config()
    assert cfg["host"] == "smtp.testserver.com"
    assert cfg["port"] == 587
    assert cfg["username"] == "testuser"
    assert cfg["from_email"] == "sender@testserver.com"
    assert cfg["is_configured"] is True


def test_get_smtp_config_from_database(monkeypatch):
    # Ensure env is clear of host
    monkeypatch.delenv("SMTP_HOST", raising=False)

    repo = SQLiteSettingsRepository()
    repo.set("smtp.host", "smtp.dbserver.com")
    repo.set("smtp.port", "465")
    repo.set("smtp.username", "dbuser")
    repo.set("smtp.password", "dbpass")
    repo.set("smtp.from_email", "db@testserver.com")

    cfg = get_smtp_config()
    assert cfg["host"] == "smtp.dbserver.com"
    assert cfg["port"] == 465
    assert cfg["username"] == "dbuser"
    assert cfg["from_email"] == "db@testserver.com"
    assert cfg["is_configured"] is True


def test_smtp_deliverer_refresh_config(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.live.com")
    monkeypatch.setenv("SMTP_USERNAME", "liveuser")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "outreach@live.com")

    deliverer = SMTPEmailDeliverer()
    assert deliverer.host == "smtp.live.com"
    assert deliverer.username == "liveuser"
    assert deliverer.from_email == "outreach@live.com"
    assert deliverer.is_configured is True


def test_environment_remains_authoritative_when_settings_are_stale(monkeypatch):
    """The displayed database values cannot silently override the sender."""
    repo = SQLiteSettingsRepository()
    repo.set("smtp.host", "smtp.stale.test")
    repo.set("smtp.from_email", "stale@test.invalid")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USERNAME", "sender")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "authoritative@example.com")

    cfg = get_smtp_config()
    assert cfg["host"] == "smtp.gmail.com"
    assert cfg["from_email"] == "authoritative@example.com"
    assert cfg["source"] == "environment"

    monkeypatch.delenv("SMTP_HOST", raising=False)
    cfg_db = get_smtp_config()
    assert cfg_db["host"] == "smtp.stale.test"
    assert cfg_db["source"] == "database"


def test_api_settings_surfaces_authoritative_smtp_source(monkeypatch):
    """The /api/settings endpoint exposes which source is authoritative for SMTP."""
    from fastapi.testclient import TestClient
    from leadforge.server import app

    client = TestClient(app)
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["smtp.host"]["source"] == "environment"
    assert data["smtp.host"]["authoritative"] is True

    monkeypatch.delenv("SMTP_HOST", raising=False)
    res_db = client.get("/api/settings")
    assert res_db.status_code == 200
    data_db = res_db.json()
    assert data_db["smtp.host"]["source"] == "database"

