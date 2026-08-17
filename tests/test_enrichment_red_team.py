"""Red Team Security and Resilience Verification Suite (Phase 1)."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
import httpx

from leadforge.enrichment.website import WebsiteProvider
from leadforge.enrichment.aggregator import EmailCandidateAggregator
from leadforge.enrichment.orchestrator import EmailEnrichmentOrchestrator
from leadforge.enrichment.base import BaseEnrichmentProvider, EnrichmentResult


class TimeoutHangingProvider(BaseEnrichmentProvider):
    @property
    def name(self) -> str:
        return "hanging_provider"

    @property
    def priority_weight(self) -> float:
        return 0.5

    async def enrich(self, business_profile: dict) -> list:
        # Simulate a hanging provider that sleeps longer than global timeout
        await asyncio.sleep(5.0)
        return [EnrichmentResult("slow@domain.com", self.name, "http://slow.com", 0.5)]


class FaultyCrashingProvider(BaseEnrichmentProvider):
    @property
    def name(self) -> str:
        return "crashing_provider"

    @property
    def priority_weight(self) -> float:
        return 0.5

    async def enrich(self, business_profile: dict) -> list:
        raise RuntimeError("Simulated internal provider crash!")


def test_ssrf_protection_blocks_internal_ips():
    async def _test():
        provider = WebsiteProvider()
        internal_targets = [
            "http://127.0.0.1:8080",
            "http://localhost/admin",
            "http://192.168.1.1/router",
            "http://10.0.0.1/internal",
            "http://0.0.0.0:3000",
        ]

        with patch.object(httpx.AsyncClient, "get") as mock_get:
            for target in internal_targets:
                profile = {"name": "Malicious Co", "website_domain": target}
                results = await provider.enrich(profile)
                assert results == [], f"Expected empty results for SSRF target {target}"
            # Verify no HTTP GET requests were dispatched to any blocked internal target
            mock_get.assert_not_called()

    asyncio.run(_test())


def test_orchestrator_handles_timeouts_and_crashes_gracefully():
    async def _test():
        hanging = TimeoutHangingProvider()
        crashing = FaultyCrashingProvider()

        orchestrator = EmailEnrichmentOrchestrator(providers=[hanging, crashing])
        profile = {"business_id": "test-id", "name": "Resilience Test"}

        # Run with short 0.2s timeout to trigger hanging timeout path
        top, ranked = await orchestrator.enrich_business(profile, global_timeout=0.2)

        # Should handle timeout and crash without throwing unhandled exceptions
        assert top is None
        assert ranked == []

    asyncio.run(_test())


def test_aggregator_prevents_script_injection_and_malformed_emails():
    async def _test():
        aggregator = EmailCandidateAggregator(verify_mx=False)
        malformed_inputs = [
            EnrichmentResult("<script>alert(1)</script>@domain.com", "red_team", "http://attack.com", 0.9),
            EnrichmentResult("user@domain.com\r\nBcc: victim@domain.com", "red_team", "http://attack.com", 0.9),
            EnrichmentResult("valid.user@company.com", "red_team", "http://attack.com", 0.95),
        ]

        top, ranked = await aggregator.aggregate(malformed_inputs)

        assert top is not None
        assert top.email == "valid.user@company.com"
        assert len(ranked) == 1

    asyncio.run(_test())
