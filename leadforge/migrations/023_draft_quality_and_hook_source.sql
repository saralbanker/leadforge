-- Persist the quality verdict and the hook's provenance on each draft.
--
-- Both were previously computed and thrown away: the quality score went into
-- the HTTP response only, and a fallback hook (used whenever the LLM was
-- unreachable) was indistinguishable from a real generation. Neither could be
-- enforced at approval time, which is what blocked safe auto-approval.

ALTER TABLE email_drafts ADD COLUMN quality_score INTEGER;
ALTER TABLE email_drafts ADD COLUMN quality_passed INTEGER;
ALTER TABLE email_drafts ADD COLUMN quality_issues TEXT;   -- JSON array

-- 'llm'      : written by the model
-- 'fallback' : the deterministic stand-in used when the model was unavailable
ALTER TABLE email_drafts ADD COLUMN hook_source TEXT;

CREATE INDEX IF NOT EXISTS idx_email_drafts_quality_score
    ON email_drafts(quality_score);

CREATE INDEX IF NOT EXISTS idx_email_drafts_hook_source
    ON email_drafts(hook_source);

-- Minimum score a draft must reach before bulk approval will accept it.
-- Single approvals stay manual and are not gated.
INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000023', 'outreach.min_quality_score', '80',
        'Bulk approval rejects drafts scoring below this (0-100).');

-- When true, bulk approval refuses drafts whose hook came from the fallback
-- rather than the model, so an Ollama outage cannot mail identical boilerplate.
INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000024', 'outreach.require_llm_hook', 'true',
        'Bulk approval rejects drafts whose hook was the deterministic fallback.');
