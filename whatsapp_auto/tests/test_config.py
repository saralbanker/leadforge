"""Tests for foundation/config.py."""

from pathlib import Path
import pytest
from foundation import config


def test_config_paths_exist():
    """Verify that configured paths exist on the filesystem."""
    assert config.ROOT_DIR.exists(), f"ROOT_DIR does not exist: {config.ROOT_DIR}"
    assert config.SCHEMA_PATH.exists(), f"SCHEMA_PATH does not exist: {config.SCHEMA_PATH}"
    assert config.DB_PATH.exists(), f"DB_PATH does not exist: {config.DB_PATH}"
    assert config.LEADFORGE_DB_PATH.exists(), f"LEADFORGE_DB_PATH does not exist: {config.LEADFORGE_DB_PATH}"


def test_config_operational_limits():
    """Verify operational limits and defaults are sane."""
    assert 10 <= config.DAILY_SEND_LIMIT <= 50, f"Dangerous daily send limit: {config.DAILY_SEND_LIMIT}"
    assert config.DEFAULT_CITY == "Ahmedabad"
    assert "Vatva" in config.DEFAULT_AREA or "Ahmedabad" in config.DEFAULT_AREA
    assert config.OPERATOR_NAME
    assert config.OPERATOR_COMPANY
