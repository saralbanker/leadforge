from typing import List, Dict, Any, Optional

from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import OpportunityRepositoryInterface, RepositoryException


class SQLiteOpportunityRepository(OpportunityRepositoryInterface):
    """Persists and queries opportunities and their scoring logs via SQLite.

    All SQL is contained here.  No business logic lives inside this class —
    it is strictly a persistence boundary.
    """

    # ── Duplicate Prevention ──────────────────────────────────────────────────

    def title_exists_for_business(self, business_id: str, title: str) -> bool:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM opportunities
                WHERE business_id = ? AND title = ? AND deleted_at IS NULL
                LIMIT 1
                """,
                (business_id, title),
            )
            return cursor.fetchone() is not None
        except Exception as exc:
            raise RepositoryException(
                f"Failed to check opportunity title existence for business '{business_id}': {exc}"
            )
        finally:
            conn.close()

    # ── Read Operations ───────────────────────────────────────────────────────

    def get_active_for_business(self, business_id: str) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, title, pipeline_stage, score, close_probability,
                       estimated_value, created_at
                FROM opportunities
                WHERE business_id = ? AND deleted_at IS NULL
                ORDER BY score DESC
                """,
                (business_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise RepositoryException(
                f"Failed to fetch opportunities for business '{business_id}': {exc}"
            )
        finally:
            conn.close()

    def get_scoring_logs(self, opportunity_id: str) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT rule_name, score_delta, reason, created_at
                FROM opportunity_scoring_logs
                WHERE opportunity_id = ?
                ORDER BY created_at ASC
                """,
                (opportunity_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise RepositoryException(
                f"Failed to fetch scoring logs for opportunity '{opportunity_id}': {exc}"
            )
        finally:
            conn.close()

    def list_ranked(
        self,
        limit: Optional[int] = None,
        pipeline_stage: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            params: list = []
            where_clauses = ["o.deleted_at IS NULL"]

            if pipeline_stage:
                where_clauses.append("o.pipeline_stage = ?")
                params.append(pipeline_stage)

            where_sql = " AND ".join(where_clauses)
            limit_sql = f"LIMIT {int(limit)}" if limit else ""

            cursor.execute(
                f"""
                SELECT
                    o.id,
                    o.business_id,
                    b.name AS business_name,
                    COALESCE(bt.name, '') AS business_category,
                    o.title,
                    o.pipeline_stage,
                    o.score,
                    o.close_probability,
                    o.estimated_value,
                    o.created_at,
                    COALESCE(dm.grade, '') AS maturity_grade,
                    COALESCE(dm.maturity_score, 0.0) AS maturity_score
                FROM opportunities o
                JOIN businesses b ON o.business_id = b.id
                LEFT JOIN business_types bt ON b.business_type_id = bt.id
                LEFT JOIN digital_maturities dm ON o.business_id = dm.business_id
                WHERE {where_sql}
                ORDER BY o.score DESC, o.close_probability DESC
                {limit_sql}
                """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise RepositoryException(f"Failed to list ranked opportunities: {exc}")
        finally:
            conn.close()

    def get_with_signals(self, opportunity_id: str) -> Optional[Dict[str, Any]]:
        """Return one opportunity with all its scoring-log signals."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    o.id, o.business_id, o.title, o.pipeline_stage,
                    o.score, o.close_probability, o.estimated_value, o.created_at,
                    b.name AS business_name,
                    COALESCE(bt.name, '') AS business_category,
                    COALESCE(dm.grade, '') AS maturity_grade,
                    COALESCE(dm.maturity_score, 0.0) AS maturity_score
                FROM opportunities o
                JOIN businesses b ON o.business_id = b.id
                LEFT JOIN business_types bt ON b.business_type_id = bt.id
                LEFT JOIN digital_maturities dm ON o.business_id = dm.business_id
                WHERE o.id = ? AND o.deleted_at IS NULL
                """,
                (opportunity_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            result = dict(row)
            cursor.execute(
                """
                SELECT rule_name, score_delta, reason
                  FROM opportunity_scoring_logs
                 WHERE opportunity_id = ?
                 ORDER BY rowid ASC
                """,
                (opportunity_id,),
            )
            result["signals"] = [dict(r) for r in cursor.fetchall()]
            return result
        except Exception as exc:
            raise RepositoryException(
                f"Failed to get opportunity with signals '{opportunity_id}': {exc}"
            )
        finally:
            conn.close()

    # ── Write Operations ──────────────────────────────────────────────────────

    def create_with_scoring_logs(
        self,
        business_id: str,
        title: str,
        pipeline_stage: str,
        score: float,
        close_probability: float,
        estimated_value: float,
        scoring_logs: List[Dict[str, Any]],
    ) -> str:
        """Atomically inserts one opportunity row and N scoring-log rows.

        Each element of *scoring_logs* must be a dict with keys:
          - rule_name  (str)
          - score_delta (float)
          - reason     (str)
        """
        conn = get_db_connection()
        try:
            conn.execute("BEGIN TRANSACTION;")
            cursor = conn.cursor()

            opp_id = uuidv7()
            cursor.execute(
                """
                INSERT INTO opportunities
                    (id, business_id, title, pipeline_stage, score,
                     close_probability, estimated_value)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opp_id,
                    business_id,
                    title,
                    pipeline_stage,
                    score,
                    close_probability,
                    estimated_value,
                ),
            )

            for entry in scoring_logs:
                cursor.execute(
                    """
                    INSERT INTO opportunity_scoring_logs
                        (id, opportunity_id, rule_name, score_delta, reason)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uuidv7(),
                        opp_id,
                        entry["rule_name"],
                        entry["score_delta"],
                        entry["reason"],
                    ),
                )

            conn.commit()
            return opp_id
        except Exception as exc:
            conn.rollback()
            raise RepositoryException(
                f"Failed to create opportunity '{title}' for business '{business_id}': {exc}"
            )
        finally:
            conn.close()
