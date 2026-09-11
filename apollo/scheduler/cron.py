import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("apollo.scheduler")

@dataclass
class ScheduledTask:
    task_id: str
    name: str
    prompt: str
    cron_expr: Optional[str] = None
    interval_seconds: Optional[int] = None
    enabled: bool = True

class BackgroundScheduler:
    """Background cron and interval scheduler for APOLLO unprompted autonomous actions with SQLite persistence."""

    def __init__(
        self,
        task_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        memory_store: Optional[Any] = None,
    ):
        self._scheduler = AsyncIOScheduler()
        self.task_callback = task_callback
        self.memory_store = memory_store
        self.tasks: Dict[str, ScheduledTask] = {}

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Background Scheduler started.")

            # Restore persisted tasks from memory store
            if self.memory_store and hasattr(self.memory_store, "get_all_scheduled_tasks"):
                try:
                    persisted = self.memory_store.get_all_scheduled_tasks()
                    for pt in persisted:
                        if pt.get("enabled", 1):
                            self.add_task(
                                task_id=pt["task_id"],
                                name=pt["name"],
                                prompt=pt["prompt"],
                                cron_expr=pt.get("cron_expr"),
                                interval_seconds=pt.get("interval_seconds"),
                                persist=False,
                            )
                    logger.info(f"Restored {len(persisted)} scheduled task(s) from persistent database.")
                except Exception as e:
                    logger.error(f"Failed to restore scheduled tasks from database: {e}")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Background Scheduler stopped.")

    def add_task(
        self,
        task_id: str,
        name: str,
        prompt: str,
        cron_expr: Optional[str] = None,
        interval_seconds: Optional[int] = None,
        persist: bool = True,
    ) -> ScheduledTask:
        """Register a new scheduled job."""
        if not cron_expr and not interval_seconds:
            raise ValueError("Either cron_expr or interval_seconds must be provided.")

        task = ScheduledTask(
            task_id=task_id,
            name=name,
            prompt=prompt,
            cron_expr=cron_expr,
            interval_seconds=interval_seconds,
            enabled=True,
        )

        async def _job_wrapper():
            logger.info(f"Triggering scheduled task '{name}' (id={task_id})")
            if self.task_callback:
                try:
                    await self.task_callback(task_id, prompt)
                except Exception as e:
                    logger.error(f"Error executing scheduled task '{task_id}': {e}")

        if cron_expr:
            trigger = CronTrigger.from_crontab(cron_expr)
        else:
            trigger = IntervalTrigger(seconds=interval_seconds)

        self._scheduler.add_job(
            _job_wrapper,
            trigger=trigger,
            id=task_id,
            replace_existing=True,
        )

        self.tasks[task_id] = task
        logger.info(f"Added scheduled task '{name}' (id={task_id})")

        # Persist to database if requested
        if persist and self.memory_store and hasattr(self.memory_store, "save_scheduled_task"):
            try:
                self.memory_store.save_scheduled_task(
                    task_id=task_id,
                    name=name,
                    prompt=prompt,
                    cron_expr=cron_expr,
                    interval_seconds=interval_seconds,
                    enabled=True,
                )
                logger.info(f"Persisted scheduled task '{task_id}' to database.")
            except Exception as e:
                logger.error(f"Failed to persist scheduled task '{task_id}': {e}")

        return task

    def remove_task(self, task_id: str) -> bool:
        """Remove a task by ID."""
        if task_id in self.tasks:
            self._scheduler.remove_job(task_id)
            del self.tasks[task_id]

            # Remove from persistent store
            if self.memory_store and hasattr(self.memory_store, "remove_scheduled_task"):
                try:
                    self.memory_store.remove_scheduled_task(task_id)
                    logger.info(f"Removed persisted scheduled task '{task_id}' from database.")
                except Exception as e:
                    logger.error(f"Failed to remove persisted task '{task_id}': {e}")

            logger.info(f"Removed scheduled task '{task_id}'")
            return True
        return False

    def list_tasks(self) -> List[ScheduledTask]:
        """List all active scheduled tasks."""
        return list(self.tasks.values())
