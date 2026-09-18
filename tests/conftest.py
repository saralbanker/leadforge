import os
import sys
from pathlib import Path
import pytest

LEADFORGE_ROOT = Path(__file__).resolve().parent.parent
if str(LEADFORGE_ROOT) not in sys.path:
    sys.path.insert(0, str(LEADFORGE_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _skip_legacy_bootstrap():
    """Skip the legacy Excel re-import/rescoring pass for every test in this session.

    Without this, initialize_database() re-imports every .xlsx in output/ and
    re-runs opportunity scoring on every fresh temp DB a test spins up.
    """
    os.environ["LEADFORGE_SKIP_BOOTSTRAP"] = "1"
    yield
    os.environ.pop("LEADFORGE_SKIP_BOOTSTRAP", None)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Point every test at a freshly migrated temp SQLite DB instead of the real leadforge.db.

    Without this, test files that call initialize_database()/get_db_connection()
    directly read and write the production database: mutating settings and racing each
    other for the file lock while the daemon is running.
    """
    from leadforge.database import initialize_database

    db_path = tmp_path / "test_leadforge.db"
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db_path))
    initialize_database()
    yield
