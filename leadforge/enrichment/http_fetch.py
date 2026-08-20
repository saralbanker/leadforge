"""Shared HTTP fetch helper for enrichment providers, with a short-lived in-memory cache.

Directory pages (IndiaMart/Justdial/TradeIndia) and business websites get fetched
independently by both the email and phone provider hierarchies, often for the same
lead at different points in its lifecycle (phone enrichment during scrape, email
enrichment later as a fallback during draft generation). This cache lets the second
fetch for a URL reuse the already-downloaded page instead of hitting the network again.
"""

import time
from typing import Optional

import httpx

_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL_SECONDS = 6 * 3600

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def fetch_page(url: str, timeout: float) -> Optional[str]:
    """Fetches a page's HTML, serving from the in-process cache when available."""
    now = time.monotonic()
    cached = _CACHE.get(url)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
        verify=False,
    ) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return None
        html = resp.text

    _CACHE[url] = (now, html)
    return html


def clear_cache() -> None:
    """Test helper: clears the fetch cache."""
    _CACHE.clear()
