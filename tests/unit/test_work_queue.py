"""Tests for WorkItem lifecycle history and WorkQueue transitions."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import pytest

from agent_orchestrator.core.work_queue import (
    WorkItem,
    WorkItemHistoryEntry,
    WorkItemStatus,
    WorkQueue,
)


# ---- WorkItemHistoryEntry ----


def test_history_entry_is_frozen() -> None:
    entry = WorkItemHistoryEntry(
        timestamp=datetime.now(timezone.utc),
        from_status=None,
        to_status=WorkItemStatus.PENDING,
    )
    with pytest.raises(AttributeError):
        entry.reason = "changed"  # type: ignore[misc]


# ---- WorkItem creation ----


def test_work_item_initial_history() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test Item")
    assert len(item.history) == 1
    assert item.history[0].from_status is None
    assert item.history[0].to_status == WorkItemStatus.PENDING
    assert item.history[0].reason == "created"


def test_work_item_record_transition() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test")
    item.record_transition(
        WorkItemStatus.QUEUED, reason="enqueued", phase_id="phase1",
    )
    assert item.status == WorkItemStatus.QUEUED
    assert len(item.history) == 2
    assert item.history[1].from_status == WorkItemStatus.PENDING
    assert item.history[1].to_status == WorkItemStatus.QUEUED
    assert item.history[1].phase_id == "phase1"
    assert item.history[1].reason == "enqueued"


def test_record_transition_sets_started_at() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test")
    assert item.started_at is None
    item.record_transition(WorkItemStatus.IN_PROGRESS, reason="dequeued")
    assert item.started_at is not None


def test_record_transition_sets_completed_at() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test")
    item.record_transition(WorkItemStatus.QUEUED, reason="enqueued")
    item.record_transition(WorkItemStatus.IN_PROGRESS, reason="dequeued")
    assert item.completed_at is None
    item.record_transition(WorkItemStatus.COMPLETED, reason="done")
    assert item.completed_at is not None


def test_record_transition_sets_completed_at_on_failure() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test")
    item.record_transition(WorkItemStatus.FAILED, reason="error")
    assert item.completed_at is not None


def test_full_lifecycle_history() -> None:
    """Simulate PENDING → QUEUED → IN_PROGRESS → COMPLETED and verify 4 history entries."""
    item = WorkItem(id="w1", type_id="test", title="Test")
    item.record_transition(WorkItemStatus.QUEUED, reason="enqueued")
    item.record_transition(WorkItemStatus.IN_PROGRESS, reason="dequeued")
    item.record_transition(WorkItemStatus.COMPLETED, phase_id="final", reason="done")

    assert len(item.history) == 4
    statuses = [(h.from_status, h.to_status) for h in item.history]
    assert statuses == [
        (None, WorkItemStatus.PENDING),
        (WorkItemStatus.PENDING, WorkItemStatus.QUEUED),
        (WorkItemStatus.QUEUED, WorkItemStatus.IN_PROGRESS),
        (WorkItemStatus.IN_PROGRESS, WorkItemStatus.COMPLETED),
    ]
    # All timestamps should be ordered
    for i in range(1, len(item.history)):
        assert item.history[i].timestamp >= item.history[i - 1].timestamp


# ---- duration_in_status ----


def test_duration_in_status_never_entered() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test")
    assert item.duration_in_status(WorkItemStatus.IN_PROGRESS) is None


def test_duration_in_status_completed() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test")
    item.record_transition(WorkItemStatus.QUEUED, reason="q")
    item.record_transition(WorkItemStatus.IN_PROGRESS, reason="ip")
    item.record_transition(WorkItemStatus.COMPLETED, reason="done")
    duration = item.duration_in_status(WorkItemStatus.IN_PROGRESS)
    assert duration is not None
    assert duration >= 0.0


def test_duration_in_status_current() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test")
    item.record_transition(WorkItemStatus.QUEUED, reason="q")
    item.record_transition(WorkItemStatus.IN_PROGRESS, reason="ip")
    # Still in IN_PROGRESS
    duration = item.duration_in_status(WorkItemStatus.IN_PROGRESS)
    assert duration is not None
    assert duration >= 0.0


# ---- WorkQueue integration ----


@pytest.mark.asyncio
async def test_queue_push_records_transition() -> None:
    queue = WorkQueue()
    item = WorkItem(id="w1", type_id="test", title="Test")
    await queue.push(item)
    assert item.status == WorkItemStatus.QUEUED
    assert len(item.history) == 2
    assert item.history[1].to_status == WorkItemStatus.QUEUED


@pytest.mark.asyncio
async def test_queue_pop_records_transition() -> None:
    queue = WorkQueue()
    item = WorkItem(id="w1", type_id="test", title="Test")
    await queue.push(item)
    popped = await queue.pop(timeout=1.0)
    assert popped is not None
    assert popped.status == WorkItemStatus.IN_PROGRESS
    assert len(popped.history) == 3
    assert popped.history[2].to_status == WorkItemStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_queue_full_lifecycle() -> None:
    """Push → pop → complete: verify full history chain."""
    queue = WorkQueue()
    item = WorkItem(id="w1", type_id="test", title="Test")
    await queue.push(item)
    popped = await queue.pop(timeout=1.0)
    assert popped is not None
    popped.record_transition(WorkItemStatus.COMPLETED, reason="done")

    assert len(popped.history) == 4
    assert popped.history[0].to_status == WorkItemStatus.PENDING
    assert popped.history[1].to_status == WorkItemStatus.QUEUED
    assert popped.history[2].to_status == WorkItemStatus.IN_PROGRESS
    assert popped.history[3].to_status == WorkItemStatus.COMPLETED


def test_record_transition_with_metadata() -> None:
    item = WorkItem(id="w1", type_id="test", title="Test")
    item.record_transition(
        WorkItemStatus.FAILED,
        reason="governance abort",
        metadata={"confidence": 0.3},
    )
    assert item.history[-1].metadata == {"confidence": 0.3}
