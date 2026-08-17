"""Business Context Builder for Communication Engine."""

from typing import Dict, Any
from leadforge.database import get_db_connection
from leadforge.repositories.base import RepositoryException
from leadforge.utils import get_logger

logger = get_logger()


class BusinessContextBuilder:
    """Aggregates and sanitizes business details, digital presence, and website audit text."""

    def build_context(self, business_id: str) -> Dict[str, Any]:
        """Queries SQLite and compiles a context dict for LLM copywriting.

        Args:
            business_id: UUID string of the business.

        Returns:
            Dict containing name, city, rating, review_count, website_domain,
            cms, ssl_valid, audit_issues, and contact_email.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # 1. Fetch business details & address
            cursor.execute(
                """
                SELECT b.id, b.name, b.display_phone, b.contact_email, b.rating, b.review_count, b.website_domain,
                       a.city, a.area, a.address_line
                FROM businesses b
                LEFT JOIN addresses a ON a.business_id = b.id
                WHERE b.id = ?
                LIMIT 1
            """,
                (business_id,),
            )
            biz_row = cursor.fetchone()
            if not biz_row:
                raise RepositoryException(f"Business '{business_id}' not found.")

            # 2. Fetch digital presence & audit details
            cursor.execute(
                """
                SELECT dp.platform as cms, dp.ssl_valid, wa.issues_json
                FROM digital_presences dp
                LEFT JOIN website_audits wa ON wa.digital_presence_id = dp.id
                WHERE dp.business_id = ?
                ORDER BY wa.created_at DESC LIMIT 1
            """,
                (business_id,),
            )
            audit_row = cursor.fetchone()

            audit_issues = ""
            cms = ""
            ssl_valid = True

            if audit_row:
                cms = audit_row["cms"] or ""
                ssl_valid = bool(audit_row["ssl_valid"])
                if audit_row["issues_json"]:
                    audit_issues = audit_row["issues_json"]

            return {
                "business_id": biz_row["id"],
                "name": biz_row["name"],
                "city": biz_row["city"] or "Unknown",
                "area": biz_row["area"] or "",
                "phone": biz_row["display_phone"] or "",
                "contact_email": biz_row["contact_email"] or "",
                "rating": biz_row["rating"] or 0.0,
                "review_count": biz_row["review_count"] or 0,
                "website_domain": biz_row["website_domain"] or "",
                "cms": cms,
                "ssl_valid": ssl_valid,
                "audit_issues": audit_issues,
            }
        except Exception as e:
            logger.error(f"[BusinessContextBuilder] Failed to build context for {business_id}: {e}")
            raise
        finally:
            conn.close()
