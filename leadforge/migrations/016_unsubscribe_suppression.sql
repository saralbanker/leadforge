-- ============================================================================
-- LeadForge Migration 016: Unsubscribe Compliance & Suppression Schema (LF-EXP-003)
-- ============================================================================

ALTER TABLE businesses ADD COLUMN is_suppressed INTEGER NOT NULL DEFAULT 0 CHECK(is_suppressed IN (0, 1));

CREATE INDEX IF NOT EXISTS idx_businesses_suppressed
ON businesses(is_suppressed);
