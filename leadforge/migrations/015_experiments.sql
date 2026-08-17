-- ============================================================================
-- LeadForge Migration 015: A/B Campaign Testing DB Schema & Engine (LF-EXP-001)
-- ============================================================================

CREATE TABLE IF NOT EXISTS experiments (
    id                    TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    name                  TEXT NOT NULL UNIQUE,
    hypothesis            TEXT NOT NULL,
    variable_type         TEXT NOT NULL CHECK(variable_type IN ('SUBJECT', 'BODY_HOOK', 'CTA', 'SEQUENCE_DELAY')),
    control_value         TEXT NOT NULL,
    variant_value         TEXT NOT NULL,
    sample_size_required  INTEGER NOT NULL DEFAULT 100 CHECK(sample_size_required > 0),
    control_sent_count    INTEGER NOT NULL DEFAULT 0 CHECK(control_sent_count >= 0),
    variant_sent_count    INTEGER NOT NULL DEFAULT 0 CHECK(variant_sent_count >= 0),
    control_success_count INTEGER NOT NULL DEFAULT 0 CHECK(control_success_count >= 0),
    variant_success_count INTEGER NOT NULL DEFAULT 0 CHECK(variant_success_count >= 0),
    status                TEXT NOT NULL CHECK(status IN ('DRAFT', 'RUNNING', 'COMPLETED', 'PAUSED')) DEFAULT 'RUNNING',
    p_value               REAL,
    winning_value         TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_experiments_status
ON experiments(status);

CREATE INDEX IF NOT EXISTS idx_experiments_name
ON experiments(name);
