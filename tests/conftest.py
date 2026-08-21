import pytest


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Point every test at a freshly migrated temp SQLite DB instead of the
    real, git-tracked leadforge.db.

    Without this, test files that call initialize_database()/get_db_connection()
    directly (most of the suite) read and write the production database:
    deleting rows, mutating settings, and racing each other for the file lock
    ("database is locked") depending on run order. Running migrations fresh
    (rather than copying leadforge.db) also avoids leaking real, manually
    configured runtime settings — e.g. live SMTP credentials — into tests
    that assert on default/unconfigured behavior.
    """
    from leadforge.database import initialize_database

    db_path = tmp_path / "test_leadforge.db"
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db_path))
    initialize_database()
    yield
