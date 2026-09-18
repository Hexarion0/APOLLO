import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("apollo.memory")

class SQLiteMemoryStore:
    """Persistent SQLite memory store for APOLLO memories and conversation history."""

    def __init__(self, db_path: Path = Path("data/apollo.db")):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    task_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    cron_expr TEXT,
                    interval_seconds INTEGER,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        logger.info(f"Initialized SQLite Memory Store at {self.db_path}")

    def store_memory(self, key: str, value: str, category: str = "general") -> None:
        """Store or update a key-value memory entry."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (key, value, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (key, value, category, now, now),
            )
            conn.commit()
        logger.info(f"Stored memory key='{key}' category='{category}'")

    def get_memory(self, key: str) -> Optional[str]:
        """Retrieve a memory value by key."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM memories WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def search_memories(self, query: str = "") -> List[Dict[str, Any]]:
        """Search memories matching query."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if query:
                cursor.execute(
                    "SELECT key, value, category, updated_at FROM memories WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC",
                    (f"%{query}%", f"%{query}%"),
                )
            else:
                cursor.execute("SELECT key, value, category, updated_at FROM memories ORDER BY updated_at DESC LIMIT 50")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def add_chat_message(self, channel: str, sender_id: str, role: str, content: str) -> None:
        """Log conversation history message."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversation_history (channel, sender_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (channel, str(sender_id), role, content, now),
            )
            conn.commit()

    def get_recent_chat_history(self, channel: str, sender_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent conversation history for context building."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT role, content, timestamp FROM conversation_history
                WHERE channel = ? AND sender_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (channel, str(sender_id), limit),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in reversed(rows)]

    def save_scheduled_task(
        self,
        task_id: str,
        name: str,
        prompt: str,
        cron_expr: Optional[str] = None,
        interval_seconds: Optional[int] = None,
        enabled: bool = True,
    ) -> None:
        """Persist or update a scheduled task in the database."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scheduled_tasks (task_id, name, prompt, cron_expr, interval_seconds, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    name = excluded.name,
                    prompt = excluded.prompt,
                    cron_expr = excluded.cron_expr,
                    interval_seconds = excluded.interval_seconds,
                    enabled = excluded.enabled
                """,
                (task_id, name, prompt, cron_expr, interval_seconds, 1 if enabled else 0, now),
            )
            conn.commit()

    def remove_scheduled_task(self, task_id: str) -> bool:
        """Remove a persisted scheduled task by task_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM scheduled_tasks WHERE task_id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_scheduled_tasks(self) -> List[Dict[str, Any]]:
        """Retrieve all persisted scheduled tasks."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT task_id, name, prompt, cron_expr, interval_seconds, enabled FROM scheduled_tasks")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
