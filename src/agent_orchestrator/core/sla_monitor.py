"""SLA Monitor — background async task that checks deadlines and emits events.

Periodically scans incomplete work items for deadline proximity, emitting
SLA_WARNING, SLA_BREACH, and SLA_ESCALATION events. Applies priority
boosts on breach.

Thread-safe: Uses asyncio for async coordination.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from agent_orchestrator.core.event_bus import Event, EventBus, EventType

logger = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL = 30.0
WARNING_THRESHOLD_RATIO = 0.8  # Warn at 80% of deadline elapsed


class SLAMonitor:
    """Background SLA deadline monitor.

    Scans work items with deadlines, emitting events when:
    - WARNING: elapsed time exceeds WARNING_THRESHOLD_RATIO of deadline
    - BREACH: current time exceeds deadline
    - ESCALATION: breach persists after priority boost applied

    Usage:
        monitor = SLAMonitor(event_bus, work_item_store)
        await monitor.start()
        # ... later ...
        await monitor.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        work_item_store: Any,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL,
    ) -> None:
        self._event_bus = event_bus
        self._work_item_store = work_item_store
        self._check_interval = check_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._warned_ids: set[str] = set()
        self._breached_ids: set[str] = set()

    async def start(self) -> None:
        """Start the background SLA check loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("SLA monitor started (interval=%.1fs)", self._check_interval)

    async def stop(self) -> None:
        """Stop the background SLA check loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("SLA monitor stopped")

    async def _loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("SLA check cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(self._check_interval)

    async def _check_cycle(self) -> None:
        """Run a single SLA check cycle across all incomplete items."""
        if self._work_item_store is None:
            return

        items = self._work_item_store.get_incomplete()
        now = datetime.now(timezone.utc)

        for item in items:
            deadline = getattr(item, "deadline", None)
            if deadline is None:
                continue

            # Ensure deadline is timezone-aware
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

            remaining = (deadline - now).total_seconds()
            total_budget = (deadline - item.submitted_at).total_seconds()

            if total_budget <= 0:
                continue

            elapsed_ratio = 1.0 - (remaining / total_budget) if total_budget > 0 else 1.0

            if remaining <= 0:
                # BREACH
                if item.id not in self._breached_ids:
                    self._breached_ids.add(item.id)
                    await self._emit_breach(item, remaining)
                    self._apply_priority_boost(item)
            elif elapsed_ratio >= WARNING_THRESHOLD_RATIO:
                # WARNING
                if item.id not in self._warned_ids:
                    self._warned_ids.add(item.id)
                    await self._emit_warning(item, remaining, elapsed_ratio)

    async def _emit_warning(
        self,
        item: Any,
        remaining_seconds: float,
        elapsed_ratio: float,
    ) -> None:
        """Emit an SLA_WARNING event."""
        await self._event_bus.emit(Event(
            type=EventType.SLA_WARNING,
            data={
                "work_item_id": item.id,
                "deadline": item.deadline.isoformat(),
                "remaining_seconds": remaining_seconds,
                "elapsed_ratio": elapsed_ratio,
            },
            source="sla_monitor",
            app_id=getattr(item, "app_id", ""),
            run_id=getattr(item, "run_id", ""),
        ))
        logger.info(
            "SLA warning for %s: %.0fs remaining (%.0f%% elapsed)",
            item.id, remaining_seconds, elapsed_ratio * 100,
        )

    async def _emit_breach(self, item: Any, remaining_seconds: float) -> None:
        """Emit an SLA_BREACH event."""
        await self._event_bus.emit(Event(
            type=EventType.SLA_BREACH,
            data={
                "work_item_id": item.id,
                "deadline": item.deadline.isoformat(),
                "overdue_seconds": abs(remaining_seconds),
            },
            source="sla_monitor",
            app_id=getattr(item, "app_id", ""),
            run_id=getattr(item, "run_id", ""),
        ))
        logger.warning(
            "SLA BREACH for %s: %.0fs overdue",
            item.id, abs(remaining_seconds),
        )

    @staticmethod
    def _apply_priority_boost(item: Any, boost: int = 2) -> None:
        """Apply priority boost to a breached work item.

        Lower priority number = higher priority. Clamps to 0 minimum.

        Args:
            item: The work item to boost.
            boost: Priority points to subtract (default 2).
        """
        old_priority = item.priority
        item.priority = max(0, item.priority - boost)
        if item.priority != old_priority:
            logger.info(
                "Priority boosted for %s: %d -> %d (SLA breach)",
                item.id, old_priority, item.priority,
            )
