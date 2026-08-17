-- Migration 018: Communication Engine Schema Additions
-- Adds communication_threads, communication_messages, followup_schedules, and unsubscribe_suppressions tables.

CREATE TABLE IF NOT EXISTS communication_threads (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    opportunity_id TEXT REFERENCES opportunities(id) ON DELETE SET NULL,
    campaign_name TEXT NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'PLANNED',
    last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_comm_threads_biz ON communication_threads(business_id);
CREATE INDEX IF NOT EXISTS idx_comm_threads_state ON communication_threads(current_state);

CREATE TABLE IF NOT EXISTS communication_messages (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    thread_id TEXT NOT NULL REFERENCES communication_threads(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK(direction IN ('OUTBOUND', 'INBOUND')),
    message_id_header TEXT,
    sender_email TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    classification_label TEXT CHECK(classification_label IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL', 'UNSUBSCRIBE', 'BOUNCE', 'OUT_OF_OFFICE')),
    prompt_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_comm_msgs_thread ON communication_messages(thread_id);

CREATE TABLE IF NOT EXISTS followup_schedules (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    thread_id TEXT NOT NULL REFERENCES communication_threads(id) ON DELETE CASCADE,
    sequence_step INT NOT NULL DEFAULT 1,
    scheduled_for TIMESTAMP NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'EXECUTED', 'CANCELLED', 'SUPPRESSED')),
    trigger_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_followup_status_sched ON followup_schedules(status, scheduled_for);

CREATE TABLE IF NOT EXISTS unsubscribe_suppressions (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    email TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL DEFAULT 'PROSPECT_UNSUBSCRIBE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_unsubscribe_email ON unsubscribe_suppressions(email);
