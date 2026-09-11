"""
apollo/tools/reminders.py — Natural Language Reminders & Timers for APOLLO.

Tools:
  - SetReminderTool    : Set one-shot timers or time-targeted reminders.
  - ListRemindersTool  : List all pending reminders.
  - CancelReminderTool : Cancel a pending reminder.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from apollo.scheduler.cron import BackgroundScheduler
from apollo.tools.base import BaseTool

logger = logging.getLogger("apollo.tools.reminders")


def parse_time_spec_to_seconds(time_spec: str) -> Optional[int]:
    """
    Parse relative time offsets like '35m', '1h', '45s', '1h30m', '90 minutes', '2 hours'
    or target clock times like '14:30', '11:00 PM', '23:00'.
    Returns total seconds from now, or None if unparseable.
    """
    spec = time_spec.strip().lower()

    # 1. Pure seconds integer
    if spec.isdigit():
        return max(1, int(spec))

    # 2. Compound relative patterns like '1h30m', '2h 15m', '45s', '30 secs', '10m'
    rel_pattern = r"^((?P<hours>\d+)\s*(?:h|hr|hours?))?\s*((?P<minutes>\d+)\s*(?:m|min|mins?|minutes?))?\s*((?P<seconds>\d+)\s*(?:s|sec|secs|seconds?))?$"
    m = re.match(rel_pattern, spec)
    if m and any(m.groups()):
        h = int(m.group("hours") or 0)
        mins = int(m.group("minutes") or 0)
        s = int(m.group("seconds") or 0)
        total = h * 3600 + mins * 60 + s
        if total > 0:
            return total

    # 3. Simple unit string like "in 30 mins", "in 2 hours"
    in_pattern = r"^in\s+(\d+)\s+(seconds?|secs?|minutes?|mins?|hours?|hrs?)$"
    m = re.match(in_pattern, spec)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("h"):
            return num * 3600
        elif unit.startswith("m"):
            return num * 60
        elif unit.startswith("s"):
            return num

    # 4. Clock time (e.g. "14:30", "9:15", "11:00 pm", "8:30 am", "at 18:00")
    clock_spec = re.sub(r"^at\s+", "", spec)
    clock_match = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)?$", clock_spec)
    if clock_match:
        hour = int(clock_match.group(1))
        minute = int(clock_match.group(2))
        meridiem = clock_match.group(3)

        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            # If time has already passed today, set for tomorrow
            target += timedelta(days=1)
        diff_seconds = int((target - now).total_seconds())
        return max(1, diff_seconds)

    return None


class SetReminderTool(BaseTool):
    """Set a natural language timer or reminder with persistent SQLite scheduling."""

    name = "set_reminder"
    description = (
        "Set a timer or reminder. Accepts relative times like '35m', '1h', '45s', '1h30m', 'in 10 minutes' "
        "or target times like '14:30', '11:00 PM'. Alerts the owner in Telegram when due."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "What to remind the owner about (e.g. 'Take out laundry', 'Commit git changes').",
            },
            "time_spec": {
                "type": "string",
                "description": "When to trigger the reminder (e.g. '35m', '2h', '14:30', 'in 15 minutes').",
            },
        },
        "required": ["text", "time_spec"],
    }

    def __init__(self, scheduler: Optional[BackgroundScheduler] = None):
        self.scheduler = scheduler

    async def execute(self, text: str, time_spec: str) -> str:
        if not self.scheduler:
            return "Error: Background scheduler is not configured."

        if not text or not str(text).strip():
            return "Error: Reminder text cannot be empty."

        seconds = parse_time_spec_to_seconds(time_spec)
        if seconds is None:
            return (
                f"Error: Could not parse time specification '{time_spec}'. "
                f"Use formats like '35m', '1h', '45s', '1h30m', 'in 10 mins', or '14:30'."
            )

        task_id = f"reminder_{uuid.uuid4().hex[:8]}"
        target_time = datetime.now() + timedelta(seconds=seconds)
        time_str = target_time.strftime("%I:%M:%S %p (%Y-%m-%d)")

        clean_text = str(text).strip()

        try:
            self.scheduler.add_task(
                task_id=task_id,
                name=f"Reminder: {clean_text[:30]}",
                prompt=clean_text,
                interval_seconds=seconds,
                persist=True,
            )
            return (
                f"🔔 **Reminder Set**\n\n"
                f"📝 **Task**: {clean_text}\n"
                f"⏱️ **Due In**: {seconds // 60}m {seconds % 60}s\n"
                f"📅 **Time**: `{time_str}`\n"
                f"🆔 **ID**: `{task_id}`"
            )
        except Exception as e:
            logger.error(f"Failed to schedule reminder: {e}")
            return f"Error setting reminder: {e}"


class ListRemindersTool(BaseTool):
    """List all currently active pending reminders."""

    name = "list_reminders"
    description = "List all active pending reminders and timers."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, scheduler: Optional[BackgroundScheduler] = None):
        self.scheduler = scheduler

    async def execute(self) -> str:
        if not self.scheduler:
            return "Error: Background scheduler is not configured."

        all_tasks = self.scheduler.list_tasks()
        reminders = [t for t in all_tasks if t.task_id.startswith("reminder_")]

        if not reminders:
            return "No active reminders or timers scheduled."

        lines = ["🔔 **Active Reminders**\n"]
        for r in reminders:
            interval = f"{r.interval_seconds}s" if r.interval_seconds else "custom"
            lines.append(f"• `{r.task_id}`: **{r.prompt}** (interval: `{interval}`)")

        return "\n".join(lines)


class CancelReminderTool(BaseTool):
    """Cancel a pending reminder by ID."""

    name = "cancel_reminder"
    description = "Cancel an active reminder by its reminder ID."
    parameters = {
        "type": "object",
        "properties": {
            "reminder_id": {
                "type": "string",
                "description": "The reminder task ID (e.g. 'reminder_a1b2c3d4').",
            },
        },
        "required": ["reminder_id"],
    }

    def __init__(self, scheduler: Optional[BackgroundScheduler] = None):
        self.scheduler = scheduler

    async def execute(self, reminder_id: str) -> str:
        if not self.scheduler:
            return "Error: Background scheduler is not configured."

        clean_id = reminder_id.strip()
        success = self.scheduler.remove_task(clean_id)
        if success:
            return f"✅ Cancelled reminder `{clean_id}`."

        # Try prefix search if not exact match
        for task in self.scheduler.list_tasks():
            if clean_id in task.task_id and task.task_id.startswith("reminder_"):
                self.scheduler.remove_task(task.task_id)
                return f"✅ Cancelled reminder `{task.task_id}` ({task.prompt})."

        return f"Error: No reminder found with ID matching '{clean_id}'."
