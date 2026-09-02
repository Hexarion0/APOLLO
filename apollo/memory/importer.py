import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from apollo.memory.store import SQLiteMemoryStore

logger = logging.getLogger("apollo.memory.importer")

def import_openclaw_memory(file_path: Path, memory_store: SQLiteMemoryStore) -> Dict[str, Any]:
    """Import OpenClaw memory file (.json, .md, .db) into APOLLO's SQLite memory store."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Memory file not found: {file_path}")

    ext = path.suffix.lower()
    imported_count = 0
    details: List[str] = []

    if ext == ".json":
        imported_count, details = _import_json_memory(path, memory_store)
    elif ext in (".md", ".txt"):
        imported_count, details = _import_markdown_memory(path, memory_store)
    elif ext in (".db", ".sqlite", ".sqlite3"):
        imported_count, details = _import_sqlite_memory(path, memory_store)
    else:
        # Fallback to text parsing
        imported_count, details = _import_markdown_memory(path, memory_store)

    logger.info(f"Imported {imported_count} memory entries from '{path}'")
    return {
        "status": "success",
        "imported_count": imported_count,
        "file_path": str(path),
        "details": details[:10],
    }

def _import_json_memory(path: Path, memory_store: SQLiteMemoryStore) -> tuple[int, List[str]]:
    raw_text = path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    count = 0
    details = []

    if isinstance(data, dict):
        # Format: {"key1": "val1", "key2": "val2"} or {"memories": [...]}
        if "memories" in data and isinstance(data["memories"], list):
            data = data["memories"]
        else:
            for k, v in data.items():
                val_str = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                memory_store.store_memory(key=str(k), value=val_str, category="openclaw_import")
                count += 1
                details.append(f"{k}: {val_str[:40]}")
            return count, details

    if isinstance(data, list):
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                key = item.get("key") or item.get("topic") or item.get("id") or item.get("title") or f"openclaw_mem_{idx+1}"
                val = item.get("value") or item.get("content") or item.get("text") or item.get("memory") or str(item)
                cat = item.get("category") or item.get("type") or "openclaw_import"
                val_str = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val)
                memory_store.store_memory(key=str(key), value=val_str, category=str(cat))
                count += 1
                details.append(f"{key}: {val_str[:40]}")
            elif isinstance(item, str):
                key = f"openclaw_mem_{idx+1}"
                memory_store.store_memory(key=key, value=item, category="openclaw_import")
                count += 1
                details.append(f"{key}: {item[:40]}")

    return count, details

def _import_markdown_memory(path: Path, memory_store: SQLiteMemoryStore) -> tuple[int, List[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    count = 0
    details = []
    current_category = "openclaw_import"
    item_idx = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            current_category = stripped.lstrip("#").strip().lower().replace(" ", "_") or "openclaw_import"
            continue
        if stripped.startswith(("-", "*", "•")):
            text = stripped.lstrip("-*•").strip()
            item_idx += 1
            if ":" in text:
                parts = text.split(":", 1)
                key = parts[0].strip().lower().replace(" ", "_")
                val = parts[1].strip()
            else:
                key = f"{current_category}_{item_idx}"
                val = text
            memory_store.store_memory(key=key, value=val, category=current_category)
            count += 1
            details.append(f"{key}: {val[:40]}")

    return count, details

def _import_sqlite_memory(path: Path, memory_store: SQLiteMemoryStore) -> tuple[int, List[str]]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]

    count = 0
    details = []

    for table in tables:
        try:
            cursor.execute(f"PRAGMA table_info('{table}');")
            columns = [col[1] for col in cursor.fetchall()]

            cursor.execute(f"SELECT * FROM '{table}' LIMIT 500;")
            rows = cursor.fetchall()

            for idx, row in enumerate(rows):
                row_dict = dict(row)
                key = row_dict.get("key") or row_dict.get("id") or row_dict.get("topic") or f"{table}_{idx+1}"
                val = row_dict.get("value") or row_dict.get("content") or row_dict.get("text") or str(row_dict)
                cat = row_dict.get("category") or table
                val_str = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val)
                memory_store.store_memory(key=str(key), value=val_str, category=str(cat))
                count += 1
                details.append(f"{key}: {val_str[:40]}")
        except Exception as e:
            logger.warning(f"Could not parse SQLite table '{table}' from '{path}': {e}")

    conn.close()
    return count, details
