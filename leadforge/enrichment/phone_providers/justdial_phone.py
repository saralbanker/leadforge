"""Justdial Phone Extraction Provider.

Handles Justdial directory searches, detail pages, and CSS icon-font glyph
decoding to extract accurate, unmasked phone numbers.
"""

import re
import urllib.parse
from typing import Dict, Any, List
from bs4 import BeautifulSoup

from leadforge.enrichment.phone_providers.base import BasePhoneProvider, PhoneResult
from leadforge.enrichment.http_fetch import fetch_page
from leadforge.normalizer import canonical_phone, normalize_phone
from leadforge.utils import get_logger

logger = get_logger()

# Justdial CSS icon font class mapping to numeric digits
JUSTDIAL_ICON_MAP = {
    # Standard desktop glyph set
    "icon-ji": "0",
    "icon-ba": "1",
    "icon-dc": "2",
    "icon-fe": "3",
    "icon-hg": "4",
    "icon-lk": "5",
    "icon-nm": "6",
    "icon-po": "7",
    "icon-rq": "8",
    "icon-ts": "9",
    "icon-yz": "1",
    "icon-wx": "2",
    "icon-vu": "3",
    "icon-acb": "0",
    "icon-plus": "+",
    "icon-hyphen": "-",
}


def decode_justdial_icon_spans(container) -> str:
    """Decodes Justdial obfuscated phone numbers from span class glyphs."""
    digits = []
    if not container:
        return ""

    # Check direct spans with class icon-*
    spans = container.find_all("span", class_=True)
    if not spans:
        # Check if direct text already contains phone
        return container.get_text(strip=True)

    for sp in spans:
        classes = sp.get("class", [])
        matched = False
        for c in classes:
            c_clean = c.strip()
            if c_clean in JUSTDIAL_ICON_MAP:
                digits.append(JUSTDIAL_ICON_MAP[c_clean])
                matched = True
                break
        if not matched:
            txt = sp.get_text(strip=True)
            if txt and (txt.isdigit() or txt in "+-"):
                digits.append(txt)

    return "".join(digits)


class JustdialPhoneProvider(BasePhoneProvider):
    """Extracts business phone numbers from Justdial listings."""

    def __init__(self, timeout_seconds: float = 7.0):
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "justdial"

    @property
    def priority_weight(self) -> float:
        return 0.88

    async def extract_phones(
        self, business_profile: Dict[str, Any]
    ) -> List[PhoneResult]:
        name = (business_profile.get("name") or "").strip()
        city = (business_profile.get("city") or "").strip()
        if not name:
            return []

        query = f"{city}/{name}".strip("/")
        search_url = f"https://www.justdial.com/{urllib.parse.quote(query)}"

        results: List[PhoneResult] = []
        seen_phones = set()

        try:
            html = await fetch_page(search_url, self._timeout)
            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")

            # 1. Check for tel: links in HTML
            for a in soup.find_all("a", href=re.compile(r"^tel:", re.IGNORECASE)):
                raw_tel = a.get("href", "").replace("tel:", "").strip()
                self._add_candidate(raw_tel, search_url, 0.92, results, seen_phones)

            # 2. Check for data-tel / data-phone attributes
            for el in soup.find_all(attrs={"data-tel": True}):
                raw_tel = el.get("data-tel", "").strip()
                self._add_candidate(raw_tel, search_url, 0.90, results, seen_phones)

            for el in soup.find_all(attrs={"data-phone": True}):
                raw_tel = el.get("data-phone", "").strip()
                self._add_candidate(raw_tel, search_url, 0.90, results, seen_phones)

            # 3. Check for obfuscated phone icon spans (.contact-info, .mobilesv, .tel, .callcontent)
            contact_containers = soup.find_all(
                class_=re.compile(r"(contact|phone|tel|callcontent|mobilesv|font\d+)", re.IGNORECASE)
            )
            for container in contact_containers:
                decoded = decode_justdial_icon_spans(container)
                if decoded and len(re.sub(r"\D", "", decoded)) >= 7:
                    self._add_candidate(decoded, search_url, 0.88, results, seen_phones)

            # 4. Fallback: regex search on whole text for standard Indian mobile numbers
            text = soup.get_text(separator=" ")
            # Standard Indian 10-digit mobile starting with 6,7,8,9
            for match in re.findall(r"(?:(?:\+|0{0,2})91[\s-]?)?([6-9]\d{9})\b", text):
                self._add_candidate(f"+91{match}", search_url, 0.80, results, seen_phones)

            # Standard Indian landlines with STD code (e.g., 079 2280 1234)
            for match in re.findall(r"\b(0[1-9]\d{1,3}[\s-]?\d{6,8})\b", text):
                self._add_candidate(match, search_url, 0.75, results, seen_phones)

        except Exception as exc:
            logger.debug(f"[JustdialPhoneProvider] Query error for '{name}' in '{city}': {exc}")

        return results

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
        seen.add(canon)

        digits_only = re.sub(r"\D", "", canon)
        is_mobile = False
        phone_type = "UNKNOWN"

        # Check if 10-digit Indian mobile (starts with 6-9 when 10 digits, or 91 + [6-9] when 12 digits)
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
