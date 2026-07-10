-- ============================================================================
-- LeadForge Migration 005: Canonical Business Identity
-- ============================================================================
-- Goals
-- -----
-- 1. Add normalized_phone (digits-only) column for indexed, deterministic
--    phone deduplication — replacing the fragile runtime REPLACE chains.
-- 2. Backfill all existing businesses from display_phone.
-- 3. Enforce one lead row per (business_id, campaign_name) — eliminates
--    the duplicate-campaign-row bug that caused dashboard/export mismatches.
-- ============================================================================

-- ── 1. Add normalized_phone column ───────────────────────────────────────────

ALTER TABLE businesses ADD COLUMN normalized_phone TEXT;

-- ── 2. Backfill normalized_phone from display_phone ──────────────────────────
-- Strip: +  space  -  (  )
-- Prepend '91' for 10-digit Indian numbers.

UPDATE businesses
SET normalized_phone = (
    CASE
        WHEN length(
            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                COALESCE(display_phone, ''), '+', ''), ' ', ''), '-', ''), '(', ''), ')', '')
        ) = 10
        THEN '91' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                COALESCE(display_phone, ''), '+', ''), ' ', ''), '-', ''), '(', ''), ')', '')
        ELSE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                COALESCE(display_phone, ''), '+', ''), ' ', ''), '-', ''), '(', ''), ')', '')
    END
)
WHERE display_phone IS NOT NULL AND display_phone != '';

-- ── 3. Index for fast canonical-phone lookups ────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_businesses_normalized_phone
ON businesses(normalized_phone)
WHERE normalized_phone IS NOT NULL AND normalized_phone != '';

-- ── 4. Remove duplicate lead rows before adding the unique constraint ─────────
-- Keep the chronologically-first lead row per (business_id, campaign_name).
-- UUIDv7 is time-ordered so MIN(id) is the oldest row.

DELETE FROM leads
WHERE campaign_name IS NOT NULL
  AND id NOT IN (
      SELECT MIN(id)
      FROM leads
      WHERE campaign_name IS NOT NULL
      GROUP BY business_id, campaign_name
  );

-- ── 5. Enforce one lead row per (business_id, campaign_name) ─────────────────

CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_unique_business_campaign
ON leads(business_id, campaign_name)
WHERE campaign_name IS NOT NULL;
