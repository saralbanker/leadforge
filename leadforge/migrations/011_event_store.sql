-- ============================================================================
-- Migration 011 — Ground Truth Event Store Schema & Immutability Triggers
-- Backlog Feature: LF-FND-001
-- ============================================================================

CREATE TABLE IF NOT EXISTS event_store (
    event_id TEXT PRIMARY KEY CHECK(length(event_id) = 36), -- UUIDv7
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    payload TEXT NOT NULL DEFAULT '{}',
    event_version INTEGER NOT NULL DEFAULT 1 CHECK(event_version >= 1),
    processed_status INTEGER NOT NULL DEFAULT 0 CHECK(processed_status IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_events_type_entity
    ON event_store(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_events_unprocessed
    ON event_store(processed_status, timestamp);

CREATE TRIGGER IF NOT EXISTS trg_event_store_no_update
BEFORE UPDATE ON event_store
FOR EACH ROW
BEGIN
    SELECT RAISE(FAIL, 'event_store records are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_event_store_no_delete
BEFORE DELETE ON event_store
FOR EACH ROW
BEGIN
    SELECT RAISE(FAIL, 'event_store records are immutable');
END;
