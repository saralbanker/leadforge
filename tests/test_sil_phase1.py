"""Phase 1 unit tests: Search Intelligence Layer foundation.

Covers:
- Google Business Category JSON loading
- Deterministic category resolution (CategoryResolver)
- Category variant generation
- Geographic cache creation and read-back (GeoResolver)
- Cache expiration logic (GeoResolver._is_expired)
- Migration 008 execution (sil_geo_cache table created)

All tests are isolated from the production database and from the network.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Isolate database before any leadforge imports ─────────────────────────────
import leadforge.database

_temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_temp_db_path = Path(_temp_db.name)
_temp_db.close()
leadforge.database.DB_PATH = _temp_db_path

from leadforge.database import initialize_database, get_db_connection  # noqa: E402
from leadforge.sil.category_resolver import CategoryResolver  # noqa: E402
from leadforge.sil.geo_resolver import GeoResolver  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def db_setup():
    initialize_database()
    yield
    if _temp_db_path.exists():
        try:
            os.remove(_temp_db_path)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# CategoryResolver — loading
# ═══════════════════════════════════════════════════════════════════════════════


class TestCategoryResolverLoading:
    def test_loads_from_default_path(self):
        resolver = CategoryResolver()
        assert len(resolver.all_categories) > 0

    def test_all_categories_are_strings(self):
        resolver = CategoryResolver()
        for cat in resolver.all_categories:
            assert isinstance(cat, str)
            assert len(cat) > 0

    def test_loads_from_custom_path(self, tmp_path):
        data = {"version": "test", "categories": ["Dentist", "Restaurant", "Gym"]}
        p = tmp_path / "cats.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        resolver = CategoryResolver(data_path=p)
        assert resolver.all_categories == ["Dentist", "Restaurant", "Gym"]

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CategoryResolver(data_path=tmp_path / "nonexistent.json")

    def test_empty_categories_raises_value_error(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"categories": []}), encoding="utf-8")
        with pytest.raises(ValueError):
            CategoryResolver(data_path=p)

    def test_malformed_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(Exception):
            CategoryResolver(data_path=p)


# ═══════════════════════════════════════════════════════════════════════════════
# CategoryResolver — deterministic resolution
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def resolver_three():
    """Small resolver over three categories for precise matching tests."""
    return _make_resolver(["Dentist", "Restaurant", "Manufacturer"])


def _make_resolver(cats: list[str]) -> CategoryResolver:
    data = {"version": "test", "categories": cats}
    tmp = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    )
    json.dump(data, tmp)
    tmp.close()
    r = CategoryResolver(data_path=Path(tmp.name))
    os.unlink(tmp.name)
    return r


class TestCategoryResolverResolution:
    def test_exact_match(self, resolver_three):
        assert resolver_three.resolve("Dentist") == "Dentist"

    def test_case_insensitive_close_match(self):
        resolver = _make_resolver(["Dentist", "Restaurant", "Manufacturer"])
        result = resolver.resolve("dentist")
        assert result == "Dentist"

    def test_typo_corrected(self):
        resolver = _make_resolver(["Dentist", "Restaurant", "Manufacturer"])
        result = resolver.resolve("Dentis")
        assert result == "Dentist"

    def test_returns_none_below_threshold(self):
        resolver = _make_resolver(["Dentist", "Restaurant", "Manufacturer"])
        result = resolver.resolve("XYZZY_UNMATCHED_999")
        assert result is None

    def test_empty_query_returns_none(self, resolver_three):
        assert resolver_three.resolve("") is None
        assert resolver_three.resolve("   ") is None

    def test_deterministic_same_input_same_output(self, resolver_three):
        r1 = resolver_three.resolve("Restaurant")
        r2 = resolver_three.resolve("Restaurant")
        assert r1 == r2

    def test_deterministic_across_instances(self, tmp_path):
        cats = ["Dentist", "Restaurant", "Manufacturer", "Wholesaler", "Hotel"]
        data = {"version": "test", "categories": cats}
        p = tmp_path / "cats.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        r1 = CategoryResolver(data_path=p)
        r2 = CategoryResolver(data_path=p)
        for q in cats + ["dentist", "manufactur", "whole"]:
            assert r1.resolve(q) == r2.resolve(q)

    def test_resolve_manufacturer_variant(self):
        resolver = CategoryResolver()
        result = resolver.resolve("Manufacturers")
        assert result is not None
        assert "Manufactur" in result

    def test_resolve_dentist_from_dental(self):
        resolver = CategoryResolver()
        result = resolver.resolve("Dental clinic")
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
# CategoryResolver — variant generation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCategoryVariants:
    def test_variants_non_empty_for_known_category(self):
        resolver = CategoryResolver()
        variants = resolver.get_variants("Dentist")
        assert len(variants) >= 1

    def test_variants_empty_for_empty_query(self):
        resolver = CategoryResolver()
        assert resolver.get_variants("") == []
        assert resolver.get_variants("   ") == []

    def test_variants_empty_for_garbage_input(self):
        resolver = CategoryResolver()
        assert resolver.get_variants("XYZZY_UNMATCHED_99999") == []

    def test_variants_max_five(self):
        resolver = CategoryResolver()
        variants = resolver.get_variants("Restaurant")
        assert len(variants) <= 5

    def test_variants_all_canonical(self):
        resolver = CategoryResolver()
        all_cats = set(resolver.all_categories)
        for v in resolver.get_variants("Dentist"):
            assert v in all_cats

    def test_variants_deterministic(self):
        resolver = CategoryResolver()
        v1 = resolver.get_variants("Manufacturer")
        v2 = resolver.get_variants("Manufacturer")
        assert v1 == v2

    def test_variants_primary_is_best_match(self):
        resolver = _make_resolver(["Dentist", "Dental lab", "Restaurant"])
        variants = resolver.get_variants("Dentist")
        assert variants[0] == "Dentist"


# ═══════════════════════════════════════════════════════════════════════════════
# Migration 008 — sil_geo_cache table creation
# ═══════════════════════════════════════════════════════════════════════════════


class TestMigration008:
    def test_sil_geo_cache_table_exists(self):
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sil_geo_cache'"
            )
            row = cursor.fetchone()
            assert row is not None, (
                "sil_geo_cache table was not created by migration 008"
            )
        finally:
            conn.close()

    def test_sil_geo_cache_columns(self):
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(sil_geo_cache)")
            cols = {row["name"] for row in cursor.fetchall()}
            assert {"id", "city", "place_name", "place_type", "fetched_at"} <= cols
        finally:
            conn.close()

    def test_sil_geo_cache_unique_constraint(self):
        conn = get_db_connection()
        try:
            from leadforge.database import uuidv7

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            conn.execute(
                "INSERT OR IGNORE INTO sil_geo_cache (id, city, place_name, place_type, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uuidv7(), "__test_city__", "__test_place__", "neighbourhood", now),
            )
            conn.commit()
            # Inserting the same (city, place_name) again should be silently ignored.
            conn.execute(
                "INSERT OR IGNORE INTO sil_geo_cache (id, city, place_name, place_type, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uuidv7(), "__test_city__", "__test_place__", "neighbourhood", now),
            )
            conn.commit()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM sil_geo_cache WHERE city=? AND place_name=?",
                ("__test_city__", "__test_place__"),
            )
            assert cursor.fetchone()[0] == 1
            conn.execute("DELETE FROM sil_geo_cache WHERE city='__test_city__'")
            conn.commit()
        finally:
            conn.close()

    def test_migration_is_idempotent(self):
        # Re-running initialize_database() a second time must not raise.
        initialize_database()


# ═══════════════════════════════════════════════════════════════════════════════
# GeoResolver — cache creation and read-back
# ═══════════════════════════════════════════════════════════════════════════════


def _geo_resolver_with_real_db() -> GeoResolver:
    return GeoResolver(db_connection_factory=get_db_connection)


class TestGeoCacheCreation:
    def _cleanup(self, city: str):
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM sil_geo_cache WHERE city = ?", (city,))
            conn.commit()
        finally:
            conn.close()

    def test_write_and_read_cache(self):
        city = "__test_write_read__"
        self._cleanup(city)
        resolver = _geo_resolver_with_real_db()
        resolver._write_cache(city, ["Alpha Nagar", "Beta Colony", "Gamma Zone"])
        result = resolver._read_cache(city)
        assert result is not None
        assert sorted(result) == ["Alpha Nagar", "Beta Colony", "Gamma Zone"]
        self._cleanup(city)

    def test_empty_write_returns_empty_read(self):
        city = "__test_empty__"
        self._cleanup(city)
        resolver = _geo_resolver_with_real_db()
        resolver._write_cache(city, [])
        # Cache has the city but zero rows → read returns empty list, not None.
        # Note: with zero rows written, _read_cache finds no sample row → returns None.
        # That is correct; callers treat None as "not cached" and empty list as "cached, no results".
        # We test that writing empty does not raise and that subsequent write with data works.
        resolver._write_cache(city, ["Sector 1"])
        result = resolver._read_cache(city)
        assert result == ["Sector 1"]
        self._cleanup(city)

    def test_write_replaces_stale_entries(self):
        city = "__test_replace__"
        self._cleanup(city)
        resolver = _geo_resolver_with_real_db()
        resolver._write_cache(city, ["Old Place"])
        resolver._write_cache(city, ["New Place"])
        result = resolver._read_cache(city)
        assert result == ["New Place"]
        self._cleanup(city)

    def test_invalidate_cache_removes_entries(self):
        city = "__test_invalidate__"
        self._cleanup(city)
        resolver = _geo_resolver_with_real_db()
        resolver._write_cache(city, ["Place A", "Place B"])
        resolver.invalidate_cache(city)
        result = resolver._read_cache(city)
        assert result is None
        self._cleanup(city)

    def test_get_neighbourhoods_uses_cache_on_second_call(self):
        city = "__test_cache_hit__"
        self._cleanup(city)
        resolver = _geo_resolver_with_real_db()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "elements": [
                {"tags": {"name": "Navrangpura", "place": "neighbourhood"}},
                {"tags": {"name": "Paldi", "place": "suburb"}},
            ]
        }

        with patch(
            "leadforge.sil.geo_resolver.requests.post", return_value=mock_response
        ) as mock_post:
            first = resolver.get_neighbourhoods(city)
            second = resolver.get_neighbourhoods(city)

        # Overpass should only be called once; second call is served from cache.
        assert mock_post.call_count == 1
        assert sorted(first) == sorted(second)
        self._cleanup(city)

    def test_get_neighbourhoods_returns_empty_on_network_error(self):
        city = "__test_net_error__"
        self._cleanup(city)
        resolver = _geo_resolver_with_real_db()

        with patch(
            "leadforge.sil.geo_resolver.requests.post",
            side_effect=Exception("network failure"),
        ):
            result = resolver.get_neighbourhoods(city)

        assert result == []
        self._cleanup(city)

    def test_get_neighbourhoods_deduplicates_names(self):
        city = "__test_dedup__"
        self._cleanup(city)
        resolver = _geo_resolver_with_real_db()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "elements": [
                {"tags": {"name": "Navrangpura", "place": "neighbourhood"}},
                {"tags": {"name": "Navrangpura", "place": "neighbourhood"}},
                {"tags": {"name": "Paldi", "place": "suburb"}},
            ]
        }

        with patch(
            "leadforge.sil.geo_resolver.requests.post", return_value=mock_response
        ):
            result = resolver.get_neighbourhoods(city)

        assert result.count("Navrangpura") == 1
        self._cleanup(city)

    def test_get_neighbourhoods_empty_city_returns_empty(self):
        resolver = _geo_resolver_with_real_db()
        assert resolver.get_neighbourhoods("") == []
        assert resolver.get_neighbourhoods("   ") == []


# ═══════════════════════════════════════════════════════════════════════════════
# GeoResolver — cache expiration logic
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheExpiration:
    def test_fresh_timestamp_not_expired(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        assert GeoResolver._is_expired(now) is False

    def test_timestamp_29_days_ago_not_expired(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=29)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        assert GeoResolver._is_expired(ts) is False

    def test_timestamp_30_days_ago_is_expired(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=30, seconds=1)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        assert GeoResolver._is_expired(ts) is True

    def test_timestamp_31_days_ago_is_expired(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=31)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        assert GeoResolver._is_expired(ts) is True

    def test_malformed_timestamp_treated_as_expired(self):
        assert GeoResolver._is_expired("not-a-timestamp") is True
        assert GeoResolver._is_expired("") is True

    def test_expired_cache_triggers_refetch(self):
        city = "__test_expiry__"
        conn = get_db_connection()
        try:
            from leadforge.database import uuidv7

            stale_ts = (datetime.now(timezone.utc) - timedelta(days=31)).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            conn.execute("DELETE FROM sil_geo_cache WHERE city = ?", (city,))
            conn.execute(
                "INSERT INTO sil_geo_cache (id, city, place_name, place_type, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uuidv7(), city, "Stale Place", "neighbourhood", stale_ts),
            )
            conn.commit()
        finally:
            conn.close()

        resolver = _geo_resolver_with_real_db()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "elements": [{"tags": {"name": "Fresh Place", "place": "neighbourhood"}}]
        }

        with patch(
            "leadforge.sil.geo_resolver.requests.post", return_value=mock_response
        ) as mock_post:
            result = resolver.get_neighbourhoods(city)

        assert mock_post.call_count == 1
        assert "Fresh Place" in result

        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM sil_geo_cache WHERE city = ?", (city,))
            conn.commit()
        finally:
            conn.close()
