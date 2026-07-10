"""Geographic neighbourhood resolver backed by OpenStreetMap Overpass.

Discovers neighbourhood / suburb / quarter / borough place names for a given
city, caches results in SQLite (table: sil_geo_cache), and returns cached
results transparently until the 30-day TTL expires.

Design constraints (from approved architecture):
- Source: OpenStreetMap Overpass API (overpass-api.de).
- Cache: sil_geo_cache table in the existing LeadForge SQLite database.
- Cache lifetime: 30 days.  Refresh is transparent to the caller.
- No Playwright; plain HTTP via `requests` (already a project dependency).
- Resolver is a planning-layer utility; it never touches business records.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from leadforge.database import get_db_connection, uuidv7
from leadforge.utils import get_logger

logger = get_logger()

_CACHE_TTL_DAYS = 30
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_TIMEOUT_SEC = 25
_PLACE_TYPES = ("neighbourhood", "suburb", "quarter", "borough")

_OVERPASS_QUERY_TEMPLATE = """
[out:json][timeout:{timeout}];
area["name"="{city}"]->.search_area;
(
  node(area.search_area)["place"~"^(neighbourhood|suburb|quarter|borough)$"];
  way(area.search_area)["place"~"^(neighbourhood|suburb|quarter|borough)$"];
  relation(area.search_area)["place"~"^(neighbourhood|suburb|quarter|borough)$"];
);
out tags;
"""


class GeoResolver:
    """Resolves city → neighbourhood/suburb names via Overpass with SQLite caching."""

    def __init__(self, db_connection_factory=None) -> None:
        # Allows injection of a factory for testing without touching the real DB.
        self._connect = db_connection_factory or get_db_connection

    # ── Public API ────────────────────────────────────────────────────────────

    def get_neighbourhoods(self, city: str) -> list[str]:
        """Return all known place names for *city*.

        Reads from cache if fresh; fetches from Overpass and refreshes cache
        when stale or missing.  Always returns a list (may be empty on error).
        """
        city = (city or "").strip()
        if not city:
            return []

        cached = self._read_cache(city)
        if cached is not None:
            return cached

        try:
            results = self._fetch_from_overpass(city)
        except Exception as exc:
            logger.warning("GeoResolver: Overpass fetch failed for '%s': %s", city, exc)
            return []

        self._write_cache(city, results)
        return results

    def invalidate_cache(self, city: str) -> None:
        """Remove all cached entries for *city*, forcing a fresh fetch on next call."""
        city = (city or "").strip()
        if not city:
            return
        conn = self._connect()
        try:
            conn.execute("DELETE FROM sil_geo_cache WHERE city = ?", (city,))
            conn.commit()
        finally:
            conn.close()

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _read_cache(self, city: str) -> Optional[list[str]]:
        """Return cached place names if the cache entry is within TTL, else None."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT place_name, fetched_at FROM sil_geo_cache WHERE city = ? LIMIT 1",
                (city,),
            )
            sample = cursor.fetchone()
            if sample is None:
                return None

            fetched_at_str = sample["fetched_at"]
            if self._is_expired(fetched_at_str):
                # Stale — evict and signal caller to re-fetch.
                conn.execute("DELETE FROM sil_geo_cache WHERE city = ?", (city,))
                conn.commit()
                return None

            # Cache is fresh — return all names.
            cursor.execute(
                "SELECT place_name FROM sil_geo_cache WHERE city = ? ORDER BY place_name",
                (city,),
            )
            return [row["place_name"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def _write_cache(self, city: str, place_names: list[str]) -> None:
        """Insert place names into the cache, replacing any stale entries."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            conn.execute("DELETE FROM sil_geo_cache WHERE city = ?", (city,))
            for name in place_names:
                place_type = "neighbourhood"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sil_geo_cache (id, city, place_name, place_type, fetched_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (uuidv7(), city, name, place_type, now),
                )
            conn.commit()
        finally:
            conn.close()

    # ── Overpass ──────────────────────────────────────────────────────────────

    def _fetch_from_overpass(self, city: str) -> list[str]:
        """Query Overpass API and return unique place names for *city*."""
        query = _OVERPASS_QUERY_TEMPLATE.format(
            city=city, timeout=_OVERPASS_TIMEOUT_SEC
        )
        response = requests.post(
            _OVERPASS_URL,
            data={"data": query},
            timeout=_OVERPASS_TIMEOUT_SEC + 5,
            headers={
                "User-Agent": "LeadForge/3.2 SIL (contact: leadforge@example.com)"
            },
        )
        response.raise_for_status()
        payload = response.json()
        names: list[str] = []
        seen: set[str] = set()
        for element in payload.get("elements", []):
            tags = element.get("tags", {})
            name = tags.get("name", "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return sorted(names)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_expired(fetched_at_str: str) -> bool:
        """Return True if the cached entry is older than _CACHE_TTL_DAYS."""
        try:
            s = fetched_at_str
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            fetched_at = datetime.fromisoformat(s)
            expiry = fetched_at + timedelta(days=_CACHE_TTL_DAYS)
            return datetime.now(timezone.utc) >= expiry
        except Exception:
            return True
