-- Migration: 014_learning_tasks.sql
-- Description: Learning Engine Task Queue & Orchestration Schema (LF-LRN-001)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS learning_tasks (
    id TEXT PRIMARY KEY,
    source_entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    learning_type TEXT NOT NULL,
    priority INTEGER DEFAULT 50,
    status TEXT CHECK(status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELLED')) DEFAULT 'PENDING',
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    last_attempt_at TEXT,
    failure_reason TEXT,
    payload_json TEXT DEFAULT '{}',
    UNIQUE(source_entity, entity_id, learning_type)
);

CREATE INDEX IF NOT EXISTS idx_learning_tasks_status_priority
ON learning_tasks(status, priority DESC, scheduled_at ASC);

CREATE INDEX IF NOT EXISTS idx_learning_tasks_source_entity
ON learning_tasks(source_entity, entity_id);

CREATE INDEX IF NOT EXISTS idx_learning_tasks_scheduled
ON learning_tasks(scheduled_at);
