-- ============================================================================
-- Migration 026 - Followup Sequencer Delays and Max Touches Settings
-- ============================================================================
-- Keyed on `key`, not on hardcoded UUIDs. The first version of this migration
-- hardcoded ids ...0001/...0002, which already belonged to opp.priority.*, so
-- INSERT OR IGNORE silently skipped both delay rows and only the third landed.

INSERT INTO settings (id, key, value, description)
VALUES (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-7000-8000-' || lower(hex(randomblob(6))),
        'outreach.followup_step2_delay_days', '3',
        'Days between the initial send (touch 1) and the first follow-up (touch 2)')
ON CONFLICT(key) DO NOTHING;

INSERT INTO settings (id, key, value, description)
VALUES (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-7000-8000-' || lower(hex(randomblob(6))),
        'outreach.followup_step3_delay_days', '6',
        'Days between the first follow-up (touch 2) and the second (touch 3)')
ON CONFLICT(key) DO NOTHING;

INSERT INTO settings (id, key, value, description)
VALUES (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-7000-8000-' || lower(hex(randomblob(6))),
        'outreach.max_sequence_touches', '3',
        'Total touches per business, the original send included')
ON CONFLICT(key) DO NOTHING;
