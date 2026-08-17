-- ============================================================================
-- LeadForge Canonical Database Schema (SQLite Version)
-- Version: 2.0 (UUIDv7 & Domain-First Partitioned)
-- ============================================================================

-- Enable foreign key constraints in SQLite (must be run at connection startup)
PRAGMA foreign_keys = ON;

-- ============================================================================
-- 1. REFERENCE DATA CONTEXT (Lookup Tables)
-- ============================================================================

CREATE TABLE industries (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT
);

CREATE TABLE business_types (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT
);

CREATE TABLE lead_statuses (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL CHECK(category IN ('OPEN', 'CONTACTED', 'QUALIFIED', 'UNQUALIFIED', 'LOST')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE services (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    base_price REAL NOT NULL DEFAULT 0.0 CHECK(base_price >= 0.0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT
);

CREATE TABLE discovery_sources (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK(source_type IN ('SCRAPER', 'MANUAL_IMPORT', 'API_INTEGRATION', 'REFERRAL')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================================
-- 2. MASTER DATA CONTEXT
-- ============================================================================

CREATE TABLE businesses (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    google_place_id TEXT UNIQUE CHECK(google_place_id IS NULL OR length(google_place_id) > 0),
    gst_number TEXT UNIQUE CHECK(gst_number IS NULL OR length(gst_number) = 15),
    website_domain TEXT,
    normalized_name TEXT NOT NULL,
    name TEXT NOT NULL,
    display_phone TEXT,
    contact_email TEXT,
    industry_id TEXT REFERENCES industries(id) ON DELETE RESTRICT,
    business_type_id TEXT REFERENCES business_types(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT
);

CREATE TABLE addresses (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    address_line TEXT NOT NULL,
    area TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    latitude REAL CHECK(latitude IS NULL OR (latitude BETWEEN -90.0 AND 90.0)),
    longitude REAL CHECK(longitude IS NULL OR (longitude BETWEEN -180.0 AND 180.0)),
    is_primary INTEGER NOT NULL DEFAULT 1 CHECK(is_primary IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE contacts (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    first_name TEXT NOT NULL,
    last_name TEXT,
    email TEXT,
    phone TEXT,
    designation TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE salespersons (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE CHECK(email LIKE '%@%'),
    phone TEXT,
    role TEXT NOT NULL CHECK(role IN ('ADMIN', 'SALES_MANAGER', 'SALES_REP')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'INACTIVE')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================================
-- 3. DIGITAL PRESENCE & WEBSITE AUDITS CONTEXT
-- ============================================================================

CREATE TABLE digital_presences (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    website_url TEXT,
    has_website INTEGER NOT NULL DEFAULT 1 CHECK(has_website IN (0, 1)),
    platform TEXT, -- e.g. WordPress, Shopify, Custom
    social_links_json TEXT, -- Raw JSON containing profiles
    ssl_valid INTEGER CHECK(ssl_valid IN (0, 1, NULL)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE website_audits (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    digital_presence_id TEXT NOT NULL REFERENCES digital_presences(id) ON DELETE CASCADE,
    lighthouse_score INTEGER CHECK(lighthouse_score IS NULL OR (lighthouse_score BETWEEN 0 AND 100)),
    page_speed_ms INTEGER CHECK(page_speed_ms IS NULL OR page_speed_ms >= 0),
    issues_json TEXT, -- JSON structure of detected performance/meta issues
    recommendation_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE digital_maturities (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    maturity_score REAL NOT NULL CHECK(maturity_score BETWEEN 0.0 AND 100.0),
    grade TEXT NOT NULL CHECK(grade IN ('A', 'B', 'C', 'D', 'F')),
    details_json TEXT,
    audited_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================================
-- 4. LEAD MANAGEMENT CONTEXT
-- ============================================================================

CREATE TABLE leads (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE RESTRICT,
    source_id TEXT NOT NULL REFERENCES discovery_sources(id) ON DELETE RESTRICT,
    status_id TEXT NOT NULL REFERENCES lead_statuses(id) ON DELETE RESTRICT,
    campaign_name TEXT,
    custom_fields_json TEXT,
    raw_payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT
);

-- ============================================================================
-- 5. OPPORTUNITY ENGINE CONTEXT
-- ============================================================================

CREATE TABLE opportunities (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    pipeline_stage TEXT NOT NULL CHECK(pipeline_stage IN ('PROSPECTING', 'QUALIFICATION', 'PROPOSAL_SENT', 'NEGOTIATION', 'CLOSED_WON', 'CLOSED_LOST')),
    score REAL NOT NULL DEFAULT 0.0,
    estimated_value REAL NOT NULL DEFAULT 0.0 CHECK(estimated_value >= 0.0),
    close_probability REAL NOT NULL DEFAULT 0.0 CHECK(close_probability BETWEEN 0.0 AND 1.0),
    closing_date TEXT,
    assigned_salesperson_id TEXT REFERENCES salespersons(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT
);

CREATE TABLE opportunity_scoring_logs (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    rule_name TEXT NOT NULL,
    score_delta REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE proposals (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    proposal_number TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'SENT', 'ACCEPTED', 'REJECTED', 'EXPIRED')),
    total_amount REAL NOT NULL DEFAULT 0.0 CHECK(total_amount >= 0.0),
    sent_at TEXT,
    accepted_at TEXT,
    pdf_url TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE proposal_services (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    proposal_id TEXT NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    service_id TEXT NOT NULL REFERENCES services(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0.0),
    total_price REAL NOT NULL CHECK(total_price >= 0.0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================================
-- 6. SALES & ACTIVITY HISTORY CONTEXT
-- ============================================================================

CREATE TABLE discovery_history (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    source_id TEXT NOT NULL REFERENCES discovery_sources(id) ON DELETE RESTRICT,
    run_timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    records_found INTEGER NOT NULL CHECK(records_found >= 0),
    status TEXT NOT NULL CHECK(status IN ('SUCCESS', 'WARNING', 'FAILED')),
    log_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE search_history (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    city TEXT NOT NULL,
    category TEXT NOT NULL,
    search_query TEXT,
    run_by_salesperson_id TEXT REFERENCES salespersons(id) ON DELETE SET NULL,
    results_count INTEGER NOT NULL DEFAULT 0 CHECK(results_count >= 0),
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE activity_timeline (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    opportunity_id TEXT REFERENCES opportunities(id) ON DELETE CASCADE,
    salesperson_id TEXT REFERENCES salespersons(id) ON DELETE SET NULL,
    activity_type TEXT NOT NULL CHECK(activity_type IN ('LEAD_SCRAPED', 'STAGE_CHANGED', 'CALL', 'MEETING', 'PROPOSAL_SENT', 'NOTE_ADDED')),
    title TEXT NOT NULL,
    description TEXT,
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reference_id TEXT, -- Links to specific physical UUID (e.g. call_logs, meetings)
    reference_type TEXT, -- Identifies reference table name (e.g. 'call_logs', 'meetings')
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE call_logs (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    salesperson_id TEXT NOT NULL REFERENCES salespersons(id) ON DELETE RESTRICT,
    contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    duration_seconds INTEGER NOT NULL DEFAULT 0 CHECK(duration_seconds >= 0),
    outcome TEXT NOT NULL CHECK(outcome IN ('CONNECTED', 'BUSY', 'NO_ANSWER', 'FAILED', 'VOICEMAIL')),
    recording_url TEXT,
    notes TEXT,
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE meetings (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    salesperson_id TEXT NOT NULL REFERENCES salespersons(id) ON DELETE RESTRICT,
    contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    opportunity_id TEXT REFERENCES opportunities(id) ON DELETE CASCADE,
    scheduled_at TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
    status TEXT NOT NULL CHECK(status IN ('SCHEDULED', 'COMPLETED', 'CANCELLED', 'NOSHOW')),
    location_type TEXT NOT NULL CHECK(location_type IN ('IN_PERSON', 'VIRTUAL')),
    meeting_link TEXT,
    agenda TEXT,
    minutes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ============================================================================
-- 7. AUDITING & COMPLIANCE (Immutable)
-- ============================================================================

CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK(action_type IN ('INSERT', 'UPDATE', 'DELETE')),
    actor TEXT NOT NULL,
    before_state_json TEXT, -- State prior to mutation (Nullable on INSERT)
    after_state_json TEXT, -- State post-mutation (Nullable on DELETE)
    client_metadata_json TEXT, -- Device ID, IP, user-agent details
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE event_store (
    event_id TEXT PRIMARY KEY CHECK(length(event_id) = 36), -- UUIDv7
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    payload TEXT NOT NULL DEFAULT '{}',
    event_version INTEGER NOT NULL DEFAULT 1 CHECK(event_version >= 1),
    processed_status INTEGER NOT NULL DEFAULT 0 CHECK(processed_status IN (0, 1))
);


-- ============================================================================
-- 8. SYSTEM SETTINGS & PREFERENCES CONTEXT
-- ============================================================================

CREATE TABLE settings (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE user_preferences (
    id TEXT PRIMARY KEY CHECK(length(id) = 36), -- UUIDv7
    salesperson_id TEXT NOT NULL REFERENCES salespersons(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(salesperson_id, key)
);

-- ============================================================================
-- INDEXES FOR QUERY OPTIMIZATION & REFERENTIAL SPEED
-- ============================================================================

-- Foreign Keys Indexes (Prevents lock contention and full-scans on joins)
CREATE INDEX idx_businesses_industry ON businesses(industry_id);
CREATE INDEX idx_businesses_type ON businesses(business_type_id);
CREATE INDEX idx_addresses_business ON addresses(business_id);
CREATE INDEX idx_contacts_business ON contacts(business_id);
CREATE INDEX idx_digital_presences_business ON digital_presences(business_id);
CREATE INDEX idx_website_audits_presence ON website_audits(digital_presence_id);
CREATE INDEX idx_digital_maturities_business ON digital_maturities(business_id);
CREATE INDEX idx_leads_business ON leads(business_id);
CREATE INDEX idx_leads_source ON leads(source_id);
CREATE INDEX idx_leads_status ON leads(status_id);
CREATE INDEX idx_opportunities_business ON opportunities(business_id);
CREATE INDEX idx_opportunities_salesperson ON opportunities(assigned_salesperson_id);
CREATE INDEX idx_opportunity_scoring_logs_opportunity ON opportunity_scoring_logs(opportunity_id);
CREATE INDEX idx_proposals_opportunity ON proposals(opportunity_id);
CREATE INDEX idx_proposal_services_proposal ON proposal_services(proposal_id);
CREATE INDEX idx_proposal_services_service ON proposal_services(service_id);
CREATE INDEX idx_discovery_history_source ON discovery_history(source_id);
CREATE INDEX idx_search_history_salesperson ON search_history(run_by_salesperson_id);
CREATE INDEX idx_activity_timeline_business ON activity_timeline(business_id);
CREATE INDEX idx_activity_timeline_opportunity ON activity_timeline(opportunity_id);
CREATE INDEX idx_activity_timeline_salesperson ON activity_timeline(salesperson_id);
CREATE INDEX idx_call_logs_salesperson ON call_logs(salesperson_id);
CREATE INDEX idx_call_logs_contact ON call_logs(contact_id);
CREATE INDEX idx_meetings_salesperson ON meetings(salesperson_id);
CREATE INDEX idx_meetings_contact ON meetings(contact_id);
CREATE INDEX idx_meetings_opportunity ON meetings(opportunity_id);
CREATE INDEX idx_user_preferences_salesperson ON user_preferences(salesperson_id);

-- Lookup Performance & Domain Validation Indexes
CREATE INDEX idx_businesses_normalized_name ON businesses(normalized_name);
CREATE INDEX idx_businesses_google_place_id ON businesses(google_place_id) WHERE google_place_id IS NOT NULL;
CREATE INDEX idx_businesses_gst_number ON businesses(gst_number) WHERE gst_number IS NOT NULL;
CREATE INDEX idx_businesses_website_domain ON businesses(website_domain) WHERE website_domain IS NOT NULL;
CREATE INDEX idx_businesses_display_phone ON businesses(display_phone) WHERE display_phone IS NOT NULL;
CREATE INDEX idx_opportunities_stage ON opportunities(pipeline_stage);
CREATE INDEX idx_audit_logs_lookup ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_logs_occurred_at ON audit_logs(occurred_at);
CREATE INDEX idx_events_type_entity ON event_store(entity_type, entity_id);
CREATE INDEX idx_events_unprocessed ON event_store(processed_status, timestamp);


-- ============================================================================
-- SYSTEM UPDATE TRIGGERS (Automated Metadata Operations)
-- ============================================================================

CREATE TRIGGER trg_industries_updated_at AFTER UPDATE ON industries FOR EACH ROW BEGIN
    UPDATE industries SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_business_types_updated_at AFTER UPDATE ON business_types FOR EACH ROW BEGIN
    UPDATE business_types SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_lead_statuses_updated_at AFTER UPDATE ON lead_statuses FOR EACH ROW BEGIN
    UPDATE lead_statuses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_services_updated_at AFTER UPDATE ON services FOR EACH ROW BEGIN
    UPDATE services SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_discovery_sources_updated_at AFTER UPDATE ON discovery_sources FOR EACH ROW BEGIN
    UPDATE discovery_sources SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_businesses_updated_at AFTER UPDATE ON businesses FOR EACH ROW BEGIN
    UPDATE businesses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_addresses_updated_at AFTER UPDATE ON addresses FOR EACH ROW BEGIN
    UPDATE addresses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_contacts_updated_at AFTER UPDATE ON contacts FOR EACH ROW BEGIN
    UPDATE contacts SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_salespersons_updated_at AFTER UPDATE ON salespersons FOR EACH ROW BEGIN
    UPDATE salespersons SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_digital_presences_updated_at AFTER UPDATE ON digital_presences FOR EACH ROW BEGIN
    UPDATE digital_presences SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_website_audits_updated_at AFTER UPDATE ON website_audits FOR EACH ROW BEGIN
    UPDATE website_audits SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_digital_maturities_updated_at AFTER UPDATE ON digital_maturities FOR EACH ROW BEGIN
    UPDATE digital_maturities SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_leads_updated_at AFTER UPDATE ON leads FOR EACH ROW BEGIN
    UPDATE leads SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_opportunities_updated_at AFTER UPDATE ON opportunities FOR EACH ROW BEGIN
    UPDATE opportunities SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_proposals_updated_at AFTER UPDATE ON proposals FOR EACH ROW BEGIN
    UPDATE proposals SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_meetings_updated_at AFTER UPDATE ON meetings FOR EACH ROW BEGIN
    UPDATE meetings SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_settings_updated_at AFTER UPDATE ON settings FOR EACH ROW BEGIN
    UPDATE settings SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_user_preferences_updated_at AFTER UPDATE ON user_preferences FOR EACH ROW BEGIN
    UPDATE user_preferences SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_event_store_no_update BEFORE UPDATE ON event_store FOR EACH ROW BEGIN
    SELECT RAISE(FAIL, 'event_store records are immutable');
END;

CREATE TRIGGER trg_event_store_no_delete BEFORE DELETE ON event_store FOR EACH ROW BEGIN
    SELECT RAISE(FAIL, 'event_store records are immutable');
END;

-- ============================================================================
-- RELATIONAL KNOWLEDGE GRAPH TABLES (LF-INT-001)
-- ============================================================================

CREATE TABLE IF NOT EXISTS industry_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    description TEXT,
    avg_contract_value REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pain_patterns (
    id TEXT PRIMARY KEY,
    industry_profile_id TEXT NOT NULL REFERENCES industry_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT CHECK(severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')) DEFAULT 'MEDIUM',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objection_patterns (
    id TEXT PRIMARY KEY,
    industry_profile_id TEXT NOT NULL REFERENCES industry_profiles(id) ON DELETE CASCADE,
    objection_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    suggested_response TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_patterns (
    id TEXT PRIMARY KEY,
    industry_profile_id TEXT NOT NULL REFERENCES industry_profiles(id) ON DELETE CASCADE,
    service_name TEXT NOT NULL,
    value_proposition TEXT NOT NULL,
    typical_price REAL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reply_patterns (
    id TEXT PRIMARY KEY,
    pattern_category TEXT NOT NULL,
    example_text TEXT NOT NULL,
    sentiment TEXT CHECK(sentiment IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE')) DEFAULT 'NEUTRAL',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_studies (
    id TEXT PRIMARY KEY,
    industry_profile_id TEXT NOT NULL REFERENCES industry_profiles(id) ON DELETE CASCADE,
    client_pseudonym TEXT NOT NULL,
    headline TEXT NOT NULL,
    metrics_achieved TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS business_insights (
    id TEXT PRIMARY KEY,
    business_id TEXT REFERENCES businesses(id) ON DELETE SET NULL,
    insight_type TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence_score REAL DEFAULT 1.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_items (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    key_name TEXT NOT NULL UNIQUE,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_pain_mappings (
    offer_pattern_id TEXT NOT NULL REFERENCES offer_patterns(id) ON DELETE CASCADE,
    pain_pattern_id TEXT NOT NULL REFERENCES pain_patterns(id) ON DELETE CASCADE,
    relevance_score REAL DEFAULT 1.0,
    PRIMARY KEY (offer_pattern_id, pain_pattern_id)
);

CREATE TABLE IF NOT EXISTS insight_pain_mappings (
    insight_id TEXT NOT NULL REFERENCES business_insights(id) ON DELETE CASCADE,
    pain_pattern_id TEXT NOT NULL REFERENCES pain_patterns(id) ON DELETE CASCADE,
    PRIMARY KEY (insight_id, pain_pattern_id)
);

CREATE INDEX IF NOT EXISTS idx_industry_profiles_code ON industry_profiles(code);
CREATE INDEX IF NOT EXISTS idx_pain_patterns_industry ON pain_patterns(industry_profile_id);
CREATE INDEX IF NOT EXISTS idx_objection_patterns_industry ON objection_patterns(industry_profile_id);
CREATE INDEX IF NOT EXISTS idx_offer_patterns_industry ON offer_patterns(industry_profile_id);
CREATE INDEX IF NOT EXISTS idx_case_studies_industry ON case_studies(industry_profile_id);
CREATE INDEX IF NOT EXISTS idx_business_insights_business ON business_insights(business_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_topic ON knowledge_items(topic);

-- ============================================================================
-- RELATIONAL KNOWLEDGE VERSIONING TABLES (LF-INT-002)
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge_item_versions (
    id TEXT PRIMARY KEY,
    key_name TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    previous_version_id TEXT REFERENCES knowledge_item_versions(id) ON DELETE RESTRICT,
    topic TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT CHECK(created_by IN ('FOUNDER', 'SYSTEM')) DEFAULT 'FOUNDER',
    status TEXT CHECK(status IN ('DRAFT', 'ACTIVE', 'DEPRECATED', 'ARCHIVED')) DEFAULT 'DRAFT',
    change_reason TEXT,
    confidence_score REAL DEFAULT 1.0,
    evidence_reference TEXT,
    UNIQUE(key_name, version_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_item_versions_unique_active
ON knowledge_item_versions(key_name)
WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_knowledge_item_versions_key_status
ON knowledge_item_versions(key_name, status);

CREATE INDEX IF NOT EXISTS idx_knowledge_item_versions_created_at
ON knowledge_item_versions(created_at);

CREATE TABLE IF NOT EXISTS industry_profile_versions (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    previous_version_id TEXT REFERENCES industry_profile_versions(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    description TEXT,
    avg_contract_value REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    created_by TEXT CHECK(created_by IN ('FOUNDER', 'SYSTEM')) DEFAULT 'FOUNDER',
    status TEXT CHECK(status IN ('DRAFT', 'ACTIVE', 'DEPRECATED', 'ARCHIVED')) DEFAULT 'DRAFT',
    change_reason TEXT,
    confidence_score REAL DEFAULT 1.0,
    evidence_reference TEXT,
    UNIQUE(code, version_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_industry_profile_versions_unique_active
ON industry_profile_versions(code)
WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_industry_profile_versions_code_status
ON industry_profile_versions(code, status);

-- ============================================================================
-- LEARNING ENGINE TASK QUEUE & ORCHESTRATION SCHEMA (LF-LRN-001)
-- ============================================================================

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

-- ============================================================================
-- SEARCH INTELLIGENCE GEOGRAPHIC CACHE SCHEMA (LF-SIL-008)
-- ============================================================================

CREATE TABLE IF NOT EXISTS sil_geo_cache (
    id          TEXT PRIMARY KEY CHECK(length(id) = 36),
    city        TEXT NOT NULL,
    place_name  TEXT NOT NULL,
    place_type  TEXT NOT NULL,
    fetched_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S.%fZ', 'now')),
    UNIQUE(city, place_name)
);

CREATE INDEX IF NOT EXISTS idx_sil_geo_cache_city
ON sil_geo_cache(city);

-- ============================================================================
-- CAMPAIGN PLAN METRICS SCHEMA (LF-CMP-009)
-- ============================================================================

CREATE TABLE IF NOT EXISTS campaign_plan_metrics (
    id                   TEXT    PRIMARY KEY CHECK(length(id) = 36),
    search_id            TEXT    NOT NULL,
    plan_idx             INTEGER NOT NULL CHECK(plan_idx >= 0),
    search_query         TEXT    NOT NULL,
    canonical_category   TEXT    NOT NULL,
    geographic_partition TEXT    NOT NULL,
    urls_discovered      INTEGER NOT NULL DEFAULT 0 CHECK(urls_discovered >= 0),
    discovery_duplicates INTEGER NOT NULL DEFAULT 0 CHECK(discovery_duplicates >= 0),
    discovery_duration_s REAL    NOT NULL DEFAULT 0.0 CHECK(discovery_duration_s >= 0.0),
    urls_processed       INTEGER NOT NULL DEFAULT 0 CHECK(urls_processed >= 0),
    qualified            INTEGER NOT NULL DEFAULT 0 CHECK(qualified >= 0),
    consumer_duplicates  INTEGER NOT NULL DEFAULT 0 CHECK(consumer_duplicates >= 0),
    website_rejections   INTEGER NOT NULL DEFAULT 0 CHECK(website_rejections >= 0),
    phone_rejections     INTEGER NOT NULL DEFAULT 0 CHECK(phone_rejections >= 0),
    validation_failures  INTEGER NOT NULL DEFAULT 0 CHECK(validation_failures >= 0),
    processing_duration_s REAL   NOT NULL DEFAULT 0.0 CHECK(processing_duration_s >= 0.0),
    yield_percentage     REAL    NOT NULL DEFAULT 0.0,
    duplicate_percentage REAL    NOT NULL DEFAULT 0.0,
    recorded_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(search_id, plan_idx)
);

CREATE INDEX IF NOT EXISTS idx_campaign_plan_metrics_search_id
    ON campaign_plan_metrics(search_id);

-- ============================================================================
-- OUTREACH EXTENSION & EMAIL DISCOVERY SCHEMA (LF-OUT-010)
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_discovery_attempts (
    id                   TEXT    PRIMARY KEY CHECK(length(id) = 36),
    business_id          TEXT    NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    domain               TEXT    NOT NULL,
    discovered_email     TEXT,
    discovery_status     TEXT    NOT NULL CHECK(discovery_status IN ('SUCCESS', 'NO_EMAIL_FOUND')),
    last_attempt_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS email_drafts (
    id                   TEXT    PRIMARY KEY CHECK(length(id) = 36),
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

CREATE INDEX IF NOT EXISTS idx_email_discovery_attempts_business
    ON email_discovery_attempts(business_id);

CREATE INDEX IF NOT EXISTS idx_email_drafts_status
    ON email_drafts(status);

CREATE INDEX IF NOT EXISTS idx_email_drafts_opportunity
    ON email_drafts(opportunity_id);

CREATE INDEX IF NOT EXISTS idx_email_drafts_recipient
    ON email_drafts(recipient_email);

-- ============================================================================
-- A/B CAMPAIGN TESTING SCHEMA (LF-EXP-001)
-- ============================================================================

CREATE TABLE IF NOT EXISTS experiments (
    id                    TEXT PRIMARY KEY CHECK(length(id) = 36),
    name                  TEXT NOT NULL UNIQUE,
    hypothesis            TEXT NOT NULL,
    variable_type         TEXT NOT NULL CHECK(variable_type IN ('SUBJECT', 'BODY_HOOK', 'CTA', 'SEQUENCE_DELAY')),
    control_value         TEXT NOT NULL,
    variant_value         TEXT NOT NULL,
    sample_size_required  INTEGER NOT NULL DEFAULT 100 CHECK(sample_size_required > 0),
    control_sent_count    INTEGER NOT NULL DEFAULT 0 CHECK(control_sent_count >= 0),
    variant_sent_count    INTEGER NOT NULL DEFAULT 0 CHECK(variant_sent_count >= 0),
    control_success_count INTEGER NOT NULL DEFAULT 0 CHECK(control_success_count >= 0),
    variant_success_count INTEGER NOT NULL DEFAULT 0 CHECK(variant_success_count >= 0),
    status                TEXT NOT NULL CHECK(status IN ('DRAFT', 'RUNNING', 'COMPLETED', 'PAUSED')) DEFAULT 'RUNNING',
    p_value               REAL,
    winning_value         TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_experiments_status
ON experiments(status);

CREATE INDEX IF NOT EXISTS idx_experiments_name
ON experiments(name);






