-- ============================================================================
-- LeadForge Migration 004: Intelligence Quality — Phase 4
-- Adds refined scoring weights, digital maturity thresholds, and new signals.
-- No schema changes. All configuration lives in the settings table.
-- ============================================================================

-- ── Rebalanced Scoring Weights ────────────────────────────────────────────────
-- Replaces Phase 3 defaults with Phase 4 calibrated values.
-- Existing rows are updated; new rows are inserted.

-- Website signals: no_website stays primary signal
INSERT OR REPLACE INTO settings (id, key, value, description) VALUES
    ('01932a00-2000-7001-8000-000000000001',
     'opp.score.no_website',
     '45.0',
     '[P4] Business has no website — primary digital-gap signal. Raised from 40 to 45.'),

    ('01932a00-2000-7001-8000-000000000002',
     'opp.score.has_website',
     '8.0',
     '[P4] Website present — upgrade/audit opportunity. Reduced from 10 to 8 (base signal).'),

-- Contact signals: email is more valuable than phone for outreach
    ('01932a00-2000-7001-8000-000000000003',
     'opp.score.has_email',
     '10.0',
     '[P4] Contact email present — outreach viability signal. Raised from 8 to 10.'),

    ('01932a00-2000-7001-8000-000000000004',
     'opp.score.has_phone',
     '3.0',
     '[P4] Phone number present — weak signal, reduced from 5 to 3 (existence, not quality).'),

-- Review volume: 3-tier now (none / low / high)
    ('01932a00-2000-7001-8000-000000000005',
     'opp.score.review_high',
     '15.0',
     '[P4] >100 reviews — strong social proof. Raised from 12. Threshold raised to 100.'),

    ('01932a00-2000-7001-8000-000000000006',
     'opp.score.review_mid',
     '8.0',
     '[P4] 10-100 reviews — moderate social proof (new tier).'),

    ('01932a00-2000-7001-8000-200000000006',
     'opp.score.review_low',
     '3.0',
     '[P4] 1-9 reviews — minimal social proof. Reduced from 6.'),

    ('01932a00-2000-7001-8000-300000000006',
     'opp.score.review_none',
     '-5.0',
     '[P4] 0 reviews on Maps — low-visibility penalty (new signal).'),

-- Rating: tighter bands with floor for very low ratings
    ('01932a00-2000-7001-8000-000000000007',
     'opp.score.rating_high',
     '12.0',
     '[P4] Rating >= 4.2 — high-quality. Raised from 10, threshold tightened.'),

    ('01932a00-2000-7001-8000-000000000008',
     'opp.score.rating_mid',
     '6.0',
     '[P4] Rating 3.5-4.2 — acceptable (new mid tier).'),

    ('01932a00-2000-7001-8000-200000000008',
     'opp.score.rating_low',
     '2.0',
     '[P4] Rating 3.0-3.5 — borderline. Reduced from 5.'),

    ('01932a00-2000-7001-8000-300000000008',
     'opp.score.rating_poor',
     '-8.0',
     '[P4] Rating < 3.0 — reputational risk, penalty signal (new).'),

-- Operational status: wider gap between closed and operational
    ('01932a00-2000-7001-8000-000000000009',
     'opp.score.operational',
     '12.0',
     '[P4] Business is OPERATIONAL — raised from 10.'),

    ('01932a00-2000-7001-8000-000000000010',
     'opp.score.temporarily_closed',
     '-15.0',
     '[P4] Temporarily closed — raised penalty from -10 to -15.'),

    ('01932a00-2000-7001-8000-000000000011',
     'opp.score.permanently_closed',
     '-60.0',
     '[P4] Permanently closed — raised penalty from -50 to -60.'),

-- Removed: categories_known (noise signal — removed from scoring)
-- Categories metadata is now used only for digital maturity, not scoring.

-- ── Digital Maturity Signals (new in P4) ─────────────────────────────────────
    ('01932a00-2000-7001-8000-400000000001',
     'opp.score.dm.no_website',
     '-10.0',
     '[P4] Digital maturity: no website is a strong digital-gap indicator (additive to main signal).'),

    ('01932a00-2000-7001-8000-400000000002',
     'opp.score.dm.no_reviews',
     '-5.0',
     '[P4] Digital maturity: zero reviews = not indexed/visible on Maps.'),

    ('01932a00-2000-7001-8000-400000000003',
     'opp.score.dm.has_email',
     '5.0',
     '[P4] Digital maturity: email contact = some digital footprint.'),

    ('01932a00-2000-7001-8000-400000000004',
     'opp.score.dm.low_rating',
     '-8.0',
     '[P4] Digital maturity: rating < 3.0 = reputational risk for digital channels.'),

