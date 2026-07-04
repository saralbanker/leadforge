from typing import List, Dict, Any, Optional
import time
from datetime import datetime, timezone
from leadforge.config import OUTPUT_DIR
from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import SearchHistoryRepositoryInterface, RepositoryException

class SQLiteSearchHistoryRepository(SearchHistoryRepositoryInterface):
    def create(self, city: str, category: str, results_count: int, status: str, search_query: Optional[str] = None) -> str:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            search_id = uuidv7()
            if not search_query:
                search_query = f"{category} in {city}"

            cursor.execute("""
                INSERT INTO search_history (id, city, category, search_query, results_count, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                search_id,
                city,
                category,
                search_query,
                results_count,
                status,
                datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%fZ')
            ))
            conn.commit()
            return search_id
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to log search history for '{category}' in '{city}': {str(e)}")
        finally:
            conn.close()

    def list_all(self) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT city, category, results_count, status, created_at
                FROM search_history
                ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()

            runs = []
            for row in rows:
                city = row["city"]
                category = row["category"]

                # Format safety names matching main.py naming
                safe_city = "".join([c if c.isalnum() else "_" for c in city])
                safe_category = "".join([c if c.isalnum() else "_" for c in category])
                filename = f"{safe_city}_{safe_category}.xlsx"

                # Check actual file size on disk for Excel downloads
                filepath = OUTPUT_DIR / filename
                size_bytes = 0
                if filepath.exists():
                    size_bytes = filepath.stat().st_size
                else:
                    # Fallback approximation for UI presentation
                    size_bytes = row["results_count"] * 1024

                # Parse created_at ISO 8601 string to epoch timestamp
                try:
                    iso_str = row["created_at"]
                    # Clean Z for fromisoformat compatibility in older python
                    if iso_str.endswith("Z"):
                        iso_str = iso_str[:-1] + "+00:00"
                    dt = datetime.fromisoformat(iso_str)
                    created_at = dt.timestamp()
                except Exception:
                    created_at = time.time()

                runs.append({
                    "filename": filename,
                    "size_bytes": size_bytes,
                    "created_at": created_at,
                    "city": city,
                    "category": category,
                    "status": row["status"]
                })
            return runs
        except Exception as e:
            raise RepositoryException(f"Failed to list search history: {str(e)}")
        finally:
            conn.close()
