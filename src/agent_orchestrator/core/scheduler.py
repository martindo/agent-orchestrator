"""Workflow scheduler for time-based automatic workflow triggering.

Supports interval-based and daily schedules. Runs a background asyncio
loop that checks schedules every minute and submits work items via a
configurable callback.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScheduleEntry:
    """A scheduled workflow trigger definition.

    Attributes:
        cron: Schedule expression. Supported formats:
            - ``interval:<seconds>`` — run every N seconds.
            - ``daily:<HH>:<MM>`` — run once daily at the given time (UTC).
    """

    id: str
    cron: str
    workflow_id: str
    input_template: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    run_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class WorkflowScheduler:
    """Background scheduler that triggers workflows on a time basis."""

    def __init__(self) -> None:
        self.schedules: list[ScheduleEntry] = []
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._submit_callback: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None

    def set_submit_callback(
        self, callback: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Set the async callback used to submit triggered work items."""
        self._submit_callback = callback

    def add_schedule(self, entry: ScheduleEntry) -> ScheduleEntry:
        """Register a new schedule entry."""
        self.schedules.append(entry)
        logger.info(
            "Schedule added: %s (%s) for workflow %s",
            entry.id, entry.cron, entry.workflow_id,
        )
        return entry

    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a schedule by ID. Returns True if found and removed."""
        before = len(self.schedules)
        self.schedules = [s for s in self.schedules if s.id != schedule_id]
        return len(self.schedules) < before

    def get_all(self) -> list[ScheduleEntry]:
        """Return all registered schedules."""
        return self.schedules

    def get(self, schedule_id: str) -> Optional[ScheduleEntry]:
        """Look up a schedule by ID."""
        return next((s for s in self.schedules if s.id == schedule_id), None)

    def toggle(self, schedule_id: str) -> Optional[ScheduleEntry]:
        """Toggle a schedule's enabled state."""
        entry = self.get(schedule_id)
        if entry:
            entry.enabled = not entry.enabled
        return entry

    async def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Workflow scheduler started")

    async def stop(self) -> None:
        """Stop the background scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Workflow scheduler stopped")

    async def _loop(self) -> None:
        """Main scheduler loop — checks schedules every 60 seconds."""
        while self._running:
            try:
                await self._check_schedules()
            except Exception as exc:
                logger.error("Scheduler error: %s", exc, exc_info=True)
            await asyncio.sleep(60)

    async def _check_schedules(self) -> None:
        """Evaluate all enabled schedules and trigger due ones."""
        now = datetime.utcnow()
        for entry in self.schedules:
            if not entry.enabled:
                continue

            should_run = self._is_due(entry, now)

            if should_run and self._submit_callback:
                await self._trigger(entry, now)

    def _is_due(self, entry: ScheduleEntry, now: datetime) -> bool:
        """Determine whether a schedule entry should fire now."""
        if entry.cron.startswith("interval:"):
            interval = int(entry.cron.split(":")[1])
            if entry.last_run:
                last = datetime.fromisoformat(entry.last_run)
                return (now - last).total_seconds() >= interval
            return True

        if entry.cron.startswith("daily:"):
            parts = entry.cron.split(":")
            target_hour, target_min = int(parts[1]), int(parts[2])
            if now.hour == target_hour and now.minute == target_min:
                if entry.last_run:
                    last = datetime.fromisoformat(entry.last_run)
                    return (now - last).total_seconds() > 3600
                return True

        return False

    async def _trigger(self, entry: ScheduleEntry, now: datetime) -> None:
        """Submit a work item for a due schedule entry."""
        try:
            work_item: dict[str, Any] = {
                "id": f"sched-{entry.id}-{int(now.timestamp())}",
                "title": f"Scheduled: {entry.workflow_id}",
                "type_id": entry.workflow_id,
                "data": entry.input_template,
                "priority": 5,
                "metadata": {"scheduled": True, "schedule_id": entry.id},
            }
            if self._submit_callback:
                await self._submit_callback(work_item)
            entry.last_run = now.isoformat()
            entry.run_count += 1
            logger.info("Scheduled workflow triggered: %s", entry.id)
        except Exception as exc:
            logger.error(
                "Failed to trigger scheduled workflow %s: %s",
                entry.id, exc, exc_info=True,
            )


# Singleton
scheduler = WorkflowScheduler()
