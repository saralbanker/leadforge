"""Category-to-service mapping resolver.

Rules are stored in the settings table under keys of the form:
    opp.category_map.<NormalisedCategory>

The value is a JSON array of service names, e.g.:
    ["Website Design & Development", "SEO & Digital Marketing"]

A fallback key ``opp.category_map.default`` is used when no specific
mapping exists.  No service names are hardcoded here.
"""

import json
from typing import List

from leadforge.repositories.settings import SQLiteSettingsRepository


_MAPPING_PREFIX = "opp.category_map."
_DEFAULT_KEY = f"{_MAPPING_PREFIX}default"


class CategoryServiceMapper:
    """Resolves the list of recommended service names for a given category.

    Instantiate once and reuse; it reads from settings on every call so that
    mapping changes take effect without a restart (or inject a mock repo in
    tests for full determinism).
    """

    def __init__(self, settings_repo: SQLiteSettingsRepository | None = None) -> None:
        self._repo = settings_repo or SQLiteSettingsRepository()

    def get_services_for_category(self, category: str) -> List[str]:
        """Return an ordered list of service names for *category*.

        Lookup order:
        1. Exact match:   opp.category_map.<category>
        2. Default:       opp.category_map.default
        3. Empty list  (no mapping configured at all)
        """
        normalised = (category or "").strip()

        # 1 — exact match
        services = self._resolve_key(f"{_MAPPING_PREFIX}{normalised}")
        if services is not None:
            return services

        # 2 — default
        services = self._resolve_key(_DEFAULT_KEY)
        if services is not None:
            return services

        # 3 — graceful empty fallback
        return []

    # ── Private ───────────────────────────────────────────────────────────────

    def _resolve_key(self, key: str) -> List[str] | None:
        """Fetches key from settings and parses JSON.  Returns None on miss."""
        raw = self._repo.get(key)
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return None
