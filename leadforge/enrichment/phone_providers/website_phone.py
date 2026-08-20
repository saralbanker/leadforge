"""Official Website Phone Extraction Provider.

Crawls business websites (homepage and depth-1 contact/about pages) to extract
official telephone and direct mobile contact numbers.
"""

import asyncio
import re
import urllib.parse
from typing import Dict, Any, List, Set, Optional
from bs4 import BeautifulSoup

from leadforge.enrichment.phone_providers.base import BasePhoneProvider, PhoneResult
from leadforge.enrichment.http_fetch import fetch_page
from leadforge.normalizer import canonical_phone, normalize_phone
from leadforge.utils import get_logger

logger = get_logger()

# Disallow internal / private IP ranges to prevent SSRF vulnerabilities
_BLOCKED_IP_PATTERNS = re.compile(
    r"^(127\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|0\.|localhost|::1)",
    re.IGNORECASE,
)

_CONTACT_PAGE_REGEX = re.compile(
    r"/(contact|contact-us|about|about-us|reach-us|reach|connect|help|footer)",
    re.IGNORECASE,
)

# Common Indian phone regex patterns
_INDIAN_MOBILE_RE = re.compile(r"(?:(?:\+|0{0,2})91[\s-]?)?([6-9]\d{9})\b")
_INDIAN_STD_LANDLINE_RE = re.compile(
    r"\b(?:0[1-9]\d{1,3}[\s-]?)?(\d{6,8})\b"
)
_INTERNATIONAL_PHONE_RE = re.compile(
    r"\+(?:[0-9] ?){6,14}[0-9]"
)


class WebsitePhoneProvider(BasePhoneProvider):
    """Extracts telephone and mobile numbers directly from business websites."""

    def __init__(self, timeout_seconds: float = 8.0, max_subpages: int = 3):
        self._timeout = timeout_seconds
        self._max_subpages = max_subpages

    @property
    def name(self) -> str:
        return "official_website"

    @property
    def priority_weight(self) -> float:
        return 0.95

    async def extract_phones(
        self, business_profile: Dict[str, Any]
    ) -> List[PhoneResult]:
        domain = (
            business_profile.get("website_domain")
            or business_profile.get("website")
            or ""
        ).strip()
        if not domain:
            return []

        if not domain.startswith("http://") and not domain.startswith("https://"):
            target_url = "https://" + domain
        else:
            target_url = domain

        parsed = urllib.parse.urlparse(target_url)
        host = (parsed.netloc or "").split(":")[0]
        if _BLOCKED_IP_PATTERNS.match(host):
            logger.warning(f"[WebsitePhoneProvider] Blocked local/private target: {host}")
            return []

        results: List[PhoneResult] = []
        visited_urls: Set[str] = set()
        seen_phones = set()

        try:
            # 1. Fetch Homepage
            home_html, subpages = await self._fetch_and_parse(target_url, visited_urls)
            if home_html:
                self._extract_phones_from_html(home_html, target_url, results, seen_phones)

            # 2. Fetch shallow subpages (contact / about us)
            tasks = []
            for sub_link in subpages[: self._max_subpages]:
                tasks.append(self._fetch_and_parse(sub_link, visited_urls))

            if tasks:
                sub_results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in sub_results:
                    if isinstance(res, tuple):
                        sub_html, _ = res
                        if sub_html:
                            self._extract_phones_from_html(sub_html, target_url, results, seen_phones)

        except Exception as exc:
            logger.debug(f"[WebsitePhoneProvider] Error crawling {domain}: {exc}")

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
                    if sub_parsed.netloc == base_parsed.netloc and full_url not in visited:
                        if full_url not in subpage_links:
                            subpage_links.append(full_url)

            return html, subpage_links
        except Exception:
            return None, []

    def _extract_phones_from_html(
        self, html: str, source_url: str, results: List[PhoneResult], seen: set
    ):
        soup = BeautifulSoup(html, "html.parser")

        # 1. Extract from tel: links (highest precision)
        for a in soup.find_all("a", href=re.compile(r"^tel:", re.IGNORECASE)):
            raw_tel = a.get("href", "").replace("tel:", "").strip()
            self._add_candidate(raw_tel, source_url, 0.95, results, seen)

        # 2. Extract from click-to-call buttons, whatsapp links, and data-phone attributes
        for a in soup.find_all("a", href=re.compile(r"(wa\.me|whatsapp\.com|api\.whatsapp\.com)", re.IGNORECASE)):
            href = str(a.get("href", ""))
            match = re.search(r"(?:phone=|send\?phone=|\.me/)([0-9]{10,12})", href)
            if match:
                self._add_candidate(match.group(1), source_url, 0.92, results, seen)

        for el in soup.find_all(attrs={"data-phone": True}):
            self._add_candidate(el.get("data-phone", "").strip(), source_url, 0.90, results, seen)

        # 3. Clean page text for regex patterns
        # Remove script and style tags
        for s in soup(["script", "style", "svg", "noscript"]):
            s.decompose()
        text = soup.get_text(separator=" ")

        # Match mobile numbers
        for match in _INDIAN_MOBILE_RE.findall(text):
            self._add_candidate(f"+91{match}", source_url, 0.88, results, seen)

        # Match international numbers with + prefix
        for match in _INTERNATIONAL_PHONE_RE.findall(text):
            self._add_candidate(match, source_url, 0.85, results, seen)

    def _add_candidate(
        self,
        raw_phone: str,
        source_url: str,
        base_confidence: float,
        results: List[PhoneResult],
        seen: set,
    ):
        canon = canonical_phone(raw_phone)
        if not canon or len(canon) < 7 or canon in seen:
            return
        # Exclude common false positives (e.g. year ranges, zip codes repeated, all identical digits)
        digits_only = re.sub(r"\D", "", canon)
        if len(set(digits_only)) <= 1 or digits_only.startswith("000000"):
            return

        seen.add(canon)
        is_mobile = False
        phone_type = "UNKNOWN"

        if (len(digits_only) == 10 and digits_only[0] in "6789") or (
            len(digits_only) == 12 and digits_only.startswith("91") and digits_only[2] in "6789"
        ):
            is_mobile = True
            phone_type = "MOBILE"
            confidence = min(1.0, base_confidence + 0.05)
        elif digits_only.startswith("1800") or digits_only.startswith("1860"):
            phone_type = "TOLL_FREE"
            confidence = max(0.60, base_confidence - 0.10)
        elif len(digits_only) >= 8:
            phone_type = "LANDLINE"
            confidence = base_confidence
        else:
            confidence = base_confidence

        formatted = normalize_phone(raw_phone)
        results.append(
            PhoneResult(
                phone=formatted,
                phone_type=phone_type,
                source_provider=self.name,
                source_url=source_url,
                confidence_score=confidence,
                is_mobile=is_mobile,
                raw_text=raw_phone,
            )
        )
