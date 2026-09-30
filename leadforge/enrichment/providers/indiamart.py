"""IndiaMart directory enrichment provider."""

import re
import urllib.parse
from typing import Dict, Any, List
from bs4 import BeautifulSoup

from leadforge.enrichment.base import BaseEnrichmentProvider, EnrichmentResult
from leadforge.enrichment.http_fetch import fetch_page
from leadforge.normalizer import normalize_email, is_valid_recipient_email
from leadforge.utils import get_logger

logger = get_logger()


class IndiaMartProvider(BaseEnrichmentProvider):
    """B2B Directory provider for IndiaMart profile contact enrichment."""

    def __init__(self, timeout_seconds: float = 6.0):
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "indiamart"

    @property
    def priority_weight(self) -> float:
        return 0.85

    async def enrich(
        self, business_profile: Dict[str, Any]
    ) -> List[EnrichmentResult]:
        name = (business_profile.get("name") or "").strip()
        city = (business_profile.get("city") or "").strip()
        phone = (business_profile.get("phone") or "").strip()
        if not name:
            return []

        query = f"{name} {city}".strip()
        found = await self._search_and_extract(query)

        # Name search is frequently too noisy/sparse for small listings that
        # IndiaMart only indexes under the seller's phone number. Retry with
        # the phone as the query before giving up.
        if not found and phone:
            digits = re.sub(r"\D", "", phone)[-10:]
            if len(digits) == 10:
                found = await self._search_and_extract(digits)

        return found

    async def _search_and_extract(self, query: str) -> List[EnrichmentResult]:
        search_url = f"https://dir.indiamart.com/search.mp?ss={urllib.parse.quote(query)}"

        found: List[EnrichmentResult] = []

        try:
            html = await fetch_page(search_url, self._timeout)
            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(separator=" ")

            ignored_domains = {"indiamart.com", "sentry.io", "w3.org", "schema.org"}
            invalid_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")

            # Extract mailto links
            for link in soup.find_all("a", href=re.compile(r"^mailto:", re.IGNORECASE)):
                match = re.search(
                    r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                    str(link.get("href", "")),
                    re.IGNORECASE,
                )
                if match:
                    email_clean = normalize_email(match.group(1))
                    if not is_valid_recipient_email(email_clean)[0]:
                        continue
                    email_domain = email_clean.split("@")[-1]
                    if email_domain not in ignored_domains and not any(email_clean.endswith(ext) for ext in invalid_exts):
                        found.append(
                            EnrichmentResult(
                                email=email_clean,
                                source_provider=self.name,
                                source_url=search_url,
                                confidence_score=0.85,
                                discovery_context="indiamart_directory_mailto",
                            )
                        )

            # Regex text extraction
            pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
            for match in pattern.findall(text):
                email_clean = normalize_email(match)
                if not is_valid_recipient_email(email_clean)[0]:
                    continue
                email_domain = email_clean.split("@")[-1]
                if email_domain in ignored_domains or any(email_clean.endswith(ext) for ext in invalid_exts):
                    continue
                found.append(
                    EnrichmentResult(
                        email=email_clean,
                        source_provider=self.name,
                        source_url=search_url,
                        confidence_score=0.75,
                        discovery_context="indiamart_directory_text",
                    )
                )
        except Exception as exc:
            logger.debug(f"[IndiaMartProvider] Error querying {query}: {exc}")

        return found
