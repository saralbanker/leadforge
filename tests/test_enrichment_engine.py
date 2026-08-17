"""Unit and Integration tests for LeadForge Business Enrichment Layer (Phase 1)."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from typing import List, Dict, Any
import httpx

from leadforge.enrichment.base import BaseEnrichmentProvider, EnrichmentResult
from leadforge.enrichment.website import WebsiteProvider
from leadforge.enrichment.aggregator import EmailCandidateAggregator
from leadforge.repositories.enrichment import SQLiteEnrichmentRepository
from leadforge.enrichment.orchestrator import EmailEnrichmentOrchestrator
from leadforge.database import get_db_connection, uuidv7


class DummyProvider(BaseEnrichmentProvider):
    def __init__(self, name: str, results: List[EnrichmentResult]):
        self._name = name
        self._results = results

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority_weight(self) -> float:
        return 0.8

    async def enrich(self, business_profile: Dict[str, Any]) -> List[EnrichmentResult]:
        return self._results


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Sets up a temporary SQLite database for enrichment testing."""
    db_file = tmp_path / "test_enrichment.db"
    monkeypatch.setattr("leadforge.database.DB_PATH", db_file)
    from leadforge.database import initialize_database

    initialize_database()
    return db_file


def test_aggregator_filters_generic_and_assets():
    async def _test():
        aggregator = EmailCandidateAggregator(verify_mx=False)
        candidates = [
            EnrichmentResult("sentry@example.com", "dummy", "http://test.com", 0.9),  # Generic
            EnrichmentResult("logo@company.png", "dummy", "http://test.com", 0.9),    # Asset
            EnrichmentResult("invalid-email", "dummy", "http://test.com", 0.9),       # Invalid syntax
            EnrichmentResult("sales@validcompany.com", "dummy", "http://test.com", 0.85), # Valid
            EnrichmentResult("contact@validcompany.com", "dummy", "http://test.com/contact", 0.95), # Valid higher score
        ]

        top, ranked = await aggregator.aggregate(candidates)

        assert top is not None
        assert top.email == "contact@validcompany.com"
        assert len(ranked) == 2
        assert ranked[0].email == "contact@validcompany.com"
        assert ranked[1].email == "sales@validcompany.com"

    asyncio.run(_test())


def test_website_provider_extracts_emails():
    async def _test():
        provider = WebsiteProvider(timeout_seconds=2.0, max_subpages=2)
        profile = {"name": "Test Co", "website_domain": "testcompany.com"}

        mock_html = """
        <html>
          <body>
            <h1>Welcome to Test Co</h1>
            <a href="mailto:info@testcompany.com">Email Us</a>
            <a href="/contact">Contact Page</a>
            <p>Direct line: 079-1234567</p>
          </body>
        </html>
        """

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = mock_html
            mock_get.return_value = mock_response

            results = await provider.enrich(profile)
            assert len(results) >= 1
            emails = [r.email for r in results]
            assert "info@testcompany.com" in emails

    asyncio.run(_test())


def test_orchestrator_end_to_end(temp_db):
    async def _test():
        # Setup test business in SQLite
        conn = get_db_connection()
        biz_id = uuidv7()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO businesses (id, name, normalized_name, website_domain) VALUES (?, ?, ?, ?)",
            (biz_id, "Shreeji Art Trading", "shreeji art trading", "shreejicoins.com"),
        )
        conn.commit()
        conn.close()

        dummy_res = [
            EnrichmentResult("artshreeji@yahoo.in", "dummy_provider", "http://shreejicoins.com", 0.95)
        ]
        provider = DummyProvider("dummy_provider", dummy_res)

        orchestrator = EmailEnrichmentOrchestrator(providers=[provider])
        profile = {"business_id": biz_id, "name": "Shreeji Art Trading", "website_domain": "shreejicoins.com"}

        top, ranked = await orchestrator.enrich_business(profile)

        assert top is not None
        assert top.email == "artshreeji@yahoo.in"

        # Verify contact_email was updated in SQLite
        conn2 = get_db_connection()
        cur2 = conn2.cursor()
        cur2.execute("SELECT contact_email FROM businesses WHERE id = ?", (biz_id,))
        saved_email = cur2.fetchone()[0]
        conn2.close()

        assert saved_email == "artshreeji@yahoo.in"

    asyncio.run(_test())
