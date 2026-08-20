import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def _skip_legacy_bootstrap():
    """Skip the legacy Excel re-import/rescoring pass for every test in this session.

    Without this, initialize_database() re-imports every .xlsx in output/ and
    re-runs opportunity scoring on every fresh temp DB a test spins up.
    """
    os.environ["LEADFORGE_SKIP_BOOTSTRAP"] = "1"
    yield
    os.environ.pop("LEADFORGE_SKIP_BOOTSTRAP", None)
