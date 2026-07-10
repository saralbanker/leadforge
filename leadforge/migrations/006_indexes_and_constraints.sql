-- ============================================================================
-- LeadForge Migration 006: Missing Indexes and Constraints
-- ============================================================================
-- Goals
-- -----
-- 1. Add UNIQUE INDEX on businesses.normalized_phone to enforce uniqueness at
--    the database level and make the application-level TOCTOU race benign.
-- 2. Add index on leads.campaign_name to eliminate full-table scans on every
--    dashboard load and campaign export.
-- 3. Add UNIQUE INDEX on digital_maturities(business_id) to enforce the
--    expected 1:1 relationship at the database level.
-- ============================================================================

-- ── 1. Unique phone constraint ────────────────────────────────────────────────
-- Handles any duplicate normalized_phone rows created before this migration
-- by retaining the earliest (smallest UUIDv7 = oldest) row.

DELETE FROM businesses
WHERE normalized_phone IS NOT NULL
  AND normalized_phone != ''
  AND id NOT IN (
      SELECT MIN(id)
      FROM businesses
      WHERE normalized_phone IS NOT NULL AND normalized_phone != ''
      GROUP BY normalized_phone
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_businesses_normalized_phone_unique
ON businesses(normalized_phone)
WHERE normalized_phone IS NOT NULL AND normalized_phone != '';

-- ── 2. Campaign name index ────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_leads_campaign_name
ON leads(campaign_name)
WHERE campaign_name IS NOT NULL;

-- ── 3. Digital maturities uniqueness ─────────────────────────────────────────
-- Retain the most recent assessment (largest UUIDv7) per business.

DELETE FROM digital_maturities
WHERE id NOT IN (
    SELECT MAX(id)
    FROM digital_maturities
    GROUP BY business_id
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_digital_maturities_business_id
ON digital_maturities(business_id);
