import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("apollo.audit")

class AuditLogger:
    """Timestamped audit logger for tracking tool invocations and autonomous actions with automatic rotation."""

    def __init__(self, log_path: Path = Path("logs/audit.log"), max_bytes: int = 5 * 1024 * 1024, backup_count: int = 2):
        self.log_path = Path(log_path)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._ensure_log_file()

    def _ensure_log_file(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch(mode=0o600)

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
                self._ensure_log_file()
        except Exception:
            pass

    def log_action(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tier: str,
        status: str,
        reason: Optional[str] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record an audited action entry in structured JSON lines format."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "arguments": arguments,
            "tier": tier,
            "status": status,  # e.g., 'EXECUTED', 'DENIED', 'CONFIRMED', 'FAILED'
            "reason": reason or "",
            "result": str(result) if result is not None else None,
            "error": error or None,
        }

        try:
            self._rotate_if_needed()
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.info(f"Audit log recorded: tool={tool_name} tier={tier} status={status}")
        except Exception as e:
            logger.error(f"Failed to write to audit log file {self.log_path}: {e}")

        return entry
