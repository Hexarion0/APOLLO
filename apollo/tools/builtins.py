import asyncio
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from apollo.tools.base import BaseTool
from apollo.memory.store import SQLiteMemoryStore

class GetSystemInfoTool(BaseTool):
    name = "get_system_info"
    description = "Get information about the system environment, OS, Python version, and system host."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        return {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": sys.version,
            "hostname": platform.node(),
            "current_dir": str(Path.cwd()),
        }

class GetCurrentTimeTool(BaseTool):
    name = "get_current_time"
    description = "Get the current UTC time and local time ISO string."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        return {
            "utc_iso": now_utc.isoformat(),
            "local_iso": datetime.now().astimezone().isoformat(),
            "timestamp": now_utc.timestamp(),
        }

class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read text content from a specified file path."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read",
            },
            "max_lines": {
                "type": "integer",
                "description": "Optional maximum number of lines to read",
                "default": 500,
            },
        },
        "required": ["file_path"],
    }

    async def execute(self, file_path: str, max_lines: int = 500, **kwargs: Any) -> Dict[str, Any]:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        lines = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                if idx >= max_lines:
                    break
                lines.append(line)

        return {
            "file_path": str(path),
            "lines_read": len(lines),
            "content": "".join(lines),
        }

class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write text content to a file path. (Requires confirmation tier)."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Destination file path",
            },
            "content": {
                "type": "string",
                "description": "Text content to write",
            },
            "append": {
                "type": "boolean",
                "description": "If true, appends content to file instead of overwriting",
                "default": False,
            },
        },
        "required": ["file_path", "content"],
    }

    async def execute(self, file_path: str, content: str, append: bool = False, **kwargs: Any) -> Dict[str, Any]:
        path = Path(file_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)

        return {
            "file_path": str(path),
            "bytes_written": len(content.encode("utf-8")),
            "mode": mode,
            "status": "success",
        }

class ExecuteCommandTool(BaseTool):
    name = "execute_command"
    description = "Execute a shell command on the host system. (Requires confirmation tier)."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Maximum execution timeout in seconds",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    async def execute(self, command: str, timeout_seconds: int = 30, **kwargs: Any) -> Dict[str, Any]:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout_seconds)
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command execution timed out after {timeout_seconds}s")

        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")

        max_len = 4000
        def _truncate(text: str) -> str:
            if len(text) > max_len:
                omitted = len(text) - max_len
                return text[:2000] + f"\n\n[... {omitted} characters omitted ...]\n\n" + text[-2000:]
            return text

        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": _truncate(stdout_str),
            "stderr": _truncate(stderr_str),
        }

class StoreMemoryTool(BaseTool):
    name = "store_memory"
    description = "Store a key-value memory entry for APOLLO's long-term persistent memory."
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Identifier key for the memory item",
            },
            "value": {
                "type": "string",
                "description": "Value or information string to remember",
            },
            "category": {
                "type": "string",
                "description": "Optional category tag (e.g., 'preference', 'fact', 'project')",
                "default": "general",
            },
        },
        "required": ["key", "value"],
    }

    def __init__(self, memory_store: SQLiteMemoryStore):
        self.memory_store = memory_store

    async def execute(self, key: str, value: str, category: str = "general", **kwargs: Any) -> Dict[str, Any]:
        self.memory_store.store_memory(key=key, value=value, category=category)
        return {
            "status": "success",
            "key": key,
            "category": category,
        }

class RecallMemoryTool(BaseTool):
    name = "recall_memory"
    description = "Search or retrieve persistent memories stored in APOLLO's memory database."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search keyword or key to look up (leave blank to get recent memories)",
                "default": "",
            },
        },
        "required": [],
    }

    def __init__(self, memory_store: SQLiteMemoryStore):
        self.memory_store = memory_store

    async def execute(self, query: str = "", **kwargs: Any) -> Dict[str, Any]:
        results = self.memory_store.search_memories(query=query)
        return {
            "query": query,
            "count": len(results),
            "results": results,
        }

