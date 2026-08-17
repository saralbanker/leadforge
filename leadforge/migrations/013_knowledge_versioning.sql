-- Migration: 013_knowledge_versioning.sql
-- Description: Knowledge Versioning Engine & Audit Layer (LF-INT-002)

PRAGMA foreign_keys = ON;

-- 1. Knowledge Item Versions Table
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

-- Partial Unique Index enforcing AT MOST ONE ACTIVE version per key_name
CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_item_versions_unique_active
ON knowledge_item_versions(key_name)
WHERE status = 'ACTIVE';

-- Index for historical queries and lookup by status
CREATE INDEX IF NOT EXISTS idx_knowledge_item_versions_key_status
ON knowledge_item_versions(key_name, status);

CREATE INDEX IF NOT EXISTS idx_knowledge_item_versions_created_at
ON knowledge_item_versions(created_at);

-- 2. Industry Profile Versions Table
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

-- Partial Unique Index enforcing AT MOST ONE ACTIVE version per industry code
CREATE UNIQUE INDEX IF NOT EXISTS idx_industry_profile_versions_unique_active
ON industry_profile_versions(code)
WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_industry_profile_versions_code_status
ON industry_profile_versions(code, status);
