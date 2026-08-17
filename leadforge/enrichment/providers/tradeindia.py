"""TradeIndia directory enrichment provider."""

import re
import urllib.parse
from typing import Dict, Any, List
import httpx
from bs4 import BeautifulSoup

from leadforge.enrichment.base import BaseEnrichmentProvider, EnrichmentResult
from leadforge.utils import get_logger

logger = get_logger()


class TradeIndiaProvider(BaseEnrichmentProvider):
    """B2B Directory provider for TradeIndia profile contact enrichment."""

    def __init__(self, timeout_seconds: float = 6.0):
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "tradeindia"

    @property
    def priority_weight(self) -> float:
        return 0.80

    async def enrich(
        self, business_profile: Dict[str, Any]
    ) -> List[EnrichmentResult]:
        name = (business_profile.get("name") or "").strip()
        city = (business_profile.get("city") or "").strip()
        if not name:
            return []

        query = f"{name} {city}".strip()
        search_url = f"https://www.tradeindia.com/search.html?keyword={urllib.parse.quote(query)}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        found: List[EnrichmentResult] = []

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=self._timeout,
                follow_redirects=True,
                verify=False,
            ) as client:
                resp = await client.get(search_url)
                if resp.status_code != 200:
                    return []

                soup = BeautifulSoup(resp.text, "html.parser")
                text = soup.get_text(separator=" ")

                ignored_domains = {"tradeindia.com", "sentry.io", "w3.org", "schema.org"}
                invalid_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")

                pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
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
                            confidence_score=0.75,
                            discovery_context="tradeindia_directory_text",
                        )
                    )
        except Exception as exc:
            logger.debug(f"[TradeIndiaProvider] Error querying {query}: {exc}")

        return found