class GitStatusTool(BaseTool):
    name = "git_status"
    description = "Check git repository working tree status (staged, unstaged, and untracked files)."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        proc = await asyncio.create_subprocess_shell(
            "git status",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return {
            "exit_code": proc.returncode,
            "output": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        }

class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "View git diff summary or detailed changes."
    parameters = {
        "type": "object",
        "properties": {
            "staged": {
                "type": "boolean",
                "description": "If true, view staged changes (--staged)",
                "default": False,
            },
        },
        "required": [],
    }

    async def execute(self, staged: bool = False, **kwargs: Any) -> Dict[str, Any]:
        cmd = "git diff --staged" if staged else "git diff"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return {
            "command": cmd,
            "exit_code": proc.returncode,
            "diff_output": stdout_bytes.decode("utf-8", errors="replace")[:3000],
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        }

class ImportMemoryTool(BaseTool):
    name = "import_memory"
    description = "Import an external OpenClaw memory file (.json, .md, or .db) into APOLLO's persistent SQLite memory database."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the OpenClaw memory file (.json, .md, or .db)",
            },
        },
        "required": ["file_path"],
    }

    def __init__(self, memory_store: SQLiteMemoryStore):
        self.memory_store = memory_store

    async def execute(self, file_path: str, **kwargs: Any) -> Dict[str, Any]:
        from apollo.memory.importer import import_openclaw_memory
        path = Path(file_path).expanduser().resolve()
        return import_openclaw_memory(path, self.memory_store)

class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "List files and subdirectories in a directory with file sizes and directory indicators."
    parameters = {
        "type": "object",
        "properties": {
            "dir_path": {
                "type": "string",
                "description": "Path to directory (defaults to current directory '.')",
                "default": ".",
            },
            "max_items": {
                "type": "integer",
                "description": "Maximum number of directory items to return",
                "default": 100,
            },
        },
        "required": [],
    }

    async def execute(self, dir_path: str = ".", max_items: int = 100, **kwargs: Any) -> Dict[str, Any]:
        path = Path(dir_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {dir_path}")
        if not path.is_dir():
            raise ValueError(f"Path is not a directory: {dir_path}")

        items = []
        for entry in sorted(path.iterdir()):
            if len(items) >= max_items:
                break
            try:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size_bytes": stat.st_size if entry.is_file() else None,
                })
            except Exception:
                items.append({"name": entry.name, "is_dir": entry.is_dir(), "size_bytes": None})

        return {
            "directory": str(path),
            "item_count": len(items),
            "items": items,
        }

class ScheduleTaskTool(BaseTool):
    name = "schedule_task"
    description = "Schedule an autonomous recurring or delayed background task. (Requires confirmation tier)."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Human-readable label for the scheduled task",
            },
            "prompt": {
                "type": "string",
                "description": "Prompt instructions for what APOLLO should execute when the task triggers",
            },
            "interval_seconds": {
                "type": "integer",
                "description": "Interval frequency in seconds (e.g. 3600 for every hour, 86400 for daily)",
            },
            "cron_expr": {
                "type": "string",
                "description": "Standard 5-part cron expression (e.g. '0 9 * * *' for 9 AM daily) — alternative to interval_seconds",
            },
            "task_id": {
                "type": "string",
                "description": "Optional unique ID for the task (auto-generated if omitted)",
            },
        },
        "required": ["name", "prompt"],
    }

    def __init__(self, scheduler: Any):
        self.scheduler = scheduler

    async def execute(
        self,
        name: str,
        prompt: str,
        interval_seconds: Optional[int] = None,
        cron_expr: Optional[str] = None,
        task_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        import uuid
        tid = task_id or f"task_{uuid.uuid4().hex[:8]}"
        task = self.scheduler.add_task(
            task_id=tid,
            name=name,
            prompt=prompt,
            cron_expr=cron_expr,
            interval_seconds=interval_seconds,
        )
        return {
            "status": "scheduled",
            "task_id": task.task_id,
            "name": task.name,
            "prompt": task.prompt,
            "interval_seconds": task.interval_seconds,
            "cron_expr": task.cron_expr,
        }

class ListTasksTool(BaseTool):
    name = "list_tasks"
    description = "List all active background scheduled autonomous tasks."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, scheduler: Any):
        self.scheduler = scheduler

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        tasks = self.scheduler.list_tasks()
        return {
            "count": len(tasks),
            "tasks": [
                {
                    "task_id": t.task_id,
                    "name": t.name,
                    "prompt": t.prompt,
                    "cron_expr": t.cron_expr,
                    "interval_seconds": t.interval_seconds,
                    "enabled": t.enabled,
                }
                for t in tasks
            ],
        }

class CancelTaskTool(BaseTool):
    name = "cancel_task"
    description = "Cancel or remove an active background scheduled task by its task_id. (Requires confirmation tier)."
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "ID of the task to cancel",
            },
        },
        "required": ["task_id"],
    }

    def __init__(self, scheduler: Any):
        self.scheduler = scheduler

    async def execute(self, task_id: str, **kwargs: Any) -> Dict[str, Any]:
        removed = self.scheduler.remove_task(task_id)
        if not removed:
            return {"status": "not_found", "task_id": task_id}
        return {"status": "cancelled", "task_id": task_id}
