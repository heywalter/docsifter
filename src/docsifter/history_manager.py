"""SQLite-backed history of review tasks and logs."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Tuple

from .runtime import get_runtime_path, isoformat_utc, utcnow


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TIMESTAMP_FIELDS = ("start_time", "end_time", "created_at", "updated_at", "timestamp")


def _with_explicit_offset(record: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp stored naive-UTC timestamps with their offset before they leave.

    Clients parse an offset-free timestamp as local time, so review history
    rendered hours away from the moment it was recorded.
    """
    for field in TIMESTAMP_FIELDS:
        if field in record:
            record[field] = isoformat_utc(record[field])
    return record


class HistoryManager:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or get_runtime_path("history.db")
        self._init_database()

    def _init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS task_history (
                    id TEXT PRIMARY KEY,
                    directory TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration INTEGER,
                    total_files INTEGER DEFAULT 0,
                    total_changes INTEGER DEFAULT 0,
                    valid_changes INTEGER DEFAULT 0,
                    total_chars INTEGER DEFAULT 0,
                    defect_rate REAL DEFAULT 0.0,
                    debug_mode BOOLEAN DEFAULT FALSE,
                    auto_generate BOOLEAN DEFAULT TRUE,
                    report_path TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS task_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task_history (id)
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS task_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    current_file TEXT,
                    message TEXT,
                    FOREIGN KEY (task_id) REFERENCES task_history (id)
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS task_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    changes_data TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task_history (id)
                )
            """
            )

            conn.commit()

    def create_task(
        self, directory: str, debug_mode: bool = False, auto_generate: bool = True
    ) -> str:
        task_id = str(uuid.uuid4())
        now = utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO task_history (
                    id, directory, status, start_time, debug_mode,
                    auto_generate, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    task_id,
                    directory,
                    TaskStatus.PENDING.value,
                    now,
                    debug_mode,
                    auto_generate,
                    now,
                    now,
                ),
            )
            conn.commit()

        return task_id

    def cancel_task(self, task_id: str) -> bool:
        now = utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT start_time FROM task_history
                WHERE id = ? AND status IN (?, ?)
                """,
                (task_id, TaskStatus.PENDING.value, TaskStatus.RUNNING.value),
            )
            row = cursor.fetchone()
            if not row:
                return False

            start_time = datetime.fromisoformat(row[0])
            duration = int((utcnow() - start_time).total_seconds())
            cursor.execute(
                """
                UPDATE task_history
                SET status = ?, end_time = ?, duration = ?, error_message = ?, updated_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    TaskStatus.CANCELLED.value,
                    now,
                    duration,
                    "Cancelled by user",
                    now,
                    task_id,
                    TaskStatus.PENDING.value,
                    TaskStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            cursor.execute(
                """
                INSERT INTO task_logs (task_id, timestamp, level, message)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, now, "INFO", "Task cancelled by user"),
            )
            conn.commit()
            return True

    def recover_interrupted_tasks(self) -> List[str]:
        """Mark tasks left active by a previous process as failed."""
        now = utcnow().isoformat()
        message = "Task interrupted by service restart"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, start_time FROM task_history WHERE status IN (?, ?)",
                (TaskStatus.PENDING.value, TaskStatus.RUNNING.value),
            )
            rows = cursor.fetchall()

            for task_id, start_time_value in rows:
                start_time = datetime.fromisoformat(start_time_value)
                duration = int((utcnow() - start_time).total_seconds())
                cursor.execute(
                    """
                    UPDATE task_history
                    SET status = ?, end_time = ?, duration = ?, error_message = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.FAILED.value, now, duration, message, now, task_id),
                )
                cursor.execute(
                    """
                    INSERT INTO task_logs (task_id, timestamp, level, message)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_id, now, "ERROR", message),
                )

            conn.commit()

        return [row[0] for row in rows]

    def is_task_cancelled(self, task_id: str) -> bool:
        if not task_id:
            return False

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM task_history WHERE id = ?", (task_id,))
            result = cursor.fetchone()
            return result and result[0] == TaskStatus.CANCELLED.value

    def update_task_status(self, task_id: str, status: TaskStatus, error_message: str = None):
        now = utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                cursor.execute("SELECT start_time FROM task_history WHERE id = ?", (task_id,))
                result = cursor.fetchone()
                if result:
                    start_time = datetime.fromisoformat(result[0])
                    duration = int((utcnow() - start_time).total_seconds())

                    cursor.execute(
                        """
                        UPDATE task_history
                        SET status = ?, end_time = ?, duration = ?,
                            error_message = ?, updated_at = ?
                        WHERE id = ?
                    """,
                        (status.value, now, duration, error_message, now, task_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE task_history
                        SET status = ?, error_message = ?, updated_at = ?
                        WHERE id = ?
                    """,
                        (status.value, error_message, now, task_id),
                    )
            else:
                cursor.execute(
                    """
                    UPDATE task_history
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                """,
                    (status.value, now, task_id),
                )

            conn.commit()

    def update_task_stats(self, task_id: str, stats: Dict[str, Any]):
        now = utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE task_history
                SET total_files = ?, total_changes = ?, valid_changes = ?,
                    total_chars = ?, defect_rate = ?, updated_at = ?
                WHERE id = ?
            """,
                (
                    stats.get("total_files", 0),
                    stats.get("total_changes", 0),
                    stats.get("valid_changes", 0),
                    stats.get("total_chars", 0),
                    stats.get("defect_rate_per_thousand", 0.0),
                    now,
                    task_id,
                ),
            )
            conn.commit()

    def set_report_path(self, task_id: str, report_path: str):
        now = utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE task_history
                SET report_path = ?, updated_at = ?
                WHERE id = ?
            """,
                (report_path, now, task_id),
            )
            conn.commit()

    def get_latest_report_path(self) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT report_path
                FROM task_history
                WHERE status = ? AND report_path IS NOT NULL
                ORDER BY end_time DESC, created_at DESC
                LIMIT 1
                """,
                (TaskStatus.COMPLETED.value,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def add_log(self, task_id: str, level: str, message: str):
        now = utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO task_logs (task_id, timestamp, level, message)
                VALUES (?, ?, ?, ?)
            """,
                (task_id, now, level, message),
            )
            conn.commit()

    def update_progress(
        self, task_id: str, progress: int, current_file: str = None, message: str = None
    ):
        now = utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO task_progress (task_id, timestamp, progress, current_file, message)
                VALUES (?, ?, ?, ?, ?)
            """,
                (task_id, now, progress, current_file, message),
            )
            conn.commit()

    def save_task_results(self, task_id: str, results: List[Dict[str, Any]]):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM task_results WHERE task_id = ?", (task_id,))
            for result in results:
                cursor.execute(
                    """
                    INSERT INTO task_results (task_id, file_path, changes_data)
                    VALUES (?, ?, ?)
                """,
                    (
                        task_id,
                        result["file_path"],
                        json.dumps(result["changes"], ensure_ascii=False),
                    ),
                )
            conn.commit()

    def get_task_history(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM task_history
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """,
                (limit, offset),
            )

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            tasks = []
            for row in rows:
                task = _with_explicit_offset(dict(zip(columns, row, strict=True)))
                if "id" in task:
                    task["task_id"] = task["id"]
                tasks.append(task)

            return tasks

    def get_task_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM task_history")
            return int(cursor.fetchone()[0])

    def get_task_detail(self, task_id: str) -> Dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_history WHERE id = ?", (task_id,))

            row = cursor.fetchone()
            if not row:
                return None

            columns = [desc[0] for desc in cursor.description]
            task = _with_explicit_offset(dict(zip(columns, row, strict=True)))

            cursor.execute(
                """
                SELECT timestamp, level, message FROM task_logs
                WHERE task_id = ? ORDER BY timestamp
            """,
                (task_id,),
            )
            task["logs"] = [
                {"timestamp": isoformat_utc(row[0]), "level": row[1], "message": row[2]}
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT timestamp, progress, current_file, message FROM task_progress
                WHERE task_id = ? ORDER BY timestamp
            """,
                (task_id,),
            )
            progress_rows = cursor.fetchall()
            task["progress_history"] = [
                {
                    "timestamp": isoformat_utc(row[0]),
                    "progress": row[1],
                    "current_file": row[2],
                    "message": row[3],
                }
                for row in progress_rows
            ]

            task["progress"] = progress_rows[-1][1] if progress_rows else 0

            cursor.execute(
                """
                SELECT file_path, changes_data FROM task_results
                WHERE task_id = ?
            """,
                (task_id,),
            )
            task["results"] = [
                {"file_path": row[0], "changes": json.loads(row[1])} for row in cursor.fetchall()
            ]

            return task

    def get_task_logs(self, task_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT timestamp, level, message FROM task_logs
                WHERE task_id = ? ORDER BY timestamp
            """,
                (task_id,),
            )
            return [
                {"timestamp": isoformat_utc(row[0]), "level": row[1], "message": row[2]}
                for row in cursor.fetchall()
            ]

    def get_task_progress(self, task_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT timestamp, progress, current_file, message FROM task_progress
                WHERE task_id = ? ORDER BY timestamp
            """,
                (task_id,),
            )
            return [
                {
                    "timestamp": isoformat_utc(row[0]),
                    "progress": row[1],
                    "current_file": row[2],
                    "message": row[3],
                }
                for row in cursor.fetchall()
            ]

    def get_running_tasks(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT h.*, p.progress, p.current_file, p.message as progress_message
                FROM task_history h
                LEFT JOIN (
                    SELECT task_id, progress, current_file, message,
                           ROW_NUMBER() OVER (PARTITION BY task_id ORDER BY timestamp DESC) as rn
                    FROM task_progress
                ) p ON h.id = p.task_id AND p.rn = 1
                WHERE h.status IN (?, ?)
                ORDER BY h.created_at DESC
            """,
                (TaskStatus.PENDING.value, TaskStatus.RUNNING.value),
            )

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            tasks = []
            for row in rows:
                task = _with_explicit_offset(dict(zip(columns, row, strict=True)))
                task["task_id"] = task["id"]
                tasks.append(task)

            return tasks

    def get_recent_stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_tasks,
                    SUM(total_files) as total_files,
                    SUM(valid_changes) as total_changes,
                    AVG(defect_rate) as avg_defect_rate,
                    MAX(end_time) as last_completed
                FROM task_history
                WHERE status = ? AND end_time IS NOT NULL
                AND datetime(end_time) >= datetime('now', '-7 days')
            """,
                (TaskStatus.COMPLETED.value,),
            )

            result = cursor.fetchone()

            if result and result[0] > 0:
                return {
                    "total_files": result[1] or 0,
                    "total_changes": result[2] or 0,
                    "avg_defect_rate": round(result[3] or 0, 2),
                    "last_completed": result[4],
                }
            else:
                return {
                    "total_files": 0,
                    "total_changes": 0,
                    "avg_defect_rate": 0,
                    "last_completed": None,
                }

    def get_total_stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_tasks,
                    SUM(total_files) as total_files,
                    SUM(valid_changes) as total_changes,
                    AVG(defect_rate) as avg_defect_rate,
                    MAX(end_time) as last_completed
                FROM task_history
                WHERE status = ? AND end_time IS NOT NULL
            """,
                (TaskStatus.COMPLETED.value,),
            )

            result = cursor.fetchone()

            if result and result[0] > 0:
                return {
                    "total_files": result[1] or 0,
                    "valid_changes": result[2] or 0,
                    "defect_rate_per_thousand": round(result[3] or 0, 1),
                    "total_tasks": result[0],
                    "last_completed": result[4],
                }
            else:
                return {
                    "total_files": 0,
                    "valid_changes": 0,
                    "defect_rate_per_thousand": 0,
                    "total_tasks": 0,
                    "last_completed": None,
                }

    def purge_tasks_older_than(self, days: int) -> Tuple[int, List[str]]:
        """Delete tasks created before the cutoff; return the count and their reports.

        Timestamps are stored as ISO strings, so a lexical comparison is also a
        chronological one.
        """
        cutoff = (utcnow() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, report_path FROM task_history WHERE created_at < ?", (cutoff,)
            )
            rows = cursor.fetchall()
            if not rows:
                return 0, []

            task_ids = [row[0] for row in rows]
            report_paths = [row[1] for row in rows if row[1]]
            placeholders = ",".join("?" for _ in task_ids)
            for table in ("task_results", "task_progress", "task_logs"):
                cursor.execute(
                    f"DELETE FROM {table} WHERE task_id IN ({placeholders})",  # noqa: S608
                    task_ids,
                )
            cursor.execute(
                f"DELETE FROM task_history WHERE id IN ({placeholders})",  # noqa: S608
                task_ids,
            )
            conn.commit()

        return len(task_ids), report_paths

    def all_report_paths(self) -> List[str]:
        """Report paths still referenced by a surviving task."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT report_path FROM task_history WHERE report_path IS NOT NULL")
            return [row[0] for row in cursor.fetchall() if row[0]]

    def delete_task(self, task_id: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM task_results WHERE task_id = ?", (task_id,))
            cursor.execute("DELETE FROM task_progress WHERE task_id = ?", (task_id,))
            cursor.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
            cursor.execute("DELETE FROM task_history WHERE id = ?", (task_id,))
            conn.commit()
