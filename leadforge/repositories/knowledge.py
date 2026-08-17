"""Repository for Relational Knowledge Graph (LF-INT-001).

Provides normalized relational storage and retrieval for organizational knowledge:
Industry Profiles, Pain Patterns, Objection Patterns, Offer Patterns, Reply Patterns,
Case Studies, Business Insights, Knowledge Items, and Mapping tables.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import RepositoryException


class SQLiteKnowledgeRepository:
    """Repository implementation for managing Relational Knowledge Graph entities."""

    # ── Industry Profiles ──────────────────────────────────────────────────
    def create_industry_profile(
        self, name: str, code: str, description: str = "", avg_contract_value: float = 0.0
    ) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            profile_id = uuidv7()
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO industry_profiles (id, name, code, description, avg_contract_value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (profile_id, name, code, description, avg_contract_value, now_str, now_str),
            )
            conn.commit()
            res = self.get_industry_profile(profile_id, conn=conn)
            if not res:
                raise RepositoryException("Failed to retrieve created industry profile.")
            return res
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to create industry profile: {str(e)}")
        finally:
            conn.close()

    def get_industry_profile(self, profile_id: str, conn: Any = None) -> Optional[Dict[str, Any]]:
        local_conn = conn or get_db_connection()
        try:
            cursor = local_conn.cursor()
            cursor.execute(
                "SELECT id, name, code, description, avg_contract_value, created_at, updated_at FROM industry_profiles WHERE id = ?",
                (profile_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "name": row["name"],
                "code": row["code"],
                "description": row["description"],
                "avg_contract_value": row["avg_contract_value"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            if not conn:
                local_conn.close()

    def get_industry_profile_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, code, description, avg_contract_value, created_at, updated_at FROM industry_profiles WHERE code = ?",
                (code,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "name": row["name"],
                "code": row["code"],
                "description": row["description"],
                "avg_contract_value": row["avg_contract_value"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    # ── Pain Patterns ──────────────────────────────────────────────────────
    def create_pain_pattern(
        self, industry_profile_id: str, title: str, description: str = "", severity: str = "MEDIUM"
    ) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            pain_id = uuidv7()
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO pain_patterns (id, industry_profile_id, title, description, severity, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pain_id, industry_profile_id, title, description, severity, now_str),
            )
            conn.commit()
            return {
                "id": pain_id,
                "industry_profile_id": industry_profile_id,
                "title": title,
                "description": description,
                "severity": severity,
                "created_at": now_str,
            }
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to create pain pattern: {str(e)}")
        finally:
            conn.close()

    def get_pain_patterns_by_industry(self, industry_profile_id: str) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, industry_profile_id, title, description, severity, created_at FROM pain_patterns WHERE industry_profile_id = ?",
                (industry_profile_id,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "industry_profile_id": row["industry_profile_id"],
                    "title": row["title"],
                    "description": row["description"],
                    "severity": row["severity"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    # ── Offer Patterns ─────────────────────────────────────────────────────
    def create_offer_pattern(
        self, industry_profile_id: str, service_name: str, value_proposition: str, typical_price: float = 0.0
    ) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            offer_id = uuidv7()
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO offer_patterns (id, industry_profile_id, service_name, value_proposition, typical_price, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (offer_id, industry_profile_id, service_name, value_proposition, typical_price, now_str),
            )
            conn.commit()
            return {
                "id": offer_id,
                "industry_profile_id": industry_profile_id,
                "service_name": service_name,
                "value_proposition": value_proposition,
                "typical_price": typical_price,
                "created_at": now_str,
            }
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to create offer pattern: {str(e)}")
        finally:
            conn.close()

    # ── Offer-Pain Mapping ────────────────────────────────────────────────
    def map_offer_to_pain(
        self, offer_pattern_id: str, pain_pattern_id: str, relevance_score: float = 1.0
    ) -> bool:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO offer_pain_mappings (offer_pattern_id, pain_pattern_id, relevance_score)
                VALUES (?, ?, ?)
                """,
                (offer_pattern_id, pain_pattern_id, relevance_score),
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to map offer to pain: {str(e)}")
        finally:
            conn.close()

    # ── Knowledge Items (Key-Value Document Persistence) ─────────────────
    def set_knowledge_item(self, topic: str, key_name: str, value: Any) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            value_json = json.dumps(value)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM knowledge_items WHERE key_name = ?", (key_name,))
            row = cursor.fetchone()

            if row:
                item_id = row["id"]
                cursor.execute(
                    "UPDATE knowledge_items SET topic = ?, value_json = ?, updated_at = ? WHERE id = ?",
                    (topic, value_json, now_str, item_id),
                )
            else:
                item_id = uuidv7()
                cursor.execute(
                    """
                    INSERT INTO knowledge_items (id, topic, key_name, value_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (item_id, topic, key_name, value_json, now_str, now_str),
                )
            conn.commit()
            return {"id": item_id, "topic": topic, "key_name": key_name, "value": value}
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to set knowledge item: {str(e)}")
        finally:
            conn.close()

    def get_knowledge_item(self, key_name: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, topic, key_name, value_json, created_at, updated_at FROM knowledge_items WHERE key_name = ?", (key_name,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "topic": row["topic"],
                "key_name": row["key_name"],
                "value": json.loads(row["value_json"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    # ── Knowledge Versioning Engine (LF-INT-002) ──────────────────────────

    def create_knowledge_item_version(
        self,
        key_name: str,
        topic: str,
        value: Any,
        created_by: str = "FOUNDER",
        status: str = "DRAFT",
        change_reason: str = "",
        confidence_score: float = 1.0,
        evidence_reference: str = "",
    ) -> Dict[str, Any]:
        """Creates a new immutable version of a knowledge item."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, version_number FROM knowledge_item_versions WHERE key_name = ? ORDER BY version_number DESC LIMIT 1",
                (key_name,),
            )
            latest = cursor.fetchone()

            if latest:
                previous_version_id = latest["id"]
                version_number = latest["version_number"] + 1
            else:
                previous_version_id = None
                version_number = 1

            version_id = uuidv7()
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            value_json = json.dumps(value)

            cursor.execute(
                """
                INSERT INTO knowledge_item_versions (
                    id, key_name, version_number, previous_version_id, topic, value_json,
                    created_at, created_by, status, change_reason, confidence_score, evidence_reference
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    key_name,
                    version_number,
                    previous_version_id,
                    topic,
                    value_json,
                    now_str,
                    created_by,
                    status,
                    change_reason,
                    confidence_score,
                    evidence_reference,
                ),
            )
            conn.commit()
            return {
                "id": version_id,
                "key_name": key_name,
                "version_number": version_number,
                "previous_version_id": previous_version_id,
                "topic": topic,
                "value": value,
                "created_at": now_str,
                "created_by": created_by,
                "status": status,
                "change_reason": change_reason,
                "confidence_score": confidence_score,
                "evidence_reference": evidence_reference,
            }
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to create knowledge item version: {str(e)}")
        finally:
            conn.close()

    def activate_knowledge_item_version(self, version_id: str) -> Dict[str, Any]:
        """Activates a specific version, deprecating any currently active version for that key_name."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, key_name, status FROM knowledge_item_versions WHERE id = ?",
                (version_id,),
            )
            target = cursor.fetchone()
            if not target:
                raise RepositoryException(f"Knowledge item version '{version_id}' not found.")

            key_name = target["key_name"]

            # Deprecate existing ACTIVE version for this key_name
            cursor.execute(
                "UPDATE knowledge_item_versions SET status = 'DEPRECATED' WHERE key_name = ? AND status = 'ACTIVE'",
                (key_name,),
            )

            # Set target version status to ACTIVE
            cursor.execute(
                "UPDATE knowledge_item_versions SET status = 'ACTIVE' WHERE id = ?",
                (version_id,),
            )
            conn.commit()
            res = self.get_knowledge_item_version_by_id(version_id, conn=conn)
            if not res:
                raise RepositoryException("Failed to retrieve activated version.")
            return res
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to activate knowledge item version: {str(e)}")
        finally:
            conn.close()

    def get_active_knowledge_item(self, key_name: str) -> Optional[Dict[str, Any]]:
        """Queries the single ACTIVE version for a given key_name."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, key_name, version_number, previous_version_id, topic, value_json,
                       created_at, created_by, status, change_reason, confidence_score, evidence_reference
                FROM knowledge_item_versions
                WHERE key_name = ? AND status = 'ACTIVE'
                """,
                (key_name,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "key_name": row["key_name"],
                "version_number": row["version_number"],
                "previous_version_id": row["previous_version_id"],
                "topic": row["topic"],
                "value": json.loads(row["value_json"]),
                "created_at": row["created_at"],
                "created_by": row["created_by"],
                "status": row["status"],
                "change_reason": row["change_reason"],
                "confidence_score": row["confidence_score"],
                "evidence_reference": row["evidence_reference"],
            }
        finally:
            conn.close()

    def get_knowledge_item_history(self, key_name: str) -> List[Dict[str, Any]]:
        """Retrieves full audit history of all versions for key_name, ordered by version_number DESC."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, key_name, version_number, previous_version_id, topic, value_json,
                       created_at, created_by, status, change_reason, confidence_score, evidence_reference
                FROM knowledge_item_versions
                WHERE key_name = ?
                ORDER BY version_number DESC
                """,
                (key_name,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "key_name": row["key_name"],
                    "version_number": row["version_number"],
                    "previous_version_id": row["previous_version_id"],
                    "topic": row["topic"],
                    "value": json.loads(row["value_json"]),
                    "created_at": row["created_at"],
                    "created_by": row["created_by"],
                    "status": row["status"],
                    "change_reason": row["change_reason"],
                    "confidence_score": row["confidence_score"],
                    "evidence_reference": row["evidence_reference"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def get_knowledge_item_version_by_id(self, version_id: str, conn: Any = None) -> Optional[Dict[str, Any]]:
        local_conn = conn or get_db_connection()
        try:
            cursor = local_conn.cursor()
            cursor.execute(
                """
                SELECT id, key_name, version_number, previous_version_id, topic, value_json,
                       created_at, created_by, status, change_reason, confidence_score, evidence_reference
                FROM knowledge_item_versions
                WHERE id = ?
                """,
                (version_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "key_name": row["key_name"],
                "version_number": row["version_number"],
                "previous_version_id": row["previous_version_id"],
                "topic": row["topic"],
                "value": json.loads(row["value_json"]),
                "created_at": row["created_at"],
                "created_by": row["created_by"],
                "status": row["status"],
                "change_reason": row["change_reason"],
                "confidence_score": row["confidence_score"],
                "evidence_reference": row["evidence_reference"],
            }
        finally:
            if not conn:
                local_conn.close()

