"""Social-profile enrichment provider.

Businesses with no crawlable website sometimes still list a contact email in
their Facebook/Instagram page's public bio or "about" text. This provider
fetches the lead's social_links (collected during Tier-2 Google Maps scraping)
and regex-scans the raw HTML for an email — no login, no JS rendering, so it
only catches what's present in the page's server-rendered markup.
"""

import json
import re
from typing import Any, Dict, List

from leadforge.enrichment.base import BaseEnrichmentProvider, EnrichmentResult
from leadforge.enrichment.http_fetch import fetch_page
from leadforge.utils import get_logger

logger = get_logger()

_SOCIAL_HOST_RE = re.compile(r"(facebook\.com|instagram\.com)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_IGNORED_DOMAINS = {"facebook.com", "instagram.com", "fb.com", "sentry.io", "w3.org", "schema.org"}
_INVALID_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")


class SocialLinkProvider(BaseEnrichmentProvider):
    """Extracts emails from a lead's public Facebook/Instagram page markup."""

    def __init__(self, timeout_seconds: float = 6.0, max_links: int = 2):
        self._timeout = timeout_seconds
        self._max_links = max_links

    @property
    def name(self) -> str:
        return "social_profile"

    @property
    def priority_weight(self) -> float:
        return 0.6

    async def enrich(self, business_profile: Dict[str, Any]) -> List[EnrichmentResult]:
        raw = business_profile.get("social_links") or "[]"
        if isinstance(raw, str):
            try:
                links = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                links = []
        else:
            links = raw or []

        social_links = [u for u in links if isinstance(u, str) and _SOCIAL_HOST_RE.search(u)]
        if not social_links:
            return []

        found: List[EnrichmentResult] = []
        for url in social_links[: self._max_links]:
            try:
                html = await fetch_page(url, self._timeout)
            except Exception as exc:
                logger.debug(f"[SocialLinkProvider] Fetch error on {url}: {exc}")
                continue
            if not html:
                continue

            for match in _EMAIL_RE.findall(html):
                email_clean = match.lower().strip()
                domain = email_clean.split("@")[-1]
                if domain in _IGNORED_DOMAINS or any(email_clean.endswith(ext) for ext in _INVALID_EXTS):
                    continue
                found.append(
                    EnrichmentResult(
                        email=email_clean,
                        source_provider=self.name,
                        source_url=url,
                        confidence_score=0.55,
                        discovery_context="social_profile_page",
                    )
                )

        return found
