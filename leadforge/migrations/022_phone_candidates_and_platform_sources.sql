-- ============================================================================
-- Migration 022: Multi-Platform Phone Candidates & Platform Sources
-- Adds columns to track multi-platform phone candidates and primary platform
-- ============================================================================

ALTER TABLE businesses ADD COLUMN phone_candidates TEXT;
ALTER TABLE businesses ADD COLUMN phone_source TEXT;
ALTER TABLE businesses ADD COLUMN primary_platform TEXT;

CREATE INDEX IF NOT EXISTS idx_businesses_phone_source
ON businesses(phone_source)
WHERE phone_source IS NOT NULL AND phone_source != '';

CREATE INDEX IF NOT EXISTS idx_businesses_primary_platform
ON businesses(primary_platform)
WHERE primary_platform IS NOT NULL AND primary_platform != '';
