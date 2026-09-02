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

        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
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
