-- ============================================================================
-- Migration 010 — Cold Email Outreach Extension Schema
-- Additive only: creates outreach and discovery logging queues
-- ============================================================================

-- Track discovered and checked business emails to avoid duplicate crawling
CREATE TABLE IF NOT EXISTS email_discovery_attempts (
    id                   TEXT    PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    business_id          TEXT    NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    domain               TEXT    NOT NULL,
    discovered_email     TEXT,
    discovery_status     TEXT    NOT NULL CHECK(discovery_status IN ('SUCCESS', 'NO_EMAIL_FOUND')),
    last_attempt_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Email drafts queue supporting human-in-the-loop validation
CREATE TABLE IF NOT EXISTS email_drafts (
    id                   TEXT    PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    opportunity_id       TEXT    NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    campaign_name        TEXT    NOT NULL,
    recipient_email      TEXT    NOT NULL,
    subject              TEXT    NOT NULL,
    body                 TEXT    NOT NULL,
    status               TEXT    NOT NULL CHECK(status IN ('PENDING_APPROVAL', 'APPROVED', 'SENT', 'FAILED', 'REJECTED')) DEFAULT 'PENDING_APPROVAL',
    error_message        TEXT,
    sent_at              TEXT,
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Index creation to optimize lookup and email scheduling searches
CREATE INDEX IF NOT EXISTS idx_email_discovery_attempts_business
    ON email_discovery_attempts(business_id);

CREATE INDEX IF NOT EXISTS idx_email_drafts_status
    ON email_drafts(status);

CREATE INDEX IF NOT EXISTS idx_email_drafts_opportunity
    ON email_drafts(opportunity_id);

CREATE INDEX IF NOT EXISTS idx_email_drafts_recipient
    ON email_drafts(recipient_email);
