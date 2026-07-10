-- ============================================================================
-- LeadForge Migration 008: Search Intelligence Layer — Geographic Cache
-- ============================================================================
-- Creates the sil_geo_cache table used by GeoResolver to store neighbourhood
-- / suburb / quarter / borough names fetched from OpenStreetMap Overpass.
-- Cache lifetime is 30 days; GeoResolver manages eviction transparently.
-- ============================================================================

CREATE TABLE IF NOT EXISTS sil_geo_cache (
    id          TEXT PRIMARY KEY CHECK(length(id) = 36),
    city        TEXT NOT NULL,
    place_name  TEXT NOT NULL,
    place_type  TEXT NOT NULL,
    fetched_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S.%fZ', 'now')),
    UNIQUE(city, place_name)
);

CREATE INDEX IF NOT EXISTS idx_sil_geo_cache_city
ON sil_geo_cache(city);
