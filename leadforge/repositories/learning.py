"""Learning Task Queue Repository (LF-LRN-001).

Provides persistence and task management for Learning Engine orchestration:
enqueueing, claiming, completing, failing/retrying, and cleaning up tasks.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from leadforge.database import get_db_connection, uuidv7
from leadforge.repositories.base import RepositoryException


class SQLiteLearningTaskRepository:
    """Repository implementation for managing learning_tasks queue."""

    def enqueue_task(
        self,
        source_entity: str,
        entity_id: str,
        learning_type: str,
        priority: int = 50,
        payload: Optional[Dict[str, Any]] = None,
        scheduled_at: Optional[str] = None,
        max_retries: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """Enqueues a new learning task. Idempotent (ignores duplicate active tasks)."""
        conn = get_db_connection()
        try:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            task_id = uuidv7()
            sched_str = scheduled_at or now_str
            payload_str = json.dumps(payload or {})

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO learning_tasks (
                    id, source_entity, entity_id, learning_type, priority, status,
                    retry_count, max_retries, created_at, scheduled_at, payload_json
                )
                VALUES (?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    source_entity,
                    entity_id,
                    learning_type,
                    priority,
                    max_retries,
                    now_str,
                    sched_str,
                    payload_str,
                ),
            )
            conn.commit()

            if cursor.rowcount == 0:
                # Task already exists (duplicate IGNORE)
                return self.get_task_by_source(source_entity, entity_id, learning_type, conn=conn)

            return self.get_task(task_id, conn=conn)
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to enqueue learning task: {str(e)}")
        finally:
            conn.close()

    def get_task(self, task_id: str, conn: Any = None) -> Optional[Dict[str, Any]]:
        local_conn = conn or get_db_connection()
        try:
            cursor = local_conn.cursor()
            cursor.execute(
                """
                SELECT id, source_entity, entity_id, learning_type, priority, status,
                       retry_count, max_retries, created_at, scheduled_at, last_attempt_at,
                       failure_reason, payload_json
                FROM learning_tasks WHERE id = ?
                """,
                (task_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(row)
        finally:
            if not conn:
                local_conn.close()

    def get_task_by_source(
        self, source_entity: str, entity_id: str, learning_type: str, conn: Any = None
    ) -> Optional[Dict[str, Any]]:
        local_conn = conn or get_db_connection()
        try:
            cursor = local_conn.cursor()
            cursor.execute(
                """
                SELECT id, source_entity, entity_id, learning_type, priority, status,
                       retry_count, max_retries, created_at, scheduled_at, last_attempt_at,
                       failure_reason, payload_json
                FROM learning_tasks
                WHERE source_entity = ? AND entity_id = ? AND learning_type = ?
                """,
                (source_entity, entity_id, learning_type),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(row)
        finally:
            if not conn:
                local_conn.close()

    def claim_batch(self, batch_size: int = 10) -> List[Dict[str, Any]]:
        """Claims a batch of PENDING tasks for processing, updating status to PROCESSING."""
        conn = get_db_connection()
        try:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id FROM learning_tasks
                WHERE status = 'PENDING' AND scheduled_at <= ?
                ORDER BY priority DESC, scheduled_at ASC
                LIMIT ?
                """,
                (now_str, batch_size),
            )
            rows = cursor.fetchall()
            if not rows:
                return []

            task_ids = [r["id"] for r in rows]
            placeholders = ",".join(["?"] * len(task_ids))

            cursor.execute(
                f"""
                UPDATE learning_tasks
                SET status = 'PROCESSING', last_attempt_at = ?
                WHERE id IN ({placeholders})
                """,
                [now_str] + task_ids,
            )
            conn.commit()

            cursor.execute(
                f"""
                SELECT id, source_entity, entity_id, learning_type, priority, status,
                       retry_count, max_retries, created_at, scheduled_at, last_attempt_at,
                       failure_reason, payload_json
                FROM learning_tasks WHERE id IN ({placeholders})
                """,
                task_ids,
            )
            return [self._row_to_dict(r) for r in cursor.fetchall()]
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to claim learning tasks batch: {str(e)}")
        finally:
            conn.close()

    def complete_task(self, task_id: str) -> bool:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE learning_tasks SET status = 'COMPLETED' WHERE id = ?",
                (task_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to complete task: {str(e)}")
        finally:
            conn.close()

    def fail_task(self, task_id: str, failure_reason: str) -> Dict[str, Any]:
        """Increments retry count and sets status to FAILED if max retries exceeded, or back to PENDING."""
        conn = get_db_connection()
        try:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT retry_count, max_retries FROM learning_tasks WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise RepositoryException(f"Task '{task_id}' not found.")

            retry_count = row["retry_count"] + 1
            max_retries = row["max_retries"]

            new_status = "FAILED" if retry_count >= max_retries else "PENDING"

            cursor.execute(
                """
                UPDATE learning_tasks
                SET retry_count = ?, status = ?, failure_reason = ?, last_attempt_at = ?
                WHERE id = ?
                """,
                (retry_count, new_status, failure_reason, now_str, task_id),
            )
            conn.commit()
            res = self.get_task(task_id, conn=conn)
            if not res:
                raise RepositoryException(f"Failed to retrieve updated task '{task_id}'.")
            return res
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to fail task: {str(e)}")
        finally:
            conn.close()

    def cleanup_completed(self, days_old: int = 30) -> int:
        """Deletes COMPLETED or CANCELLED tasks older than specified days."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM learning_tasks
                WHERE status IN ('COMPLETED', 'CANCELLED')
                  AND datetime(created_at) <= datetime('now', '-' || ? || ' days')
                """,
                (days_old,),
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            raise RepositoryException(f"Failed to cleanup completed tasks: {str(e)}")
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "source_entity": row["source_entity"],
            "entity_id": row["entity_id"],
            "learning_type": row["learning_type"],
            "priority": row["priority"],
            "status": row["status"],
            "retry_count": row["retry_count"],
            "max_retries": row["max_retries"],
            "created_at": row["created_at"],
            "scheduled_at": row["scheduled_at"],
            "last_attempt_at": row["last_attempt_at"],
            "failure_reason": row["failure_reason"],
            "payload": json.loads(row["payload_json"] or "{}"),
        }
