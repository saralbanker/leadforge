-- Repair malformed ISO 8601 timestamps in search_history produced by the
-- incorrect Python strftime format "%Y-%m-%dT%H:%M:%fZ" (missing :%S.).
--
-- Malformed shape: YYYY-MM-DDTHH:MM:ffffffZ  (24 chars, microseconds where
-- seconds+dot+microseconds should be).
-- Correct shape:   YYYY-MM-DDTHH:MM:SS.ffffffZ  (27 chars).
--
-- Repair: insert ':00.' between the minutes and the 6-digit microseconds so
-- the timestamp represents seconds=00 with the original microsecond value.
-- The actual seconds cannot be recovered, but the repaired value is a valid,
-- sortable, UI-renderable ISO 8601 string.

UPDATE search_history
SET started_at = substr(started_at, 1, 16) || ':00.' || substr(started_at, 18, 6) || 'Z'
WHERE length(started_at) = 24
  AND substr(started_at, 17, 1) = ':'
  AND substr(started_at, 24, 1) = 'Z';

UPDATE search_history
SET created_at = substr(created_at, 1, 16) || ':00.' || substr(created_at, 18, 6) || 'Z'
WHERE length(created_at) = 24
  AND substr(created_at, 17, 1) = ':'
  AND substr(created_at, 24, 1) = 'Z';

UPDATE search_history
SET finished_at = substr(finished_at, 1, 16) || ':00.' || substr(finished_at, 18, 6) || 'Z'
WHERE finished_at IS NOT NULL
  AND length(finished_at) = 24
  AND substr(finished_at, 17, 1) = ':'
  AND substr(finished_at, 24, 1) = 'Z';
