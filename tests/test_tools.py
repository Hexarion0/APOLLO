from pathlib import Path
import pytest
from apollo.channels.telegram import _chunk_text
from apollo.scheduler.cron import BackgroundScheduler
from apollo.tools.builtins import CancelTaskTool, ListDirectoryTool, ListTasksTool, ScheduleTaskTool

def test_chunk_text_small():
    text = "Short text"
    assert _chunk_text(text, max_chunk_size=100) == ["Short text"]

def test_chunk_text_split_with_code_block():
    text = "Intro\n```python\nline1\nline2\nline3\n```\nOutro"
    chunks = _chunk_text(text, max_chunk_size=25)
    assert len(chunks) > 1
    # Check that code block is closed and reopened across boundary
    assert "```\n" in chunks[0]
    assert "```python\n" in chunks[1]

@pytest.mark.asyncio
async def test_list_directory_tool(tmp_path: Path):
    (tmp_path / "file1.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "subdir").mkdir()

    tool = ListDirectoryTool()
    res = await tool.execute(dir_path=str(tmp_path))
    assert res["item_count"] == 2
    names = [i["name"] for i in res["items"]]
    assert "file1.txt" in names
    assert "subdir" in names

@pytest.mark.asyncio
async def test_scheduler_tools():
    scheduler = BackgroundScheduler()
    sched_tool = ScheduleTaskTool(scheduler=scheduler)
    list_tool = ListTasksTool(scheduler=scheduler)
    cancel_tool = CancelTaskTool(scheduler=scheduler)

    # 1. Schedule a task
    s_res = await sched_tool.execute(
        name="Daily Backup",
        prompt="Backup database",
        interval_seconds=3600,
        task_id="backup_job",
    )
    assert s_res["status"] == "scheduled"
    assert s_res["task_id"] == "backup_job"

    # 2. List tasks
    l_res = await list_tool.execute()
    assert l_res["count"] == 1
    assert l_res["tasks"][0]["task_id"] == "backup_job"

    # 3. Cancel task
    c_res = await cancel_tool.execute(task_id="backup_job")
    assert c_res["status"] == "cancelled"

    # 4. List tasks again
    l_res2 = await list_tool.execute()
    assert l_res2["count"] == 0
