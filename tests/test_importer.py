import json
import sqlite3
import pytest
from pathlib import Path
from apollo.memory.store import SQLiteMemoryStore
from apollo.memory.importer import import_openclaw_memory

def test_import_json_memory(tmp_path: Path):
    db_path = tmp_path / "apollo.db"
    store = SQLiteMemoryStore(db_path=db_path)

    json_file = tmp_path / "openclaw_mem.json"
    json_data = [
        {"key": "favorite_food", "value": "Ramen", "category": "preferences"},
        {"key": "city", "value": "Tokyo", "category": "location"},
    ]
    json_file.write_text(json.dumps(json_data), encoding="utf-8")

    res = import_openclaw_memory(json_file, store)
    assert res["status"] == "success"
    assert res["imported_count"] == 2
    assert store.get_memory("favorite_food") == "Ramen"

def test_import_markdown_memory(tmp_path: Path):
    db_path = tmp_path / "apollo.db"
    store = SQLiteMemoryStore(db_path=db_path)

    md_file = tmp_path / "openclaw_mem.md"
    md_content = """# User Preferences
- Editor: VS Code
- Theme: Dark Mode
"""
    md_file.write_text(md_content, encoding="utf-8")

    res = import_openclaw_memory(md_file, store)
    assert res["status"] == "success"
    assert res["imported_count"] == 2
    assert store.get_memory("editor") == "VS Code"

def test_import_sqlite_memory(tmp_path: Path):
    db_path = tmp_path / "apollo.db"
    store = SQLiteMemoryStore(db_path=db_path)

    openclaw_db = tmp_path / "openclaw.db"
    conn = sqlite3.connect(str(openclaw_db))
    cur = conn.cursor()
    cur.execute("CREATE TABLE openclaw_facts (key TEXT PRIMARY KEY, value TEXT, category TEXT)")
    cur.execute("INSERT INTO openclaw_facts VALUES ('hobby', 'Gaming', 'personal')")
    conn.commit()
    conn.close()

    res = import_openclaw_memory(openclaw_db, store)
    assert res["status"] == "success"
    assert res["imported_count"] == 1
    assert store.get_memory("hobby") == "Gaming"
