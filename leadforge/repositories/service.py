"""Provides read access to the services table.
All SQL stays here — never in the engine.
"""

from leadforge.database import get_db_connection
from leadforge.repositories.base import RepositoryException


class SQLiteServiceRepository:
    """Read-only access to the services catalogue."""

    def get_base_price(self, service_name: str) -> float:
        """Returns the base_price for a named service, or 0.0 if not found."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT base_price FROM services WHERE name = ? AND deleted_at IS NULL LIMIT 1",
                (service_name,),
            )
            row = cursor.fetchone()
            return float(row["base_price"]) if row else 0.0
        except Exception as exc:
            raise RepositoryException(
                f"Failed to fetch base price for '{service_name}': {exc}"
            )
        finally:
            conn.close()
