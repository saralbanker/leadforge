-- Migration 029 - Keep known-dead directory providers disabled by default.

INSERT INTO settings (id, key, value, description)
VALUES (
    lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-7000-8000-' || lower(hex(randomblob(6))),
    'enrichment.directory_providers_enabled',
    'false',
    'Enable IndiaMart, Justdial, and TradeIndia enrichment providers'
)
ON CONFLICT(key) DO NOTHING;
