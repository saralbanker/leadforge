"""Canonical Google Business Category resolver.

Loads a locally-vendored JSON snapshot of Google Business Categories and
resolves arbitrary user-supplied category strings to the nearest canonical
entry using deterministic token matching via Python's built-in difflib.

Design constraints (from approved architecture):
- JSON snapshot is the single source of truth; never hit a remote API.
- Resolution uses difflib only — no handwritten synonyms, no dynamic generation.
- Same input always produces the same output (deterministic).
- get_variants() returns the resolved canonical name plus close neighbours for
  search-plan expansion; it does NOT invent new names.
"""

import difflib
import json
from pathlib import Path
from typing import Optional

_DEFAULT_DATA_PATH = (
    Path(__file__).resolve().parent / "data" / "google_business_categories.json"
)

_RESOLVE_CUTOFF = 0.6
_VARIANT_CUTOFF = 0.5
_MAX_VARIANTS = 5


class CategoryResolver:
    """Resolves user-supplied category strings to canonical Google Business Categories."""

    def __init__(self, data_path: Optional[Path] = None) -> None:
        self._path = Path(data_path) if data_path else _DEFAULT_DATA_PATH
        self._categories: list[str] = self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def resolve(self, query: str) -> Optional[str]:
        """Return the single best-matching canonical category, or None if below threshold."""
        q = (query or "").strip()
        if not q:
            return None
        matches = difflib.get_close_matches(
            q, self._categories, n=1, cutoff=_RESOLVE_CUTOFF
        )
        return matches[0] if matches else None

    def get_variants(self, category: str) -> list[str]:
        """Return up to _MAX_VARIANTS canonical categories close to *category*.

        The returned list always starts with the resolved canonical form (if
        resolution succeeds) so callers can treat index-0 as the primary term.
        The remaining entries are expansion candidates for search planning.
        """
        q = (category or "").strip()
        if not q:
            return []

        matches = difflib.get_close_matches(
            q,
            self._categories,
            n=_MAX_VARIANTS,
            cutoff=_VARIANT_CUTOFF,
        )
        if not matches:
            return []

        # Promote the single best match to index-0 so the primary is always first.
        best = difflib.get_close_matches(
            q, self._categories, n=1, cutoff=_RESOLVE_CUTOFF
        )
        if best and best[0] != matches[0]:
            ordered = [best[0]] + [m for m in matches if m != best[0]]
            return ordered[:_MAX_VARIANTS]
        return matches

    @property
    def all_categories(self) -> list[str]:
        return list(self._categories)

    # ── Private ───────────────────────────────────────────────────────────────

    def _load(self) -> list[str]:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Google Business Categories snapshot not found: {self._path}"
            )
        with open(self._path, encoding="utf-8") as fh:
            payload = json.load(fh)
        categories = payload.get("categories", [])
        if not isinstance(categories, list) or not categories:
            raise ValueError(
                f"Google Business Categories snapshot is empty or malformed: {self._path}"
            )
        return [str(c) for c in categories if c]
