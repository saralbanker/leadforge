"""Guards against fabricated contact data and verifies email candidate ranking.

The enrichment fallback used to invent addresses like ``sales@{name}mfg.co.in``
when discovery found nothing, label them with a fictional provider, and write
them to ``businesses.contact_email``. Every one of them bounced. These tests
exist so that behaviour cannot return.
"""

import asyncio
import re
from pathlib import Path

import pytest

from leadforge.enrichment.aggregator import EmailCandidateAggregator
from leadforge.enrichment.base import EnrichmentResult
from leadforge.enrichment.orchestrator import EmailEnrichmentOrchestrator

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _result(email, provider="official_website", confidence=0.85):
    return EnrichmentResult(
        email=email,
        source_provider=provider,
        source_url="",
        confidence_score=confidence,
        discovery_context="test",
    )


# --------------------------------------------------------------------------
# No fabrication
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "script",
    ["scrape_manufacturing_no_website_leads.py", "scrape_high_value_no_website_leads.py"],
)
def test_scripts_never_synthesize_an_email_address(script):
    """No scraper may build an address out of the business name."""
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    fabricators = re.findall(
        r'f"(?:sales|info|contact|enquiry|admin)@\{[^"]*"', source
    )
    assert fabricators == [], (
        f"{script} fabricates email addresses: {fabricators}. "
        "A guessed address bounces, and bounces cost sender reputation."
    )


@pytest.mark.parametrize(
    "script",
    ["scrape_manufacturing_no_website_leads.py", "scrape_high_value_no_website_leads.py"],
)
def test_scripts_skip_leads_without_a_discovered_email(script):
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    assert "if not discovered_email:" in source, f"{script} must skip undiscoverable leads"
    assert "skipped_no_email" in source, f"{script} must count what it skipped"


def test_no_fictional_provider_labels_remain():
    """Fabricated results were stamped with provider names that do not exist."""
    for script in SCRIPTS.glob("scrape_*.py"):
        source = script.read_text(encoding="utf-8")
        for invented in ("B2B Industrial Directory Index", "B2B Registry Index",
                         "B2B Directory Index", "Regional Directory Index"):
            assert invented not in source, (
                f"{script.name} still labels results with the fictional provider "
                f"{invented!r}, which makes invented data look sourced."
            )


# --------------------------------------------------------------------------
# MX verification
# --------------------------------------------------------------------------

def test_unresolvable_domains_are_rejected(monkeypatch):
    """An address whose domain does not accept mail must never reach a draft."""
    async def _test():
        agg = EmailCandidateAggregator(verify_mx=True)

        async def fake_mx(domain):
            return domain == "realcompany.in"

        monkeypatch.setattr(agg, "_check_domain_has_mx", fake_mx)

        top, ranked = await agg.aggregate([
            _result("sales@shreemfg.co.in", "indiamart", 0.82),
            _result("sales@navkarmfg.co.in", "indiamart", 0.82),
            _result("rajesh@realcompany.in", "official_website", 0.85),
        ])

        assert [c.email for c in ranked] == ["rajesh@realcompany.in"]
        assert top.email == "rajesh@realcompany.in"

    asyncio.run(_test())


def test_all_unresolvable_yields_nothing_rather_than_a_guess(monkeypatch):
    async def _test():
        agg = EmailCandidateAggregator(verify_mx=True)

        async def no_mx(domain):
            return False

        monkeypatch.setattr(agg, "_check_domain_has_mx", no_mx)
        top, ranked = await agg.aggregate([_result("sales@shreemfg.co.in", "indiamart", 0.82)])
        assert top is None and ranked == []

    asyncio.run(_test())


def test_mx_verification_is_on_by_default():
    assert EmailCandidateAggregator()._verify_mx is True


def test_domain_existence_check_uses_keyword_args():
    """Regression: loop.getaddrinfo takes only (host, port) positionally.

    Passing family/type positionally raised TypeError for every domain, which
    the outer handler swallowed — so enabling verify_mx rejected everything.
    """
    async def _test():
        agg = EmailCandidateAggregator(verify_mx=True)
        assert await agg._check_domain_has_mx("localhost.") in (True, False)  # must not raise
        assert await agg._check_domain_has_mx("") is False

    asyncio.run(_test())


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------

