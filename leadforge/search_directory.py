"""Directory search and lead discovery providers for B2B platforms.

Implements streaming discovery for IndiaMart, Justdial, and TradeIndia.
"""

import asyncio
import re
import urllib.parse
from typing import AsyncGenerator, Dict, Any, List, Optional
import httpx
from bs4 import BeautifulSoup

from leadforge.enrichment.phone_providers.justdial_phone import decode_justdial_icon_spans
from leadforge.normalizer import canonical_phone, normalize_phone
from leadforge.utils import get_logger, clean_text

logger = get_logger()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def sanitize_category_query(category: str) -> str:
    """Strips punctuation, handles ampersands, and normalizes category for directory search."""
    cleaned = category.replace("&", " and ").replace("/", " ").replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def slugify_category(category: str) -> str:
    """Produces clean URL slug like 'Industrial-Boiler-Manufacturers'."""
    cleaned = re.sub(r"[^\w\s-]", "", category.replace("&", "and")).strip()
    return re.sub(r"[\s_]+", "-", cleaned)


async def discover_indiamart_businesses_stream(
    city: str, category: str, limit: int = 50, timeout_seconds: float = 8.0
) -> AsyncGenerator[Dict[str, Any], None]:
    """Yields business listing dictionaries discovered on IndiaMart."""
    clean_cat = sanitize_category_query(category)
    query = f"{clean_cat} {city}".strip()
    search_url = f"https://dir.indiamart.com/search.mp?ss={urllib.parse.quote(query)}"
    logger.info(f"[IndiaMart Discovery] Searching for '{query}' (budget: {limit})...")

    yielded_count = 0
    seen_names = set()

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=timeout_seconds, follow_redirects=True, verify=False
        ) as client:
            resp = await client.get(search_url)
            # If standard dir search returns non-200 or empty, try mobile search endpoint
            if resp.status_code != 200 or len(resp.text) < 1000:
                m_url = f"https://m.indiamart.com/isearch.php?s={urllib.parse.quote(query)}"
                resp = await client.get(m_url)

            soup = BeautifulSoup(resp.text, "html.parser")
            # Target business listing cards (.lst_cl, .card, .g-card, .pro-card)
            cards = soup.find_all(class_=re.compile(r"(lst_cl|pro-card|card|g-card|b-card|res-card)", re.IGNORECASE))
            if not cards:
                cards = soup.find_all("div", attrs={"data-click": True})

            for card in cards:
                if yielded_count >= limit:
                    break

                # Extract business name
                name_tag = card.find(class_=re.compile(r"(company|c-name|cnm|gp-name|bo|org)", re.IGNORECASE)) or card.find("h2") or card.find("h3")
                name = clean_text(name_tag.get_text() if name_tag else "")
                if not name or len(name) < 3 or name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())

                # Extract phone numbers
                phones = []
                for a in card.find_all("a", href=re.compile(r"^tel:", re.IGNORECASE)):
                    raw_tel = a.get("href", "").replace("tel:", "").strip()
                    if len(canonical_phone(raw_tel)) >= 7:
                        phones.append(normalize_phone(raw_tel))

                for el in card.find_all(class_=re.compile(r"(du-num|bo|mob|phn|cnt_txt|pno)", re.IGNORECASE)):
                    for m in re.findall(r"(?:(?:\+|0{0,2})91[\s-]?)?([6-9]\d{9})\b", el.get_text()):
                        phones.append(f"+91{m}")
                    for m in re.findall(r"\b(0804\d{6,7})\b", el.get_text()):
                        phones.append(m)

                phone = phones[0] if phones else ""

                # Extract address / area
                addr_tag = card.find(class_=re.compile(r"(address|cty|city|location|loc)", re.IGNORECASE))
                address = clean_text(addr_tag.get_text() if addr_tag else f"{city}")

                # Extract link
                link_tag = card.find("a", href=True)
                source_url = link_tag["href"] if link_tag else search_url
                if not source_url.startswith("http"):
                    source_url = urllib.parse.urljoin("https://dir.indiamart.com", source_url)

                yielded_count += 1
                yield {
                    "name": name,
                    "city": city,
                    "category": category,
                    "phone": phone,
                    "address": address,
                    "source_url": source_url,
                    "primary_platform": "indiamart",
                    "business_status": "OPERATIONAL",
                    "rating": 4.5,
                    "review_count": 10,
                }

    except Exception as exc:
        logger.warning(f"[IndiaMart Discovery] Error during scrape: {exc}")


