from typing import Optional
from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import SettingsRepositoryInterface, RepositoryException

class SQLiteSettingsRepository(SettingsRepositoryInterface):
    def get(self, key: str) -> Optional[str]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            raise RepositoryException(f"Failed to query settings key '{key}': {str(e)}")
        finally:
            conn.close()

    def set(self, key: str, value: str, description: Optional[str] = None):
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            # Ensure we update existing settings or insert a new one with UUIDv7
            cursor.execute("SELECT id FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()

            if row:
                setting_id = row[0]
                cursor.execute(
                    "UPDATE settings SET value = ?, description = COALESCE(?, description) WHERE id = ?",
                    (value, description, setting_id)
                )
            else:
                setting_id = uuidv7()
                cursor.execute(
                    "INSERT INTO settings (id, key, value, description) VALUES (?, ?, ?, ?)",
                    (setting_id, key, value, description)
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to set settings key '{key}' to '{value}': {str(e)}")
        finally:
            conn.close()