def test_provider_trust_outranks_a_higher_raw_confidence():
    """A Justdial body-text hit must not beat a website mailto: on confidence alone."""
    async def _test():
        agg = EmailCandidateAggregator(verify_mx=False)
        top, _ = await agg.aggregate([
            _result("contact@acme.in", "justdial", 0.95),
            _result("contact@acme-works.in", "official_website", 0.85),
        ])
        assert top.source_provider == "official_website"

    asyncio.run(_test())


def test_a_named_person_outranks_a_shared_mailbox():
    async def _test():
        agg = EmailCandidateAggregator(verify_mx=False)
        top, ranked = await agg.aggregate([
            _result("info@acme.in"),
            _result("sales@acme.in"),
            _result("rajesh@acme.in"),
        ])
        assert top.email == "rajesh@acme.in"
        assert [c.email for c in ranked] == ["rajesh@acme.in", "sales@acme.in", "info@acme.in"]

    asyncio.run(_test())


def test_unmonitored_mailboxes_rank_last():
    async def _test():
        agg = EmailCandidateAggregator(verify_mx=False)
        top, _ = await agg.aggregate([
            _result("noreply@acme.in", confidence=0.95),
            _result("info@acme.in", confidence=0.80),
        ])
        assert top.email == "info@acme.in"

    asyncio.run(_test())


@pytest.mark.parametrize("email,expected", [
    ("noreply@x.in", 0.55), ("careers@x.in", 0.55),
    ("info@x.in", 0.80), ("office@x.in", 0.80),
    ("sales@x.in", 1.0), ("enquiry@x.in", 1.0),
    ("rajesh@x.in", 1.10), ("r.patel@x.in", 1.10),
])
def test_role_multiplier(email, expected):
    assert EmailCandidateAggregator.role_multiplier(email) == expected


# --------------------------------------------------------------------------
# Re-crawl guard
# --------------------------------------------------------------------------

class _StubRepo:
    def __init__(self, prior=None):
        self.prior = prior
        self.saved = []

    def get_recent_discovery(self, business_id, max_age_hours=720):
        return self.prior

    def save_enrichment_result(self, **kwargs):
        self.saved.append(kwargs)


class _CountingProvider:
    def __init__(self):
        self.calls = 0

    name = "official_website"
    priority_weight = 1.0

    def is_enabled(self):
        return True

    async def enrich(self, business_profile):
        self.calls += 1
        return [_result("fresh@acme.in")]


def test_recent_discovery_short_circuits_the_crawl():
    async def _test():
        provider = _CountingProvider()
        repo = _StubRepo(prior={
            "discovered_email": "known@acme.in",
            "discovery_status": "SUCCESS",
            "last_attempt_at": "2026-08-19T10:00:00Z",
        })
        orch = EmailEnrichmentOrchestrator(
            providers=[provider],
            aggregator=EmailCandidateAggregator(verify_mx=False),
            repository=repo,
        )
        top, _ = await orch.enrich_business({"business_id": "b1", "name": "Acme"})

        assert top.email == "known@acme.in"
        assert provider.calls == 0, "must not re-crawl a business already enriched"

    asyncio.run(_test())


def test_force_re_crawls_despite_a_recent_discovery():
    async def _test():
        provider = _CountingProvider()
        repo = _StubRepo(prior={
            "discovered_email": "known@acme.in",
            "discovery_status": "SUCCESS",
            "last_attempt_at": "2026-08-19T10:00:00Z",
        })
        orch = EmailEnrichmentOrchestrator(
            providers=[provider],
            aggregator=EmailCandidateAggregator(verify_mx=False),
            repository=repo,
        )
        top, _ = await orch.enrich_business({"business_id": "b1", "name": "Acme"}, force=True)

        assert provider.calls == 1
        assert top.email == "fresh@acme.in"

    asyncio.run(_test())


def test_no_prior_discovery_still_crawls():
    async def _test():
        provider = _CountingProvider()
        orch = EmailEnrichmentOrchestrator(
            providers=[provider],
            aggregator=EmailCandidateAggregator(verify_mx=False),
            repository=_StubRepo(prior=None),
        )
        top, _ = await orch.enrich_business({"business_id": "b1", "name": "Acme"})
        assert provider.calls == 1
        assert top.email == "fresh@acme.in"

    asyncio.run(_test())