async def discover_justdial_businesses_stream(
    city: str, category: str, limit: int = 50, timeout_seconds: float = 8.0
) -> AsyncGenerator[Dict[str, Any], None]:
    """Yields business listing dictionaries discovered on Justdial."""
    clean_cat = sanitize_category_query(category)
    slug = slugify_category(clean_cat)
    city_slug = slugify_category(city)
    search_url = f"https://www.justdial.com/{city_slug}/{slug}"
    logger.info(f"[Justdial Discovery] Searching for '{city_slug}/{slug}' (budget: {limit})...")

    yielded_count = 0
    seen_names = set()

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=timeout_seconds, follow_redirects=True, verify=False
        ) as client:
            resp = await client.get(search_url)
            if resp.status_code != 200:
                logger.warning(f"[Justdial Discovery] HTTP {resp.status_code} on {search_url}")
                return

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all(class_=re.compile(r"(resultbox|card|cntanr|store-details)", re.IGNORECASE))

            for card in cards:
                if yielded_count >= limit:
                    break

                # Extract name
                name_tag = card.find(class_=re.compile(r"(lng_cont_name|store-name|heading)", re.IGNORECASE)) or card.find("h2")
                name = clean_text(name_tag.get_text() if name_tag else "")
                if not name or len(name) < 3 or name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())

                # Decode phone
                decoded_phone = decode_justdial_icon_spans(card)
                canon = canonical_phone(decoded_phone)
                phone = normalize_phone(decoded_phone) if len(canon) >= 7 else ""

                if not phone:
                    for a in card.find_all("a", href=re.compile(r"^tel:", re.IGNORECASE)):
                        raw_tel = a.get("href", "").replace("tel:", "").strip()
                        if len(canonical_phone(raw_tel)) >= 7:
                            phone = normalize_phone(raw_tel)
                            break

                # Extract address
                addr_tag = card.find(class_=re.compile(r"(cont_fl_addr|address|location)", re.IGNORECASE))
                address = clean_text(addr_tag.get_text() if addr_tag else f"{city}")

                link_tag = card.find("a", href=True)
                source_url = link_tag["href"] if link_tag else search_url
                if not source_url.startswith("http"):
                    source_url = urllib.parse.urljoin("https://www.justdial.com", source_url)

                yielded_count += 1
                yield {
                    "name": name,
                    "city": city,
                    "category": category,
                    "phone": phone,
                    "address": address,
                    "source_url": source_url,
                    "primary_platform": "justdial",
                    "business_status": "OPERATIONAL",
                    "rating": 4.2,
                    "review_count": 15,
                }

    except Exception as exc:
        logger.warning(f"[Justdial Discovery] Error during scrape: {exc}")


async def discover_tradeindia_businesses_stream(
    city: str, category: str, limit: int = 50, timeout_seconds: float = 8.0
) -> AsyncGenerator[Dict[str, Any], None]:
    """Yields business listing dictionaries discovered on TradeIndia."""
    clean_cat = sanitize_category_query(category)
    query = f"{clean_cat} {city}".strip()
    search_url = f"https://www.tradeindia.com/search.html?keyword={urllib.parse.quote(query)}"
    logger.info(f"[TradeIndia Discovery] Searching for '{query}' (budget: {limit})...")

    yielded_count = 0
    seen_names = set()

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=timeout_seconds, follow_redirects=True, verify=False
        ) as client:
            resp = await client.get(search_url)
            if resp.status_code != 200:
                logger.warning(f"[TradeIndia Discovery] HTTP {resp.status_code} on {search_url}")
                return

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all(class_=re.compile(r"(co-card|company-card|card|listing-item)", re.IGNORECASE))

            for card in cards:
                if yielded_count >= limit:
                    break

                name_tag = card.find(class_=re.compile(r"(company-name|co-name|title)", re.IGNORECASE)) or card.find("h2") or card.find("h3")
                name = clean_text(name_tag.get_text() if name_tag else "")
                if not name or len(name) < 3 or name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())

                phone = ""
                for a in card.find_all("a", href=re.compile(r"^tel:", re.IGNORECASE)):
                    raw_tel = a.get("href", "").replace("tel:", "").strip()
                    if len(canonical_phone(raw_tel)) >= 7:
                        phone = normalize_phone(raw_tel)
                        break

                if not phone:
                    text_val = card.get_text()
                    for m in re.findall(r"(?:(?:\+|0{0,2})91[\s-]?)?([6-9]\d{9})\b", text_val):
                        phone = f"+91{m}"
                        break

                addr_tag = card.find(class_=re.compile(r"(location|city|address)", re.IGNORECASE))
                address = clean_text(addr_tag.get_text() if addr_tag else f"{city}")

                link_tag = card.find("a", href=True)
                source_url = link_tag["href"] if link_tag else search_url
                if not source_url.startswith("http"):
                    source_url = urllib.parse.urljoin("https://www.tradeindia.com", source_url)

                yielded_count += 1
                yield {
                    "name": name,
                    "city": city,
                    "category": category,
                    "phone": phone,
                    "address": address,
                    "source_url": source_url,
                    "primary_platform": "tradeindia",
                    "business_status": "OPERATIONAL",
                    "rating": 4.4,
                    "review_count": 8,
                }

    except Exception as exc:
        logger.warning(f"[TradeIndia Discovery] Error during scrape: {exc}")
