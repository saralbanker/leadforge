-- WhatsApp-Auto: SQLite Schema for Solo Outreach Management

CREATE TABLE IF NOT EXISTS wa_contacts (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    area TEXT NOT NULL DEFAULT 'Ahmedabad',
    city TEXT NOT NULL DEFAULT 'Ahmedabad',
    products TEXT NOT NULL DEFAULT 'manufacturing',
    raw_phone TEXT NOT NULL,
    normalized_phone TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'leadforge',
    status TEXT NOT NULL DEFAULT 'PENDING',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wa_dispatch_logs (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL REFERENCES wa_contacts(id),
    template_name TEXT NOT NULL,
    message_text TEXT NOT NULL,
    dispatched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dispatch_status TEXT NOT NULL,
    response_received INTEGER DEFAULT 0,
    response_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wa_contacts_status ON wa_contacts(status);
CREATE INDEX IF NOT EXISTS idx_wa_contacts_phone ON wa_contacts(normalized_phone);
CREATE INDEX IF NOT EXISTS idx_wa_dispatch_contact ON wa_dispatch_logs(contact_id);
