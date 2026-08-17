"""SQLite Repository for Email Enrichment Layer persistence and caching."""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import json
from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import RepositoryException
from leadforge.enrichment.base import EnrichmentResult
from leadforge.utils import get_logger

logger = get_logger()


class SQLiteEnrichmentRepository:
    """Repository handling persistence for email enrichment attempts and caching."""

    def initialize_schema(self) -> None:
        """Ensures enrichment tables exist in SQLite."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS enrichment_cache (
                    cache_key TEXT PRIMARY KEY,
                    provider_name TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                );
            """
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to initialize enrichment schema: {e}")
        finally:
            conn.close()

    def save_enrichment_result(
        self,
        business_id: str,
        domain: str,
        top_candidate: Optional[EnrichmentResult],
        all_candidates: List[EnrichmentResult],
    ) -> None:
        """Persists candidate attempts and updates businesses.contact_email."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            conn.execute("BEGIN TRANSACTION;")
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # 1. Update contact_email in businesses table if a top candidate was found
            if top_candidate and top_candidate.email:
                cursor.execute(
                    "UPDATE businesses SET contact_email = ?, updated_at = ? WHERE id = ?",
                    (top_candidate.email, now_str, business_id),
                )

            # 2. Insert attempt records into email_discovery_attempts
            if all_candidates:
                for cand in all_candidates:
                    cursor.execute(
                        """
                        INSERT INTO email_discovery_attempts (
                            id, business_id, domain, discovered_email, discovery_status, last_attempt_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (
                            uuidv7(),
                            business_id,
                            domain or cand.source_provider,
                            cand.email,
                            "SUCCESS",
                            now_str,
                        ),
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO email_discovery_attempts (
                        id, business_id, domain, discovered_email, discovery_status, last_attempt_at
                    )
                    VALUES (?, ?, ?, NULL, 'NO_EMAIL_FOUND', ?)
                """,
                    (uuidv7(), business_id, domain or "UNKNOWN", now_str),
                )

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to save enrichment result: {e}")
        finally:
            conn.close()

    def get_cached_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        self.initialize_schema()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT response_json FROM enrichment_cache WHERE cache_key = ?",
                (cache_key,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return None
        except Exception:
            return None
        finally:
            conn.close()

    def set_cached_response(
        self, cache_key: str, provider_name: str, payload: Dict[str, Any]
    ) -> None:
        self.initialize_schema()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO enrichment_cache (cache_key, provider_name, response_json, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (cache_key, provider_name, json.dumps(payload)),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"Failed to cache enrichment response for {cache_key}: {e}")
        finally:
            conn.close()
