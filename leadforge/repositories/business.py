"""Business Repository — read-only queries for the businesses dashboard and export."""

import json
from typing import Any, Dict, List, Optional

from leadforge.database import get_db_connection
from leadforge.repositories.base import RepositoryException


class SQLiteBusinessRepository:
    """Read-only queries for the business browsing and export workflows.

    All SQL lives here.  No business logic.
    """

    _VALID_SORT = {"score", "name", "rating", "review_count", "maturity_score"}
    _VALID_DIR = {"asc", "desc"}

    # ── Public API ─────────────────────────────────────────────────────────────

    def list(
        self,
        search: Optional[str] = None,
        maturity_grade: Optional[str] = None,
        min_score: Optional[float] = None,
        sort_by: str = "score",
        sort_dir: str = "desc",
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Return businesses with intelligence summary, suitable for the UI list view."""
        sort_col = sort_by if sort_by in self._VALID_SORT else "score"
        sort_direction = (
            sort_dir.lower() if sort_dir.lower() in self._VALID_DIR else "desc"
        )

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            params: list = []
            where_clauses = ["b.deleted_at IS NULL"]

            if search:
                where_clauses.append(
                    "(LOWER(b.name) LIKE ? OR LOWER(bt.name) LIKE ? OR LOWER(a.area) LIKE ?)"
                )
                term = f"%{search.lower()}%"
                params += [term, term, term]

            if maturity_grade:
                where_clauses.append("dm.grade = ?")
                params.append(maturity_grade.upper())

            if min_score is not None:
                where_clauses.append("COALESCE(best_opp.score, 0) >= ?")
                params.append(float(min_score))

            where_sql = " AND ".join(where_clauses)

            # Map sort_col to actual SQL expression
            sort_expr = {
                "score": "COALESCE(best_opp.score, 0)",
                "name": "LOWER(b.name)",
                "rating": "COALESCE(b.rating, 0)",
                "review_count": "COALESCE(b.review_count, 0)",
                "maturity_score": "COALESCE(dm.maturity_score, 0)",
            }[sort_col]

            cursor.execute(
                f"""
                SELECT
                    b.id,
                    b.name,
                    COALESCE(bt.name, '') AS category,
                    COALESCE(b.display_phone, '') AS phone,
                    COALESCE(dp.website_url, '') AS website,
                    COALESCE(a.area, '') AS area,
                    b.rating,
                    b.review_count,
                    b.business_status,
                    b.first_discovered_at,
                    b.last_scraped_at,
                    COALESCE(dm.grade, '') AS maturity_grade,
                    COALESCE(dm.maturity_score, 0.0) AS maturity_score,
                    COALESCE(best_opp.score, 0.0) AS top_score,
                    COALESCE(best_opp.title, '') AS top_opportunity,
                    COALESCE(disc.discovery_count, 1) AS discovery_count
                FROM businesses b
                LEFT JOIN business_types bt ON b.business_type_id = bt.id
                LEFT JOIN addresses a ON b.id = a.business_id AND a.is_primary = 1
                LEFT JOIN digital_presences dp ON b.id = dp.business_id
                LEFT JOIN digital_maturities dm ON b.id = dm.business_id
                LEFT JOIN (
                    SELECT business_id, MAX(score) AS score, title
                      FROM opportunities WHERE deleted_at IS NULL
                     GROUP BY business_id
                ) best_opp ON b.id = best_opp.business_id
                LEFT JOIN (
                    SELECT business_id, COUNT(DISTINCT campaign_name) AS discovery_count
                      FROM leads
                     GROUP BY business_id
                ) disc ON b.id = disc.business_id
                WHERE {where_sql}
                ORDER BY {sort_expr} {sort_direction.upper()}
                LIMIT ?
                """,
                params + [int(limit)],
            )
            return [self._row_to_biz(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise RepositoryException(f"Failed to list businesses: {exc}")
        finally:
            conn.close()

    def get_detail(self, business_id: str) -> Optional[Dict[str, Any]]:
        """Return full business detail: metadata + maturity + opportunities + signals."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # ── Business metadata ──────────────────────────────────────────────
            cursor.execute(
                """
                SELECT
                    b.id, b.name, b.display_phone AS phone, b.contact_email,
                    b.website_domain, b.rating, b.review_count, b.business_status,
                    b.opening_hours, b.categories, b.first_discovered_at, b.last_scraped_at,
                    COALESCE(bt.name, '') AS category,
                    COALESCE(dp.website_url, '') AS website,
                    COALESCE(a.address_line, '') AS address,
                    COALESCE(a.area, '') AS area,
                    COALESCE(a.city, '') AS city
                FROM businesses b
                LEFT JOIN business_types bt ON b.business_type_id = bt.id
                LEFT JOIN addresses a ON b.id = a.business_id AND a.is_primary = 1
                LEFT JOIN digital_presences dp ON b.id = dp.business_id
                WHERE b.id = ? AND b.deleted_at IS NULL
                """,
                (business_id,),
            )
            biz_row = cursor.fetchone()
            if not biz_row:
                return None

            detail: Dict[str, Any] = {k: biz_row[k] for k in biz_row.keys()}

            # ── Digital Maturity ───────────────────────────────────────────────
            cursor.execute(
                "SELECT maturity_score, grade, details_json FROM digital_maturities WHERE business_id = ? LIMIT 1",
                (business_id,),
            )
            mat_row = cursor.fetchone()
            if mat_row:
                raw_details = mat_row["details_json"] or "{}"
                try:
                    mat_details = json.loads(raw_details)
                except (json.JSONDecodeError, TypeError):
                    mat_details = {}
                detail["maturity"] = {
                    "grade": mat_row["grade"],
                    "score": mat_row["maturity_score"],
                    **mat_details,
                }
            else:
                detail["maturity"] = None

            # ── Opportunities + Signals ────────────────────────────────────────
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
            opps = []
            for opp_row in cursor.fetchall():
                opp = dict(opp_row)
                cursor.execute(
                    """
                    SELECT rule_name, score_delta, reason
                      FROM opportunity_scoring_logs
                     WHERE opportunity_id = ?
                     ORDER BY rowid ASC
                    """,
                    (opp["id"],),
                )
                opp["signals"] = [dict(r) for r in cursor.fetchall()]
                opps.append(opp)
            detail["opportunities"] = opps

            return detail
        except Exception as exc:
            raise RepositoryException(
                f"Failed to get business detail for '{business_id}': {exc}"
            )
        finally:
            conn.close()

    def list_for_export(
        self,
        mode: str = "all",
        campaign_name: Optional[str] = None,
        min_score: Optional[float] = None,
        search: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Return enriched lead rows for Excel export.

        Modes:
          all           — all businesses
          high_priority — businesses with top_score >= 60
          campaign      — businesses belonging to the given campaign_name
          filtered      — search + min_score combo
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            params: list = []
            where_clauses = ["b.deleted_at IS NULL"]

            if mode == "high_priority":
                where_clauses.append("COALESCE(best_opp.score, 0) >= 60")

            if mode == "campaign" and campaign_name:
                where_clauses.append("l.campaign_name = ?")
                params.append(campaign_name)

            if mode == "filtered":
                if search:
                    where_clauses.append("LOWER(b.name) LIKE ?")
                    params.append(f"%{search.lower()}%")
                if min_score is not None:
                    where_clauses.append("COALESCE(best_opp.score, 0) >= ?")
                    params.append(float(min_score))

            where_sql = " AND ".join(where_clauses)

            join_leads = (
                "LEFT JOIN leads l ON b.id = l.business_id"
                if mode == "campaign"
                else ""
            )

            cursor.execute(
                f"""
                SELECT DISTINCT
                    b.id,
                    b.name,
                    COALESCE(b.display_phone, '') AS phone,
                    COALESCE(dp.website_url, '') AS website,
                    COALESCE(bt.name, '') AS category,
                    COALESCE(a.area, '') AS area,
                    b.rating,
                    b.review_count,
                    COALESCE(dm.grade, '') AS maturity_grade,
                    COALESCE(dm.maturity_score, 0.0) AS maturity_score,
                    COALESCE(best_opp.score, 0.0) AS top_score,
                    COALESCE(best_opp.title, '') AS top_opportunity,
                    COALESCE(all_svcs.service_list, '') AS recommended_services
                FROM businesses b
                LEFT JOIN business_types bt ON b.business_type_id = bt.id
                LEFT JOIN addresses a ON b.id = a.business_id AND a.is_primary = 1
                LEFT JOIN digital_presences dp ON b.id = dp.business_id
                LEFT JOIN digital_maturities dm ON b.id = dm.business_id
                LEFT JOIN (
                    SELECT business_id, MAX(score) AS score, title
                      FROM opportunities WHERE deleted_at IS NULL
                     GROUP BY business_id
                ) best_opp ON b.id = best_opp.business_id
                LEFT JOIN (
                    SELECT business_id, GROUP_CONCAT(title, '; ') AS service_list
                      FROM opportunities WHERE deleted_at IS NULL
                     GROUP BY business_id
                ) all_svcs ON b.id = all_svcs.business_id
                {join_leads}
                WHERE {where_sql}
                ORDER BY COALESCE(best_opp.score, 0) DESC
                LIMIT ?
                """,
                params + [int(limit)],
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                score = row["top_score"] or 0
                results.append(
                    {
                        "name": row["name"],
                        "phone": row["phone"],
                        "website": row["website"],
                        "category": row["category"],
                        "area": row["area"],
                        "rating": row["rating"],
                        "review_count": row["review_count"],
                        "maturity_grade": row["maturity_grade"],
                        "maturity_score": round(row["maturity_score"] or 0, 1),
                        "priority": "High" if score >= 60 else "Medium",
                        "score": round(score, 1),
                        "top_opportunity": row["top_opportunity"],
                        "recommended_services": row["recommended_services"],
                    }
                )
            return results
        except Exception as exc:
            raise RepositoryException(f"Failed to list businesses for export: {exc}")
        finally:
            conn.close()

    # ── Private ────────────────────────────────────────────────────────────────

    def _row_to_biz(self, row) -> Dict[str, Any]:
        score = row["top_score"] or 0.0
        return {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "phone": row["phone"],
            "website": row["website"],
            "area": row["area"],
            "rating": row["rating"],
            "review_count": row["review_count"],
            "business_status": row["business_status"] or "",
            "first_discovered_at": row["first_discovered_at"] or "",
            "last_scraped_at": row["last_scraped_at"] or "",
            "maturity_grade": row["maturity_grade"],
            "maturity_score": round(row["maturity_score"] or 0, 1),
            "top_score": round(score, 1),
            "top_opportunity": row["top_opportunity"],
            "priority": "HIGH" if score >= 60 else ("MEDIUM" if score >= 28 else "LOW"),
            "discovery_count": row["discovery_count"] or 1,
        }
