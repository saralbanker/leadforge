-- ============================================================================
-- LeadForge Migration (003_opportunity_intelligence.sql)
-- Phase 3: Opportunity Intelligence Engine — Seed Data
-- Seeds configurable services and scoring rule weights.
-- No schema changes required; existing schema supports Phase 3 fully.
-- ============================================================================

-- ── Services Catalogue ───────────────────────────────────────────────────────
-- Default services LeadForge can pitch. Extensible — add rows, not code.
INSERT OR IGNORE INTO services (id, name, description, base_price) VALUES
    ('01932a00-0000-7001-8000-000000000001', 'Website Design & Development', 'Custom responsive website build', 25000.0),
    ('01932a00-0000-7001-8000-000000000002', 'SEO & Digital Marketing',      'Search engine optimisation + Google Ads management', 8000.0),
    ('01932a00-0000-7001-8000-000000000003', 'Social Media Management',      'Monthly social media content creation and posting', 5000.0),
    ('01932a00-0000-7001-8000-000000000004', 'Google Business Profile Setup','GMB optimisation and review strategy', 3000.0),
    ('01932a00-0000-7001-8000-000000000005', 'Website Audit & Consultation', 'One-time technical and UX audit with recommendations', 2000.0),
    ('01932a00-0000-7001-8000-000000000006', 'E-Commerce Setup',             'Online store build with payment gateway integration', 40000.0),
    ('01932a00-0000-7001-8000-000000000007', 'CRM & Lead Management',        'CRM setup and sales pipeline configuration', 12000.0),
    ('01932a00-0000-7001-8000-000000000008', 'WhatsApp Business Automation', 'WhatsApp API integration for customer engagement', 6000.0);

-- ── Category → Service Mappings (JSON arrays stored as settings) ─────────────
-- Format: opp.category_map.<normalised_category> = JSON array of service names
-- These drive which services are pitched for each business type.
-- Extend by inserting more rows — zero code changes required.
INSERT OR IGNORE INTO settings (id, key, value, description) VALUES
    ('01932a00-1000-7001-8000-000000000001',
     'opp.category_map.Manufacturers',
     '["Website Design & Development","SEO & Digital Marketing","CRM & Lead Management"]',
     'Service recommendations for Manufacturers category'),
    ('01932a00-1000-7001-8000-000000000002',
     'opp.category_map.Traders',
     '["Website Design & Development","E-Commerce Setup","Google Business Profile Setup"]',
     'Service recommendations for Traders category'),
    ('01932a00-1000-7001-8000-000000000003',
     'opp.category_map.Restaurants',
     '["Google Business Profile Setup","Social Media Management","WhatsApp Business Automation"]',
     'Service recommendations for Restaurants category'),
    ('01932a00-1000-7001-8000-000000000004',
     'opp.category_map.Hotels',
     '["Website Design & Development","Social Media Management","Google Business Profile Setup"]',
     'Service recommendations for Hotels category'),
    ('01932a00-1000-7001-8000-000000000005',
     'opp.category_map.Retailers',
     '["E-Commerce Setup","Social Media Management","Google Business Profile Setup"]',
     'Service recommendations for Retailers category'),
    ('01932a00-1000-7001-8000-000000000006',
     'opp.category_map.default',
     '["Website Design & Development","Google Business Profile Setup","SEO & Digital Marketing"]',
     'Default service recommendations when no specific category mapping exists'),

-- ── Scoring Rule Weights ─────────────────────────────────────────────────────
-- All weights are floats 0.0–100.0.  Total max is intentionally > 100 so
-- categories of signals can be weighted independently.
    ('01932a00-2000-7001-8000-000000000001',
     'opp.score.no_website',
     '40.0',
     'Score delta when business has no website (primary signal)'),
    ('01932a00-2000-7001-8000-000000000002',
     'opp.score.has_website',
     '10.0',
     'Base score delta when business has a website (upgrade opportunity)'),
    ('01932a00-2000-7001-8000-000000000003',
     'opp.score.has_email',
     '8.0',
     'Score delta for having a contact email (reachability signal)'),
    ('01932a00-2000-7001-8000-000000000004',
     'opp.score.has_phone',
     '5.0',
     'Score delta for having a phone number'),
    ('01932a00-2000-7001-8000-000000000005',
     'opp.score.review_high',
     '12.0',
     'Score delta when review count > 50 (strong social proof)'),
    ('01932a00-2000-7001-8000-000000000006',
     'opp.score.review_low',
     '6.0',
     'Score delta when review count > 0 but <= 50'),
    ('01932a00-2000-7001-8000-000000000007',
     'opp.score.rating_high',
     '10.0',
     'Score delta when rating >= 4.0'),
    ('01932a00-2000-7001-8000-000000000008',
     'opp.score.rating_low',
     '5.0',
     'Score delta when rating >= 3.0 and < 4.0'),
    ('01932a00-2000-7001-8000-000000000009',
     'opp.score.operational',
     '10.0',
     'Score delta when business_status is OPERATIONAL'),
    ('01932a00-2000-7001-8000-000000000010',
     'opp.score.temporarily_closed',
     '-10.0',
     'Score penalty when business is TEMPORARILY_CLOSED'),
    ('01932a00-2000-7001-8000-000000000011',
     'opp.score.permanently_closed',
     '-50.0',
     'Score penalty when business is PERMANENTLY_CLOSED'),
    ('01932a00-2000-7001-8000-000000000012',
     'opp.score.categories_known',
     '5.0',
     'Score delta when business categories metadata is present'),

-- ── Confidence Thresholds ────────────────────────────────────────────────────
    ('01932a00-3000-7001-8000-000000000001',
     'opp.confidence.high_threshold',
     '65.0',
     'Score >= this threshold → HIGH confidence opportunity'),
    ('01932a00-3000-7001-8000-000000000002',
     'opp.confidence.medium_threshold',
     '35.0',
     'Score >= this threshold (and < high) → MEDIUM confidence'),

-- ── Priority Thresholds ──────────────────────────────────────────────────────
    ('01932a00-4000-7001-8000-000000000001',
     'opp.priority.high_threshold',
     '60.0',
     'Score >= this threshold → HIGH priority'),
    ('01932a00-4000-7001-8000-000000000002',
     'opp.priority.medium_threshold',
     '30.0',
     'Score >= this threshold (and < high) → MEDIUM priority'),

-- ── Estimated Value Multipliers ──────────────────────────────────────────────
    ('01932a00-5000-7001-8000-000000000001',
     'opp.value.high_confidence_multiplier',
     '1.0',
     'Multiplier on base_price for HIGH confidence opportunities'),
    ('01932a00-5000-7001-8000-000000000002',
     'opp.value.medium_confidence_multiplier',
     '0.7',
     'Multiplier on base_price for MEDIUM confidence opportunities'),
    ('01932a00-5000-7001-8000-000000000003',
     'opp.value.low_confidence_multiplier',
     '0.4',
     'Multiplier on base_price for LOW confidence opportunities');
