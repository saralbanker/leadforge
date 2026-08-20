"""Justdial directory enrichment provider."""

import re
import urllib.parse
from typing import Dict, Any, List
from bs4 import BeautifulSoup

from leadforge.enrichment.base import BaseEnrichmentProvider, EnrichmentResult
from leadforge.enrichment.http_fetch import fetch_page
from leadforge.utils import get_logger

logger = get_logger()


class JustdialProvider(BaseEnrichmentProvider):
    """Regional Directory provider for Justdial contact enrichment."""

    def __init__(self, timeout_seconds: float = 6.0):
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "justdial"

    @property
    def priority_weight(self) -> float:
        return 0.75

    async def enrich(
        self, business_profile: Dict[str, Any]
    ) -> List[EnrichmentResult]:
        name = (business_profile.get("name") or "").strip()
        city = (business_profile.get("city") or "").strip()
        if not name:
            return []

        query = f"{city}/{name}".strip("/")
        search_url = f"https://www.justdial.com/{urllib.parse.quote(query)}"

        found: List[EnrichmentResult] = []

        try:
            html = await fetch_page(search_url, self._timeout)
            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(separator=" ")

            pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
            ignored_domains = {"justdial.com", "jdmagicbox.com", "sentry.io", "w3.org", "schema.org"}
            invalid_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
            for match in pattern.findall(text):
                email_clean = match.lower().strip()
                email_domain = email_clean.split("@")[-1]
                if email_domain in ignored_domains or any(email_clean.endswith(ext) for ext in invalid_exts):
                    continue
                found.append(
                    EnrichmentResult(
                        email=email_clean,
                        source_provider=self.name,
                        source_url=search_url,
                        confidence_score=0.70,
                        discovery_context="justdial_directory_text",
                    )
                )
        except Exception as exc:
            logger.debug(f"[JustdialProvider] Error querying {query}: {exc}")

        return found
