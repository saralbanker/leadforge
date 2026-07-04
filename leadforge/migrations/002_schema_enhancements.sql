-- ============================================================================
-- LeadForge Schema Migration (002_schema_enhancements.sql)
-- Add Rating, Review Count, Status, Hours, Categories, and Run Auditing metrics
-- ============================================================================

-- 1. Alter businesses table to add scraper metadata and discovery lifecycle
ALTER TABLE businesses ADD COLUMN rating REAL;
ALTER TABLE businesses ADD COLUMN review_count INTEGER;
ALTER TABLE businesses ADD COLUMN business_status TEXT;
ALTER TABLE businesses ADD COLUMN opening_hours TEXT;
ALTER TABLE businesses ADD COLUMN categories TEXT;
ALTER TABLE businesses ADD COLUMN last_scraped_at TEXT;
ALTER TABLE businesses ADD COLUMN first_discovered_at TEXT;

-- 2. Alter search_history table to add execution timestamps and counts
ALTER TABLE search_history ADD COLUMN started_at TEXT;
ALTER TABLE search_history ADD COLUMN finished_at TEXT;
ALTER TABLE search_history ADD COLUMN execution_duration REAL;
ALTER TABLE search_history ADD COLUMN limit_requested INTEGER;
ALTER TABLE search_history ADD COLUMN new_businesses INTEGER;
ALTER TABLE search_history ADD COLUMN updated_businesses INTEGER;
ALTER TABLE search_history ADD COLUMN failed_businesses INTEGER;
ALTER TABLE search_history ADD COLUMN duplicate_detections INTEGER;
ALTER TABLE search_history ADD COLUMN scraper_version TEXT;
ALTER TABLE search_history ADD COLUMN scraper_metadata TEXT;

-- 3. Alter leads table to associate discoveries directly with their originating search runs
ALTER TABLE leads ADD COLUMN search_history_id TEXT REFERENCES search_history(id);

-- 4. Insert default operational scraper parameters into settings
INSERT OR IGNORE INTO settings (id, key, value, description) VALUES
('01907de3-bc42-7c89-8d76-5a507db4f991', 'MAX_RETRIES', '3', 'Maximum retries for scraper page loads'),
('01907de3-bc42-7c89-8d76-5a507db4f992', 'BASE_BACKOFF_SECONDS', '2.0', 'Base backoff delay in seconds for exponential retries'),
('01907de3-bc42-7c89-8d76-5a507db4f993', 'THROTTLE_DELAY', '1.0', 'Scraper throttle delay in seconds between business details pages'),
('01907de3-bc42-7c89-8d76-5a507db4f994', 'REQUEST_TIMEOUT', '30', 'Playwright page navigation timeout in seconds'),
('01907de3-bc42-7c89-8d76-5a507db4f995', 'USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'User agent header for Google Maps crawler');
