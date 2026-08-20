-- ============================================================================
-- Migration 020 — Email Draft Status Repair
-- Updates CHECK constraint on email_drafts.status to include QUEUED and CANCELLED.
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_drafts_new (
    id                   TEXT    PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    opportunity_id       TEXT    NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    campaign_name        TEXT    NOT NULL,
    recipient_email      TEXT    NOT NULL,
    subject              TEXT    NOT NULL,
    body                 TEXT    NOT NULL,
    status               TEXT    NOT NULL CHECK(status IN ('PENDING_APPROVAL', 'APPROVED', 'QUEUED', 'SENT', 'FAILED', 'REJECTED', 'CANCELLED')) DEFAULT 'PENDING_APPROVAL',
    error_message        TEXT,
    sent_at              TEXT,
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT OR IGNORE INTO email_drafts_new (id, opportunity_id, campaign_name, recipient_email, subject, body, status, error_message, sent_at, created_at, updated_at)
SELECT id, opportunity_id, campaign_name, recipient_email, subject, body, status, error_message, sent_at, created_at, updated_at
FROM email_drafts;

DROP TABLE email_drafts;

ALTER TABLE email_drafts_new RENAME TO email_drafts;

CREATE INDEX IF NOT EXISTS idx_email_drafts_status
    ON email_drafts(status);

CREATE INDEX IF NOT EXISTS idx_email_drafts_opportunity
    ON email_drafts(opportunity_id);

CREATE INDEX IF NOT EXISTS idx_email_drafts_recipient
    ON email_drafts(recipient_email);
