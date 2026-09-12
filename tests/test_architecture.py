"""
Tests for new architecture features:
  - Log rotation (ChatFileLogger, AuditLogger)
  - Scheduler persistence (SQLite round-trip)
  - Command output truncation (ExecuteCommandTool)
  - Desktop tools schema validation (TakeScreenshotTool, MediaControlTool)
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Log Rotation Tests
# ---------------------------------------------------------------------------

class TestLogRotation:
    """Test log rotation for ChatFileLogger and AuditLogger."""

    def test_chat_logger_rotation_init(self):
        """ChatFileLogger accepts max_bytes and backup_count params."""
        from apollo.chat_log import ChatFileLogger

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "chat.log"
            logger = ChatFileLogger(log_path=log_path, max_bytes=1024, backup_count=1)
            assert logger.max_bytes == 1024
            assert logger.backup_count == 1

    def test_chat_logger_rotation_defaults(self):
        """ChatFileLogger uses sensible defaults when params omitted."""
        from apollo.chat_log import ChatFileLogger

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "chat.log"
            logger = ChatFileLogger(log_path=log_path)
            assert logger.max_bytes == 5 * 1024 * 1024  # 5MB default
            assert logger.backup_count == 2

    def test_audit_logger_rotation_init(self):
        """AuditLogger accepts max_bytes and backup_count params."""
        from apollo.audit import AuditLogger

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "audit.log"
            logger = AuditLogger(log_path=log_path, max_bytes=2048, backup_count=3)
            assert logger.max_bytes == 2048
            assert logger.backup_count == 3

    def test_chat_logger_rotate_creates_backup(self):
        """ChatFileLogger rotates when file exceeds max_bytes."""
        from apollo.chat_log import ChatFileLogger

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "chat.log"
            # Tiny limit to trigger rotation quickly
            logger = ChatFileLogger(log_path=log_path, max_bytes=50, backup_count=1)

            # Write enough data to exceed the limit
            big_content = "X" * 200 + "\n"
            log_path.write_text(big_content)
            logger._rotate_if_needed()

            backup_path = log_path.with_name("chat.log.1")
            assert backup_path.exists(), "Backup file should exist after rotation"


# ---------------------------------------------------------------------------
# Scheduler Persistence Tests
# ---------------------------------------------------------------------------

class TestSchedulerPersistence:
    """Test scheduler task persistence via SQLiteMemoryStore."""

    def _make_store(self, td):
        from apollo.memory.store import SQLiteMemoryStore
        db_path = Path(td) / "test.db"
        return SQLiteMemoryStore(db_path=db_path)

    def test_save_and_retrieve_scheduled_task(self):
        """Tasks saved to DB can be retrieved."""
        with tempfile.TemporaryDirectory() as td:
            store = self._make_store(td)
            store.save_scheduled_task(
                task_id="t1",
                name="Morning check",
                prompt="Good morning",
                cron_expr="0 8 * * *",
            )
            tasks = store.get_all_scheduled_tasks()
            assert len(tasks) == 1
            assert tasks[0]["task_id"] == "t1"
            assert tasks[0]["name"] == "Morning check"
            assert tasks[0]["cron_expr"] == "0 8 * * *"
            assert tasks[0]["interval_seconds"] is None

    def test_save_interval_task(self):
        """Interval-based tasks are stored correctly."""
        with tempfile.TemporaryDirectory() as td:
            store = self._make_store(td)
            store.save_scheduled_task(
                task_id="t2",
                name="Heartbeat",
                prompt="Ping",
                interval_seconds=300,
            )
            tasks = store.get_all_scheduled_tasks()
            assert len(tasks) == 1
            assert tasks[0]["interval_seconds"] == 300
            assert tasks[0]["cron_expr"] is None

    def test_remove_scheduled_task(self):
        """Removed tasks no longer appear in retrieval."""
        with tempfile.TemporaryDirectory() as td:
            store = self._make_store(td)
            store.save_scheduled_task(task_id="t3", name="Temp", prompt="Hi")
            assert len(store.get_all_scheduled_tasks()) == 1
            result = store.remove_scheduled_task("t3")
            assert result is True
            assert len(store.get_all_scheduled_tasks()) == 0

    def test_remove_nonexistent_task(self):
        """Removing a non-existent task returns False."""
        with tempfile.TemporaryDirectory() as td:
            store = self._make_store(td)
            result = store.remove_scheduled_task("doesnt-exist")
            assert result is False

    def test_upsert_scheduled_task(self):
        """Saving same task_id updates rather than duplicates."""
        with tempfile.TemporaryDirectory() as td:
            store = self._make_store(td)
            store.save_scheduled_task(task_id="t4", name="V1", prompt="Old")
            store.save_scheduled_task(task_id="t4", name="V2", prompt="New")
            tasks = store.get_all_scheduled_tasks()
            assert len(tasks) == 1
            assert tasks[0]["name"] == "V2"
            assert tasks[0]["prompt"] == "New"

    def test_scheduler_add_task_calls_persist(self):
        """BackgroundScheduler.add_task calls memory_store.save_scheduled_task when persist=True."""
        from apollo.scheduler.cron import BackgroundScheduler

        mock_store = MagicMock()
        mock_store.save_scheduled_task = MagicMock()
        mock_store.get_all_scheduled_tasks = MagicMock(return_value=[])

        scheduler = BackgroundScheduler(memory_store=mock_store)
        # Don't call start() — AsyncIOScheduler needs a running event loop.
        # Instead, mock the internal scheduler to avoid that.
        scheduler._scheduler = MagicMock()
        scheduler._scheduler.running = True

        scheduler.add_task(
            task_id="persist_test",
            name="Test Task",
            prompt="Do something",
            interval_seconds=60,
            persist=True,
        )

        mock_store.save_scheduled_task.assert_called_once_with(
            task_id="persist_test",
            name="Test Task",
            prompt="Do something",
            cron_expr=None,
            interval_seconds=60,
            enabled=True,
        )

    def test_scheduler_add_task_skips_persist_when_false(self):
        """BackgroundScheduler.add_task does NOT persist when persist=False."""
        from apollo.scheduler.cron import BackgroundScheduler

        mock_store = MagicMock()
        mock_store.save_scheduled_task = MagicMock()

        scheduler = BackgroundScheduler(memory_store=mock_store)
        scheduler._scheduler = MagicMock()
        scheduler._scheduler.running = True

        scheduler.add_task(
            task_id="no_persist",
            name="Ephemeral",
            prompt="Quick",
            interval_seconds=30,
            persist=False,
        )

        mock_store.save_scheduled_task.assert_not_called()

    def test_scheduler_remove_task_calls_persist(self):
        """BackgroundScheduler.remove_task calls memory_store.remove_scheduled_task."""
        from apollo.scheduler.cron import BackgroundScheduler

        mock_store = MagicMock()
        mock_store.remove_scheduled_task = MagicMock()
        mock_store.save_scheduled_task = MagicMock()

        scheduler = BackgroundScheduler(memory_store=mock_store)
        scheduler._scheduler = MagicMock()
        scheduler._scheduler.running = True

        scheduler.add_task(
            task_id="rm_test",
            name="To Remove",
            prompt="Bye",
            interval_seconds=60,
            persist=False,
        )
        scheduler.remove_task("rm_test")

        mock_store.remove_scheduled_task.assert_called_once_with("rm_test")


# ---------------------------------------------------------------------------
# Command Truncation Tests
# ---------------------------------------------------------------------------

class TestCommandTruncation:
    """Test ExecuteCommandTool output truncation."""

    @pytest.mark.asyncio
    async def test_output_truncation_large_output(self):
        """Large command output is truncated with head/tail sandwich."""
        from apollo.tools.builtins import ExecuteCommandTool

        tool = ExecuteCommandTool()
        result = await tool.execute(command="seq 1 10000")
        result_str = str(result)
        # Should be capped — the raw output would be ~50KB but truncation caps at 4000 chars
        assert len(result_str) < 6000, f"Output should be truncated, got {len(result_str)} chars"

    @pytest.mark.asyncio
    async def test_output_no_truncation_small(self):
        """Small output is NOT truncated."""
        from apollo.tools.builtins import ExecuteCommandTool

        tool = ExecuteCommandTool()
        result = await tool.execute(command="echo hello")
        assert "hello" in str(result)
        assert "truncated" not in str(result).lower()


# ---------------------------------------------------------------------------
# Desktop Tools Schema Tests
# ---------------------------------------------------------------------------

class TestDesktopTools:
    """Test desktop tool definitions and schema validity."""

    def test_screenshot_tool_schema(self):
        """TakeScreenshotTool has valid OpenAI function schema."""
        from apollo.tools.desktop import TakeScreenshotTool

        tool = TakeScreenshotTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "take_screenshot"
        params = schema["function"]["parameters"]
        assert "region" in params["properties"]
        assert "output_path" in params["properties"]
        assert params["properties"]["region"]["enum"] == ["fullscreen", "active", "area"]

    def test_media_control_tool_schema(self):
        """MediaControlTool has valid OpenAI function schema."""
        from apollo.tools.desktop import MediaControlTool

        tool = MediaControlTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "media_control"
        params = schema["function"]["parameters"]
        assert "action" in params["properties"]
        assert "value" in params["properties"]
        assert "player" in params["properties"]
        assert "required" in params
        assert "action" in params["required"]

    @pytest.mark.asyncio
    async def test_media_control_unknown_action(self):
        """MediaControlTool returns error for volume-set without value."""
        from apollo.tools.desktop import MediaControlTool

        tool = MediaControlTool()
        result = await tool.execute(action="volume-set")
        assert "error" in result.lower() or "value" in result.lower()

    @pytest.mark.asyncio
    async def test_screenshot_no_binary(self):
        """TakeScreenshotTool gracefully fails when grim/grimblast not found."""
        from apollo.tools.desktop import TakeScreenshotTool

        tool = TakeScreenshotTool()
        with patch.object(tool, "_which", new_callable=AsyncMock, return_value=None):
            result = await tool.execute(region="fullscreen")
            assert any(kw in result.lower() for kw in ("error", "bridge", "unavailable", "not found"))
            assert "grim" in result.lower()

