-- ============================================================================
-- Migration 028 - Daily Outreach Run Schedule Settings
-- ============================================================================
-- Keyed on `key`, not on hardcoded UUIDs.
-- Sets configurable daily schedule time and enabled status for morning outreach runs.

INSERT INTO settings (id, key, value, description)
VALUES (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-7000-8000-' || lower(hex(randomblob(6))),
        'outreach.schedule_time', '08:00',
        'Daily outreach run time in 24h HH:MM machine local time')
ON CONFLICT(key) DO NOTHING;

INSERT INTO settings (id, key, value, description)
VALUES (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-7000-8000-' || lower(hex(randomblob(6))),
        'outreach.schedule_enabled', 'true',
        'Whether the daily outreach schedule timer is enabled')
ON CONFLICT(key) DO NOTHING;
