-- Migration: 012_knowledge_graph.sql
-- Description: Relational Knowledge Graph schema for LeadForge (LF-INT-001)

PRAGMA foreign_keys = ON;

-- 1. Industry Profiles
CREATE TABLE IF NOT EXISTS industry_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    description TEXT,
    avg_contract_value REAL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 2. Pain Patterns
CREATE TABLE IF NOT EXISTS pain_patterns (
    id TEXT PRIMARY KEY,
    industry_profile_id TEXT NOT NULL REFERENCES industry_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT CHECK(severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')) DEFAULT 'MEDIUM',
    created_at TEXT NOT NULL
);

-- 3. Objection Patterns
CREATE TABLE IF NOT EXISTS objection_patterns (
    id TEXT PRIMARY KEY,
    industry_profile_id TEXT NOT NULL REFERENCES industry_profiles(id) ON DELETE CASCADE,
    objection_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    suggested_response TEXT,
    created_at TEXT NOT NULL
);

-- 4. Offer Patterns
CREATE TABLE IF NOT EXISTS offer_patterns (
    id TEXT PRIMARY KEY,
    industry_profile_id TEXT NOT NULL REFERENCES industry_profiles(id) ON DELETE CASCADE,
    service_name TEXT NOT NULL,
    value_proposition TEXT NOT NULL,
    typical_price REAL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

-- 5. Reply Patterns
CREATE TABLE IF NOT EXISTS reply_patterns (
    id TEXT PRIMARY KEY,
    pattern_category TEXT NOT NULL,
    example_text TEXT NOT NULL,
    sentiment TEXT CHECK(sentiment IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE')) DEFAULT 'NEUTRAL',
    created_at TEXT NOT NULL
);

-- 6. Case Studies
CREATE TABLE IF NOT EXISTS case_studies (
    id TEXT PRIMARY KEY,
    industry_profile_id TEXT NOT NULL REFERENCES industry_profiles(id) ON DELETE CASCADE,
    client_pseudonym TEXT NOT NULL,
    headline TEXT NOT NULL,
    metrics_achieved TEXT,
    created_at TEXT NOT NULL
);

-- 7. Business Insights
CREATE TABLE IF NOT EXISTS business_insights (
    id TEXT PRIMARY KEY,
    business_id TEXT REFERENCES businesses(id) ON DELETE SET NULL,
    insight_type TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence_score REAL DEFAULT 1.0,
    created_at TEXT NOT NULL
);

-- 8. Knowledge Items
CREATE TABLE IF NOT EXISTS knowledge_items (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    key_name TEXT NOT NULL UNIQUE,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 9. Offer Pain Mappings (Link Table)
CREATE TABLE IF NOT EXISTS offer_pain_mappings (
    offer_pattern_id TEXT NOT NULL REFERENCES offer_patterns(id) ON DELETE CASCADE,
    pain_pattern_id TEXT NOT NULL REFERENCES pain_patterns(id) ON DELETE CASCADE,
    relevance_score REAL DEFAULT 1.0,
    PRIMARY KEY (offer_pattern_id, pain_pattern_id)
);

-- 10. Insight Pain Mappings (Link Table)
CREATE TABLE IF NOT EXISTS insight_pain_mappings (
    insight_id TEXT NOT NULL REFERENCES business_insights(id) ON DELETE CASCADE,
    pain_pattern_id TEXT NOT NULL REFERENCES pain_patterns(id) ON DELETE CASCADE,
    PRIMARY KEY (insight_id, pain_pattern_id)
);

-- Indexes for efficient relational querying
CREATE INDEX IF NOT EXISTS idx_industry_profiles_code ON industry_profiles(code);
CREATE INDEX IF NOT EXISTS idx_pain_patterns_industry ON pain_patterns(industry_profile_id);
CREATE INDEX IF NOT EXISTS idx_objection_patterns_industry ON objection_patterns(industry_profile_id);
CREATE INDEX IF NOT EXISTS idx_offer_patterns_industry ON offer_patterns(industry_profile_id);
CREATE INDEX IF NOT EXISTS idx_case_studies_industry ON case_studies(industry_profile_id);
CREATE INDEX IF NOT EXISTS idx_business_insights_business ON business_insights(business_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_topic ON knowledge_items(topic);
