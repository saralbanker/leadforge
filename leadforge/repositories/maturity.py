"""Digital Maturity Repository — persists assessments to digital_maturities table."""

from typing import Any, Dict, Optional

from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import RepositoryException


class SQLiteDigitalMaturityRepository:
    """Upserts and retrieves digital maturity records.

    One record per business, overwritten on each scrape so the maturity
    always reflects the latest data.
    """

    def upsert(
        self,
        business_id: str,
        score: float,
        grade: str,
        details_json: str = "",
    ) -> None:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM digital_maturities WHERE business_id = ? LIMIT 1",
                (business_id,),
            )
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    """
                    UPDATE digital_maturities
                       SET maturity_score = ?,
                           grade         = ?,
                           details_json  = ?,
                           audited_at    = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                           updated_at    = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                     WHERE business_id = ?
                    """,
                    (score, grade, details_json, business_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO digital_maturities
                        (id, business_id, maturity_score, grade, details_json, audited_at)
                    VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                    (uuidv7(), business_id, score, grade, details_json),
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise RepositoryException(
                f"Failed to upsert digital maturity for '{business_id}': {exc}"
            )
        finally:
            conn.close()

    def get_for_business(self, business_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT maturity_score, grade, details_json, audited_at
                  FROM digital_maturities WHERE business_id = ? LIMIT 1
                """,
                (business_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "maturity_score": row["maturity_score"],
                "grade": row["grade"],
                "details_json": row["details_json"],
                "audited_at": row["audited_at"],
            }
        except Exception as exc:
            raise RepositoryException(
                f"Failed to get digital maturity for '{business_id}': {exc}"
            )
        finally:
            conn.close()
