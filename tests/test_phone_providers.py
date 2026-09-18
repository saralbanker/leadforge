"""Unit tests for Multi-Platform Phone Extraction Providers & Phone Candidate Aggregator."""

import asyncio
from bs4 import BeautifulSoup
from unittest.mock import AsyncMock, patch, MagicMock

from leadforge.enrichment.phone_providers.base import PhoneResult
from leadforge.enrichment.phone_providers.justdial_phone import (
    JustdialPhoneProvider,
    decode_justdial_icon_spans,
)
from leadforge.enrichment.phone_providers.indiamart_phone import IndiaMartPhoneProvider
from leadforge.enrichment.phone_providers.tradeindia_phone import TradeIndiaPhoneProvider
from leadforge.enrichment.phone_providers.website_phone import WebsitePhoneProvider
from leadforge.enrichment.phone_providers.phone_aggregator import PhoneCandidateAggregator
from leadforge.enrichment.phone_orchestrator import PhoneEnrichmentOrchestrator


def test_justdial_icon_decoder_standard_glyphs():
    """Verify that Justdial icon font classes correctly map to numeric phone digits."""
    html = """
    <div class="contact-info">
        <span class="icon-plus"></span>
        <span class="icon-yz"></span>
        <span class="icon-ji"></span>
        <span class="icon-po"></span>
        <span class="icon-rq"></span>
        <span class="icon-dc"></span>
        <span class="icon-fe"></span>
        <span class="icon-hg"></span>
        <span class="icon-lk"></span>
        <span class="icon-nm"></span>
        <span class="icon-po"></span>
        <span class="icon-ts"></span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("div", class_="contact-info")
    decoded = decode_justdial_icon_spans(container)
    assert decoded == "+10782345679"


def test_justdial_phone_provider_html_parsing():
    """Verify Justdial provider parses HTML containing tel: links and contact spans."""
    async def _run():
        provider = JustdialPhoneProvider()
        mock_html = """
        <html>
            <body>
                <div class="store-details">
                    <h2>Shree Ram Engineering Works</h2>
                    <a href="tel:+919825014820" class="call-btn">Call Now</a>
                    <div class="contact-no">
                        <span class="icon-plus"></span>
                        <span class="icon-ts"></span>
                        <span class="icon-ba"></span>
                        <span class="icon-po"></span>
                        <span class="icon-rq"></span>
                        <span class="icon-dc"></span>
                        <span class="icon-fe"></span>
                        <span class="icon-hg"></span>
                        <span class="icon-lk"></span>
                        <span class="icon-nm"></span>
                        <span class="icon-po"></span>
                        <span class="icon-ji"></span>
                    </div>
                </div>
            </body>
        </html>
        """
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html
            mock_get.return_value = mock_resp

            results = await provider.extract_phones({
                "name": "Shree Ram Engineering Works",
                "city": "Ahmedabad",
            })

            assert len(results) >= 1
            phone_values = [r.phone for r in results]
            assert "+919825014820" in phone_values
            assert any(r.is_mobile for r in results)

    asyncio.run(_run())


def test_indiamart_phone_provider_extraction():
    """Verify IndiaMart provider extracts direct supplier mobiles and PBX numbers."""
    async def _run():
        provider = IndiaMartPhoneProvider()
        mock_html = """
        <html>
            <body>
                <div class="card">
                    <h3>Navkar Dye Chem Industries</h3>
                    <span class="du-num">+91 98795 23110</span>
                    <span class="pno">08048920192</span>
                    <a href="tel:+919879523110">Contact Seller</a>
                </div>
            </body>
        </html>
        """
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html
            mock_get.return_value = mock_resp

            results = await provider.extract_phones({
                "name": "Navkar Dye Chem Industries",
                "city": "Ahmedabad",
            })

            assert len(results) >= 1
            numbers = [r.phone for r in results]
            assert any("98795" in n for n in numbers)
            mobile_result = next((r for r in results if r.phone_type == "MOBILE"), None)
            assert mobile_result is not None

    asyncio.run(_run())


def test_tradeindia_phone_provider_extraction():
    """Verify TradeIndia provider extracts supplier phone numbers."""
    async def _run():
        provider = TradeIndiaPhoneProvider()
        mock_html = """
        <html>
            <body>
                <div class="company-card">
                    <h2>Balaji Steel Tubes & Structural</h2>
                    <div class="co-phone">+91 98220 54180</div>
                    <a href="tel:+919822054180">Call</a>
                </div>
            </body>
        </html>
        """
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html
            mock_get.return_value = mock_resp

            results = await provider.extract_phones({
                "name": "Balaji Steel Tubes & Structural",
                "city": "Pune",
            })

            assert len(results) >= 1
            numbers = [r.phone for r in results]
            assert any("98220" in n for n in numbers)

    asyncio.run(_run())


def test_website_phone_provider_crawling():
    """Verify Website provider extracts phone numbers from homepage and /contact page."""
    async def _run():
        provider = WebsitePhoneProvider()
        home_html = """
        <html>
            <body>
                <h1>Apex Transformers</h1>
                <a href="/contact-us">Contact Us</a>
                <footer>Call us: +91 98240 77120 | 0265 2641234</footer>
            </body>
        </html>
        """
        contact_html = """
        <html>
            <body>
                <h1>Reach Apex Transformers</h1>
                <a href="tel:+919824077120">Direct Mobile</a>
            </body>
        </html>
        """
        with patch.object(provider, "_fetch_and_parse") as mock_fetch:
            mock_fetch.side_effect = [
                (home_html, ["https://apextransformers.com/contact-us"]),
                (contact_html, []),
            ]

            results = await provider.extract_phones({
                "name": "Apex Transformers",
                "website": "https://apextransformers.com",
                "city": "Vadodara",
            })

            assert len(results) >= 1
            numbers = [r.phone for r in results]
            assert any("98240" in n for n in numbers)

    asyncio.run(_run())


def test_phone_candidate_aggregator_prioritization():
    """Verify aggregator ranks Mobile > Landline > Toll-Free and preserves all candidates."""
    aggregator = PhoneCandidateAggregator()
    candidates = [
        PhoneResult(
            phone="1800 200 1234",
            phone_type="TOLL_FREE",
            source_provider="official_website",
            source_url="https://example.com",
            confidence_score=0.70,
            is_mobile=False,
        ),
        PhoneResult(
            phone="079 2280 1234",
            phone_type="LANDLINE",
            source_provider="justdial",
            source_url="https://justdial.com",
            confidence_score=0.85,
            is_mobile=False,
        ),
        PhoneResult(
            phone="+91 98250 14820",
            phone_type="MOBILE",
            source_provider="indiamart",
            source_url="https://indiamart.com",
            confidence_score=0.95,
            is_mobile=True,
        ),
    ]

    primary_phone, primary_source, canonical, candidates_data = aggregator.aggregate(
        candidate_results=candidates,
        initial_phone="079 2280 1234",
        initial_source="google_maps",
    )

    # Top priority must be direct mobile
    assert "9825014820" in canonical
    assert primary_source == "indiamart"
    assert len(candidates_data) == 3  # Deduplicated unique numbers
    # First item in candidates data is the top prioritized mobile
    assert candidates_data[0]["phone_type"] == "MOBILE"


def test_phone_enrichment_orchestrator():
    """Verify orchestrator runs enabled providers and aggregates candidates."""
    async def _run():
        orchestrator = PhoneEnrichmentOrchestrator()

        mock_res_indiamart = [
            PhoneResult(
                phone="+91 98795 23110",
                phone_type="MOBILE",
                source_provider="indiamart",
                source_url="",
                confidence_score=0.92,
                is_mobile=True,
            )
        ]

        with patch.object(orchestrator.providers["indiamart"], "extract_phones", AsyncMock(return_value=mock_res_indiamart)):
            primary_phone, primary_source, canonical, candidates = await orchestrator.enrich_phone(
                business_profile={
                    "name": "Navkar Dye Chem",
                    "city": "Ahmedabad",
                },
                enabled_platforms=["indiamart"],
                initial_phone=None,
                initial_source="google_maps",
            )

            assert primary_phone is not None
            assert "9879523110" in canonical
            assert primary_source == "indiamart"
            assert len(candidates) >= 1

    asyncio.run(_run())
