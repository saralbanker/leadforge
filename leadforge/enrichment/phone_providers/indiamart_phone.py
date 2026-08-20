"""IndiaMart Phone Extraction Provider.

Queries IndiaMart directory search & seller profiles to extract direct supplier mobile
numbers, virtual numbers, and PBX contact points.
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


class IndiaMartPhoneProvider(BasePhoneProvider):
    """Extracts business phone numbers from IndiaMart B2B directories."""

    def __init__(self, timeout_seconds: float = 7.0):
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "indiamart"

    @property
    def priority_weight(self) -> float:
        return 0.90

    async def extract_phones(
        self, business_profile: Dict[str, Any]
    ) -> List[PhoneResult]:
        name = (business_profile.get("name") or "").strip()
        city = (business_profile.get("city") or "").strip()
        if not name:
            return []

        query = f"{name} {city}".strip()
        search_url = f"https://dir.indiamart.com/search.mp?ss={urllib.parse.quote(query)}"

        results: List[PhoneResult] = []
        seen_phones = set()

        try:
            html = await fetch_page(search_url, self._timeout)
            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")

            # 1. Look for direct tel: links
            for a in soup.find_all("a", href=re.compile(r"^tel:", re.IGNORECASE)):
                raw_tel = a.get("href", "").replace("tel:", "").strip()
                self._add_candidate(raw_tel, search_url, 0.95, results, seen_phones)

            # 2. Check seller contact info spans / classes
            phone_elements = soup.find_all(
                class_=re.compile(r"(du-num|bo|mob|phn|cnt_txt|contact-no|pno|call-btn)", re.IGNORECASE)
            )
            for el in phone_elements:
                text_val = el.get_text(separator=" ", strip=True)
                # Extract phone patterns from element text
                for match in re.findall(r"(?:(?:\+|0{0,2})91[\s-]?)?([6-9]\d{9})\b", text_val):
                    self._add_candidate(f"+91{match}", search_url, 0.92, results, seen_phones)
                for match in re.findall(r"\b(0804\d{6,7}|0[1-9]\d{1,3}[\s-]?\d{6,8})\b", text_val):
                    self._add_candidate(match, search_url, 0.85, results, seen_phones)

            # 3. Check data attributes (data-click, data-phone, data-mobile)
            for el in soup.find_all(attrs={"data-mobile": True}):
                raw_tel = el.get("data-mobile", "").strip()
                self._add_candidate(raw_tel, search_url, 0.92, results, seen_phones)

            for el in soup.find_all(attrs={"data-phone": True}):
                raw_tel = el.get("data-phone", "").strip()
                self._add_candidate(raw_tel, search_url, 0.90, results, seen_phones)

            # 4. Fallback search across full page text for Indian mobile and landline patterns
            page_text = soup.get_text(separator=" ")
            # Standard Indian 10-digit mobile starting with 6,7,8,9
            for match in re.findall(r"(?:(?:\+|0{0,2})91[\s-]?)?([6-9]\d{9})\b", page_text):
                self._add_candidate(f"+91{match}", search_url, 0.82, results, seen_phones)

            # IndiaMart virtual PBX numbers (often start with 0804xxxxxxx)
            for match in re.findall(r"\b(0804\d{6,7})\b", page_text):
                self._add_candidate(match, search_url, 0.80, results, seen_phones)

        except Exception as exc:
            logger.debug(f"[IndiaMartPhoneProvider] Query error for '{name}': {exc}")

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

        if (len(digits_only) == 10 and digits_only[0] in "6789") or (
            len(digits_only) == 12 and digits_only.startswith("91") and digits_only[2] in "6789"
        ):
            is_mobile = True
            phone_type = "MOBILE"
            confidence = min(1.0, base_confidence + 0.05)
        elif digits_only.startswith("1800") or digits_only.startswith("1860"):
            phone_type = "TOLL_FREE"
            confidence = max(0.60, base_confidence - 0.10)
        elif digits_only.startswith("0804") or digits_only.startswith("91804"):
            phone_type = "VIRTUAL_PBX"
            confidence = base_confidence
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
