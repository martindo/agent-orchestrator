"""WorkQueue — Priority-ordered async queue for pending work items.

Thread-safe: Uses asyncio.PriorityQueue for async operations
and threading.Lock for synchronous metadata access.

Work items are ordered by priority (lower = higher priority),
then by submission time (FIFO for same priority).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---- Named Constants ----

DEFAULT_PRIORITY = 5
MIN_PRIORITY = 0
MAX_PRIORITY = 10
DEFAULT_QUEUE_SIZE = 0  # unbounded


class WorkItemStatus(str, Enum):
    """Status of a work item in the queue/pipeline."""

    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkItem:
    """A work item to be processed through the pipeline.

    Work items are the primary unit of work in the orchestrator.
    They flow through workflow phases and are processed by agents.

    State Ownership: WorkQueue owns the status field.
    Pipeline owns the current_phase field.
    """

    id: str
    type_id: str  # References WorkItemTypeConfig.id
    title: str
    data: dict[str, Any] = field(default_factory=dict)
    priority: int = DEFAULT_PRIORITY
    status: WorkItemStatus = WorkItemStatus.PENDING
    run_id: str = ""
    app_id: str = "default"
    current_phase: str = ""
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    attempt_count: int = 0

    def __lt__(self, other: WorkItem) -> bool:
        """Compare by priority, then submission time."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.submitted_at < other.submitted_at


class WorkQueue:
    """Priority-ordered async work queue.

    Thread-safe: Uses asyncio.PriorityQueue internally.

    Usage:
        queue = WorkQueue()
        await queue.push(work_item)
        item = await queue.pop()
    """

    def __init__(self, max_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue: asyncio.PriorityQueue[WorkItem] = asyncio.PriorityQueue(
            maxsize=max_size,
        )
        self._items: dict[str, WorkItem] = {}
        self._lock = threading.Lock()
        self._total_pushed = 0
        self._total_popped = 0

    async def push(self, item: WorkItem) -> None:
        """Add a work item to the queue.

        Args:
            item: Work item to enqueue.

        Raises:
            ValueError: If item with same ID already in queue.
        """
        with self._lock:
            if item.id in self._items:
                msg = f"Work item '{item.id}' already in queue"
                raise ValueError(msg)
            self._items[item.id] = item
            self._total_pushed += 1

        item.status = WorkItemStatus.QUEUED
        await self._queue.put(item)
        logger.debug("Queued work item '%s' (priority=%d)", item.id, item.priority)

    async def pop(self, timeout: float | None = None) -> WorkItem | None:
        """Get the highest-priority work item.

        Args:
            timeout: Max seconds to wait. None = wait forever.

        Returns:
            Work item, or None if timeout expires.
        """
        try:
            if timeout is not None:
                item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            else:
                item = await self._queue.get()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None

        with self._lock:
            self._items.pop(item.id, None)
            self._total_popped += 1

        item.status = WorkItemStatus.IN_PROGRESS
        logger.debug("Dequeued work item '%s'", item.id)
        return item

    def size(self) -> int:
        """Current number of items in queue."""
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """True if queue has no items."""
        return self._queue.empty()

    def get_item(self, item_id: str) -> WorkItem | None:
        """Get a queued item by ID without removing it."""
        with self._lock:
            return self._items.get(item_id)

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            return {
                "current_size": self._queue.qsize(),
                "total_pushed": self._total_pushed,
                "total_popped": self._total_popped,
            }
