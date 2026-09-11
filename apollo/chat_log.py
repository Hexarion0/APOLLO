"""
apollo/chat_log.py — Persistent flat-file conversation logger.

Writes every user message, assistant response, tool call, and tool result
to a human-readable log file (default: chat.log).  APOLLO can read this file
with the read_file tool to recover context after a crash or restart.

Log format:
    ════════════════ [SESSION START] 2026-09-03 18:19:10 UTC ════════════════

    [18:19:15] USER
    what's the weather in Bangkok?

    [18:19:16] TOOL → get_weather
    {"location": "Bangkok"}

    [18:19:17] TOOL RESULT ← get_weather
    {"location": "Bangkok, Thailand", "temperature": "32°C", ...}

    [18:19:18] APOLLO
    It's 32°C in Bangkok right now — pretty warm!

    ════════════════ [SESSION END] 2026-09-03 18:30:00 UTC ════════════════
"""

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class ChatFileLogger:
    """Thread-safe append-only flat-file conversation logger with automatic size rotation."""

    def __init__(self, log_path: Path, max_bytes: int = 5 * 1024 * 1024, backup_count: int = 2) -> None:
        self.log_path = Path(log_path)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._write_session_marker("SESSION START")

    def _rotate_if_needed(self) -> None:
        if not self.log_path.exists():
            return
        try:
            if self.log_path.stat().st_size >= self.max_bytes:
                for i in range(self.backup_count - 1, 0, -1):
                    src = self.log_path.with_name(f"{self.log_path.name}.{i}")
                    dst = self.log_path.with_name(f"{self.log_path.name}.{i+1}")
                    if src.exists():
                        src.replace(dst)
                first_backup = self.log_path.with_name(f"{self.log_path.name}.1")
                self.log_path.replace(first_backup)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_user(self, message: str, sender_id: Optional[str] = None) -> None:
        label = f"USER ({sender_id})" if sender_id else "USER"
        self._append(label, message)

    def log_assistant(self, message: str) -> None:
        self._append("APOLLO", message)

    def log_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        import json
        body = json.dumps(arguments, ensure_ascii=False, indent=2)
        self._append(f"TOOL → {tool_name}", body)

    def log_tool_result(self, tool_name: str, result: Any, status: str = "OK") -> None:
        import json
        try:
            body = json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            body = str(result)
        self._append(f"TOOL RESULT ← {tool_name} [{status}]", body)

    def log_session_end(self) -> None:
        self._write_session_marker("SESSION END")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%H:%M:%S")

    def _append(self, label: str, body: str) -> None:
        ts = self._timestamp()
        lines = [f"\n[{ts}] {label}", body.strip(), ""]
        entry = "\n".join(lines) + "\n"
        with self._lock:
            self._rotate_if_needed()
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(entry)

    def _write_session_marker(self, kind: str) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        marker = f"\n{'═' * 20} [{kind}] {now} {'═' * 20}\n"
        with self._lock:
            self._rotate_if_needed()
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(marker)
