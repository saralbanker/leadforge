"""Integration and Red/Blue Team verification test suite for Phase 2 & Phase 3."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from leadforge.server import app
from leadforge.enrichment.providers.indiamart import IndiaMartProvider
from leadforge.enrichment.providers.tradeindia import TradeIndiaProvider
from leadforge.enrichment.providers.justdial import JustdialProvider
from leadforge.enrichment.orchestrator import EmailEnrichmentOrchestrator
from leadforge.enrichment.phone_orchestrator import PhoneEnrichmentOrchestrator
from leadforge.repositories.settings import SQLiteSettingsRepository
import httpx


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_enrichment_p23.db"
    monkeypatch.setattr("leadforge.database.DB_PATH", db_file)
    from leadforge.database import initialize_database

    initialize_database()
    return db_file


def test_directory_providers_extraction():
    async def _test():
        indiamart = IndiaMartProvider(timeout_seconds=2.0)
        tradeindia = TradeIndiaProvider(timeout_seconds=2.0)
        justdial = JustdialProvider(timeout_seconds=2.0)

        profile = {"name": "Apex Engineering", "city": "Ahmedabad"}

        mock_indiamart_html = """
        <html>
          <body>
            <div>Apex Engineering Listing</div>
            <a href="mailto:contact@apexeng.in">Send Email</a>
          </body>
        </html>
        """

        mock_tradeindia_html = """
        <html>
          <body>
            <p>For inquiries email info@apexeng.in</p>
          </body>
        </html>
        """

        mock_justdial_html = """
        <html>
          <body>
            <p>Sales: sales@apexeng.in</p>
          </body>
        </html>
        """

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            def side_effect(url, **kwargs):
                resp = MagicMock()
                resp.status_code = 200
                if "indiamart" in str(url):
                    resp.text = mock_indiamart_html
                elif "tradeindia" in str(url):
                    resp.text = mock_tradeindia_html
                else:
                    resp.text = mock_justdial_html
                return resp

            mock_get.side_effect = side_effect

            im_res = await indiamart.enrich(profile)
            ti_res = await tradeindia.enrich(profile)
            jd_res = await justdial.enrich(profile)

            assert len(im_res) >= 1
            assert im_res[0].email == "contact@apexeng.in"

            assert len(ti_res) >= 1
            assert ti_res[0].email == "info@apexeng.in"

            assert len(jd_res) >= 1
            assert jd_res[0].email == "sales@apexeng.in"

    asyncio.run(_test())


def test_enrichment_stats_api_endpoint(temp_db):
    client = TestClient(app)
    response = client.get("/api/enrichment/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_attempts" in data
    assert "successful_discoveries" in data
    assert "businesses_with_email" in data


def test_red_team_directory_provider_resilience():
    async def _test():
        providers = [
            IndiaMartProvider(timeout_seconds=0.1),
            TradeIndiaProvider(timeout_seconds=0.1),
            JustdialProvider(timeout_seconds=0.1),
        ]

        malicious_profiles = [
            {"name": "'; DROP TABLE businesses; --", "city": "Ahmedabad"},
            {"name": "<script>alert('xss')</script>", "city": "Mumbai"},
            {"name": "A" * 5000, "city": "Delhi"},
            {"name": "", "city": ""},
        ]

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = httpx.ConnectTimeout("Connection timed out")

            for prov in providers:
                for prof in malicious_profiles:
                    results = await prov.enrich(prof)
                    assert isinstance(results, list)

    asyncio.run(_test())


def test_directory_providers_default_off_without_pipeline_error(temp_db):
    """The opt-out flag removes dead directories without changing no-result semantics."""
    SQLiteSettingsRepository().set("enrichment.directory_providers_enabled", "false")
    email_orchestrator = EmailEnrichmentOrchestrator()
    assert {provider.name for provider in email_orchestrator._providers}.isdisjoint(
        {"indiamart", "justdial", "tradeindia"}
    )

    async def _test():
        phone_orchestrator = PhoneEnrichmentOrchestrator()
        result = await phone_orchestrator.enrich_phone(
            {"name": "No Directory Call", "city": "Ahmedabad"},
            enabled_platforms=[],
            initial_phone=None,
        )
        assert result == (None, None, None, [])

        # Also when enabled_platforms is omitted/None
        result_none = await phone_orchestrator.enrich_phone(
            {"name": "No Directory Call", "city": "Ahmedabad"},
            enabled_platforms=None,
            initial_phone=None,
        )
        assert result_none == (None, None, None, [])

    asyncio.run(_test())
