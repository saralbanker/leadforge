"""Website enrichment provider executing async multi-page crawling."""

import asyncio
import re
import urllib.parse
from typing import Dict, Any, List, Set, Optional
from bs4 import BeautifulSoup

from leadforge.enrichment.base import (
    BaseEnrichmentProvider,
    EnrichmentResult,
    is_non_business_host,
)
from leadforge.enrichment.http_fetch import fetch_page
from leadforge.utils import get_logger

logger = get_logger()

# Disallow internal / private IP ranges to prevent SSRF vulnerabilities
_BLOCKED_IP_PATTERNS = re.compile(
    r"^(127\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|0\.|localhost|::1)",
    re.IGNORECASE,
)

_CONTACT_PAGE_REGEX = re.compile(
    r"/(contact|contact-us|about|about-us|reach-us|connect|footer)",
    re.IGNORECASE,
)


class WebsiteProvider(BaseEnrichmentProvider):
    """Asynchronous multi-page website email extraction provider."""

    def __init__(self, timeout_seconds: float = 8.0, max_subpages: int = 3):
        self._timeout = timeout_seconds
        self._max_subpages = max_subpages

    @property
    def name(self) -> str:
        return "official_website"

    @property
    def priority_weight(self) -> float:
        return 1.0

    async def enrich(
        self, business_profile: Dict[str, Any]
    ) -> List[EnrichmentResult]:
        domain = (
            business_profile.get("website_domain")
            or business_profile.get("website")
            or ""
        ).strip()
        if not domain:
            return []

        # A link-aggregator or social profile hosts many businesses; crawling it
        # yields the platform's own contact address, not this lead's.
        if is_non_business_host(domain):
            logger.info(
                f"[WebsiteProvider] Skipping '{domain}' — a platform/aggregator host, "
                f"not {business_profile.get('name', 'this business')}'s own site."
            )
            return []

        # Ensure scheme
        if not domain.startswith("http://") and not domain.startswith("https://"):
            target_url = "https://" + domain
        else:
            target_url = domain

        # SSRF Protection: validate host
        parsed = urllib.parse.urlparse(target_url)
        host = (parsed.netloc or "").split(":")[0]
        if _BLOCKED_IP_PATTERNS.match(host):
            logger.warning(f"[WebsiteProvider] Blocked local/private target: {host}")
            return []

        results: List[EnrichmentResult] = []
        visited_urls: Set[str] = set()

        # 1. Crawl Homepage
        homepage_html, subpage_links = await self._fetch_and_parse(target_url, visited_urls)
        if homepage_html:
            results.extend(
                self._extract_emails_from_html(
                    homepage_html, target_url, context="homepage"
                )
            )

        # 2. Crawl shallow subpages concurrently (depth-1: contact/about links)
        tasks = []
        for sub_link in subpage_links[: self._max_subpages]:
            tasks.append(self._fetch_and_parse(sub_link, visited_urls))

        if tasks:
            sub_results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in sub_results:
                if isinstance(res, tuple):
                    sub_html, _ = res
                    if sub_html:
                        results.extend(
                            self._extract_emails_from_html(
                                sub_html, sub_link, context="contact_subpage"
                            )
                        )

        return results

    async def _fetch_and_parse(
        self, url: str, visited: Set[str]
    ) -> tuple[Optional[str], List[str]]:
        if url in visited:
            return None, []
        visited.add(url)

        try:
            html = await fetch_page(url, self._timeout)
            if not html:
                return None, []

            soup = BeautifulSoup(html, "html.parser")

            subpage_links: List[str] = []
            base_parsed = urllib.parse.urlparse(url)

            for a_tag in soup.find_all("a", href=True):
                href = str(a_tag["href"]).strip()
                if _CONTACT_PAGE_REGEX.search(href):
                    full_url = urllib.parse.urljoin(url, href)
                    sub_parsed = urllib.parse.urlparse(full_url)
                    # Stay on same domain
                    if sub_parsed.netloc == base_parsed.netloc and full_url not in visited:
                        if full_url not in subpage_links:
                            subpage_links.append(full_url)

            return html, subpage_links
        except Exception as e:
            logger.debug(f"[WebsiteProvider] Fetch error on {url}: {e}")
            return None, []

    def _extract_emails_from_html(
        self, html: str, url: str, context: str
    ) -> List[EnrichmentResult]:
        found: List[EnrichmentResult] = []
        soup = BeautifulSoup(html, "html.parser")

        # Extract mailto links (highest confidence context)
        for link in soup.find_all("a", href=re.compile(r"^mailto:", re.IGNORECASE)):
            href = str(link.get("href", ""))
            match = re.search(
                r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                href,
                re.IGNORECASE,
            )
            if match:
                email = match.group(1).lower().strip()
                found.append(
                    EnrichmentResult(
                        email=email,
                        source_provider=self.name,
                        source_url=url,
                        confidence_score=0.95 if context == "homepage" else 0.90,
                        discovery_context=f"{context}_mailto",
                    )
                )

        # Regex scan text body
        raw_text = soup.get_text(separator=" ")
        pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        for match in pattern.findall(raw_text):
            email = match.lower().strip()
            found.append(
                EnrichmentResult(
                    email=email,
                    source_provider=self.name,
                    source_url=url,
                    confidence_score=0.85 if context == "homepage" else 0.80,
                    discovery_context=f"{context}_body_text",
                )
            )

        return found
