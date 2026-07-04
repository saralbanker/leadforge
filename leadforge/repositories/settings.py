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

    def get_int(self, key: str, default: int) -> int:
        """Gets value as integer, falling back to default on conversion error or missing key."""
        val = self.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except ValueError:
            return default

    def get_float(self, key: str, default: float) -> float:
        """Gets value as float, falling back to default on conversion error or missing key."""
        val = self.get(key)
        if val is None:
            return default
        try:
            return float(val)
        except ValueError:
            return default

    def get_str(self, key: str, default: str) -> str:
        """Gets value as string, falling back to default if missing key."""
        val = self.get(key)
        return val if val is not None else default
