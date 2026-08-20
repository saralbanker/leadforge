-- ============================================================================
-- Migration 021 — Ensure LLM, Composer, and Footer Settings
-- ============================================================================

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000001', 'llm.enabled', 'true', 'Enable or disable local LLM (Ollama) inference for outreach copy and hook generation');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000002', 'llm.api_url', 'http://localhost:11434', 'Base URL endpoint for Ollama or OpenAI-compatible local LM server');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000003', 'llm.model_name', 'llama3.1:8b', 'Target local model tag in Ollama (e.g. llama3.1:8b, mistral, qwen2.5:3b)');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000005', 'llm.max_tokens', '150', 'Maximum token generation limit (num_predict) per hook/draft generation call');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000020', 'outreach.composer_subject', 'Quick question re: {business_name}', 'Default subject template in outreach composer');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('01932a00-3000-7001-8000-000000000021', 'outreach.composer_body', '{observation_hook}

We help local companies build fast B2B order portals and scale digital acquisition.

Would you be open to a 10-minute chat this week?', 'Default body template in outreach composer');

-- Update footer company name if it is currently the placeholder 'Acme Growth Consultants'
UPDATE settings SET value = 'Orvion' WHERE key = 'outreach.footer_company_name' AND value = 'Acme Growth Consultants';
-- Ensure model is standardized to llama3.1:8b if set to llama3.2:3b
UPDATE settings SET value = 'llama3.1:8b' WHERE key = 'llm.model_name' AND value = 'llama3.2:3b';
