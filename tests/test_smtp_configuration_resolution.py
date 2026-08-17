import os
import pytest
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
