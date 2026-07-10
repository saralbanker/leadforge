-- ============================================================================
-- Migration 009 — Campaign Intelligence: per-plan execution metrics (Phase 5)
-- Additive only: no existing table or column is modified.
-- ============================================================================

-- One row per (search_id, plan_idx) pair.
-- search_id matches the search_id argument passed to run_qualified_campaign().
-- plan_idx is the 0-based index of the SearchPlan in the ordered execution list.

CREATE TABLE IF NOT EXISTS campaign_plan_metrics (
    id                   TEXT    PRIMARY KEY CHECK(length(id) = 36),
    search_id            TEXT    NOT NULL,
    plan_idx             INTEGER NOT NULL CHECK(plan_idx >= 0),

    -- Plan identity (denormalised for direct query without joins)
    search_query         TEXT    NOT NULL,
    canonical_category   TEXT    NOT NULL,
    geographic_partition TEXT    NOT NULL,

    -- Producer-side metrics (discovery phase)
    urls_discovered      INTEGER NOT NULL DEFAULT 0 CHECK(urls_discovered >= 0),
    discovery_duplicates INTEGER NOT NULL DEFAULT 0 CHECK(discovery_duplicates >= 0),
    discovery_duration_s REAL    NOT NULL DEFAULT 0.0 CHECK(discovery_duration_s >= 0.0),

    -- Consumer-side metrics (processing phase)
    urls_processed       INTEGER NOT NULL DEFAULT 0 CHECK(urls_processed >= 0),
    qualified            INTEGER NOT NULL DEFAULT 0 CHECK(qualified >= 0),
    consumer_duplicates  INTEGER NOT NULL DEFAULT 0 CHECK(consumer_duplicates >= 0),
    website_rejections   INTEGER NOT NULL DEFAULT 0 CHECK(website_rejections >= 0),
    phone_rejections     INTEGER NOT NULL DEFAULT 0 CHECK(phone_rejections >= 0),
    validation_failures  INTEGER NOT NULL DEFAULT 0 CHECK(validation_failures >= 0),
    processing_duration_s REAL   NOT NULL DEFAULT 0.0 CHECK(processing_duration_s >= 0.0),

    -- Derived metrics (pre-computed at finalize time)
    yield_percentage     REAL    NOT NULL DEFAULT 0.0,
    duplicate_percentage REAL    NOT NULL DEFAULT 0.0,

    recorded_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    UNIQUE(search_id, plan_idx)
);

CREATE INDEX IF NOT EXISTS idx_campaign_plan_metrics_search_id
    ON campaign_plan_metrics(search_id);
