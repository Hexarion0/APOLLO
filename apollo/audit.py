import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("apollo.audit")

class AuditLogger:
    """Timestamped audit logger for tracking tool invocations and autonomous actions."""

    def __init__(self, log_path: Path = Path("audit.log")):
        self.log_path = log_path
        self._ensure_log_file()

    def _ensure_log_file(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch(mode=0o600)

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
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.info(f"Audit log recorded: tool={tool_name} tier={tier} status={status}")
        except Exception as e:
            logger.error(f"Failed to write to audit log file {self.log_path}: {e}")

        return entry
