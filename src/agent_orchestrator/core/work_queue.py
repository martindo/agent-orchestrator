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

# Terminal statuses — work items in these states are "done"
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class WorkItemStatus(str, Enum):
    """Status of a work item in the queue/pipeline."""

    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WorkItemHistoryEntry:
    """Immutable record of a single status transition on a work item.

    Captures when the transition happened, which component triggered it,
    and an optional reason string for governance/audit context.
    """

    timestamp: datetime
    from_status: WorkItemStatus | None  # None for initial creation
    to_status: WorkItemStatus
    phase_id: str = ""
    agent_id: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


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
    history: list[WorkItemHistoryEntry] = field(default_factory=list)
    deadline: datetime | None = None
    urgency: str = ""              # "critical" | "high" | "medium" | "low" | ""
    sla_policy_id: str = ""
    routing_tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Record the initial PENDING status in history."""
        if not self.history:
            self.history.append(WorkItemHistoryEntry(
                timestamp=self.submitted_at,
                from_status=None,
                to_status=self.status,
                reason="created",
            ))

    def record_transition(
        self,
        to_status: WorkItemStatus,
        *,
        phase_id: str = "",
        agent_id: str = "",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Transition to a new status, recording the change in history.

        Also updates timestamp fields (started_at, completed_at) as
        appropriate for the target status.
        """
        now = datetime.now(timezone.utc)
        entry = WorkItemHistoryEntry(
            timestamp=now,
            from_status=self.status,
            to_status=to_status,
            phase_id=phase_id,
            agent_id=agent_id,
            reason=reason,
            metadata=metadata or {},
        )
        self.history.append(entry)
        self.status = to_status

        if to_status == WorkItemStatus.IN_PROGRESS and self.started_at is None:
            self.started_at = now
        elif to_status in (WorkItemStatus.COMPLETED, WorkItemStatus.FAILED, WorkItemStatus.CANCELLED):
            self.completed_at = now

    def duration_in_status(self, status: WorkItemStatus) -> float | None:
        """Return seconds spent in a given status, or None if never entered.

        If the item is currently in that status, measures from entry to now.
        If the item passed through that status, measures entry to exit.
        If the item entered the status multiple times, returns the total.
        """
        total = 0.0
        entered_at: datetime | None = None
        was_entered = False

        for entry in self.history:
            if entry.to_status == status and entered_at is None:
                entered_at = entry.timestamp
                was_entered = True
            elif entry.from_status == status and entered_at is not None:
                total += (entry.timestamp - entered_at).total_seconds()
                entered_at = None

        # Still in that status
        if entered_at is not None and self.status == status:
            total += (datetime.now(timezone.utc) - entered_at).total_seconds()

        return total if was_entered else None

    def __lt__(self, other: WorkItem) -> bool:
        """Compare by priority, then deadline proximity, then submission time.

        Items with closer deadlines sort higher when priorities are equal.
        Items with deadlines sort before items without deadlines at same priority.
        """
        if self.priority != other.priority:
            return self.priority < other.priority
        # Deadline proximity as tiebreaker
        if self.deadline is not None and other.deadline is not None:
            return self.deadline < other.deadline
        if self.deadline is not None:
            return True
        if other.deadline is not None:
            return False
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

        item.record_transition(WorkItemStatus.QUEUED, reason="enqueued")
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

        item.record_transition(WorkItemStatus.IN_PROGRESS, reason="dequeued")
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