-- ── Evidence Count Thresholds (for confidence engine) ────────────────────────
    ('01932a00-3000-7001-8000-000000000001',
     'opp.confidence.high_threshold',
     '60.0',
     '[P4] Score >= threshold → HIGH confidence. Lowered from 65 (better coverage).'),

    ('01932a00-3000-7001-8000-000000000002',
     'opp.confidence.medium_threshold',
     '30.0',
     '[P4] Score >= threshold → MEDIUM confidence. Unchanged.'),

-- Evidence count gates (min signals required to unlock HIGH/MEDIUM confidence)
    ('01932a00-3000-7001-8000-100000000001',
     'opp.confidence.min_signals_high',
     '4',
     '[P4] Minimum distinct positive signals required to award HIGH confidence.'),

    ('01932a00-3000-7001-8000-100000000002',
     'opp.confidence.min_signals_medium',
     '2',
     '[P4] Minimum distinct positive signals required to award MEDIUM confidence.'),

-- ── Priority Thresholds (unchanged values, documented for P4) ────────────────
    ('01932a00-4000-7001-8000-000000000001',
     'opp.priority.high_threshold',
     '60.0',
     '[P4] Score >= threshold → HIGH priority. Unchanged.'),

    ('01932a00-4000-7001-8000-000000000002',
     'opp.priority.medium_threshold',
     '28.0',
     '[P4] Score >= threshold → MEDIUM priority. Slightly lowered from 30.'),

-- ── Value Multipliers (recalibrated for P4) ───────────────────────────────────
    ('01932a00-5000-7001-8000-000000000001',
     'opp.value.high_confidence_multiplier',
     '1.0',
     '[P4] HIGH confidence → full base price (unchanged).'),

    ('01932a00-5000-7001-8000-000000000002',
     'opp.value.medium_confidence_multiplier',
     '0.65',
     '[P4] MEDIUM confidence → 65% of base price. Reduced from 0.7.'),

    ('01932a00-5000-7001-8000-000000000003',
     'opp.value.low_confidence_multiplier',
     '0.35',
     '[P4] LOW confidence → 35% of base price. Reduced from 0.4.'),

-- ── Review Thresholds (configurable breakpoints) ──────────────────────────────
    ('01932a00-6000-7001-8000-000000000001',
     'opp.review.high_threshold',
     '100',
     '[P4] Review count >= threshold → REVIEW_HIGH signal.'),

    ('01932a00-6000-7001-8000-000000000002',
     'opp.review.mid_threshold',
     '10',
     '[P4] Review count >= threshold (and < high) → REVIEW_MID signal.'),

-- ── Rating Thresholds (configurable breakpoints) ──────────────────────────────
    ('01932a00-7000-7001-8000-000000000001',
     'opp.rating.high_threshold',
     '4.2',
     '[P4] Rating >= threshold → RATING_HIGH signal.'),

    ('01932a00-7000-7001-8000-000000000002',
     'opp.rating.mid_threshold',
     '3.5',
     '[P4] Rating >= threshold (and < high) → RATING_MID signal.'),

    ('01932a00-7000-7001-8000-000000000003',
     'opp.rating.low_threshold',
     '3.0',
     '[P4] Rating >= threshold (and < mid) → RATING_LOW signal.'),

-- ── Additional Service Category Mappings (P4 additions) ──────────────────────
    ('01932a00-1000-7001-8000-000000000007',
     'opp.category_map.Chemicals',
     '["Website Design & Development","SEO & Digital Marketing","CRM & Lead Management"]',
     '[P4] Service recommendations for Chemicals industry'),

    ('01932a00-1000-7001-8000-000000000008',
     'opp.category_map.Services',
     '["Website Design & Development","Google Business Profile Setup","WhatsApp Business Automation"]',
     '[P4] Service recommendations for Services category'),

    ('01932a00-1000-7001-8000-000000000009',
     'opp.category_map.Healthcare',
     '["Website Design & Development","Google Business Profile Setup","Social Media Management"]',
     '[P4] Service recommendations for Healthcare category'),

    ('01932a00-1000-7001-8000-000000000010',
     'opp.category_map.Education',
     '["Website Design & Development","SEO & Digital Marketing","Social Media Management"]',
     '[P4] Service recommendations for Education category');
