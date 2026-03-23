"""Tests for SLAMonitor — background deadline monitoring."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from agent_orchestrator.core.event_bus import Event, EventBus, EventType
from agent_orchestrator.core.sla_monitor import (
    DEFAULT_CHECK_INTERVAL,
    WARNING_THRESHOLD_RATIO,
    SLAMonitor,
)


# ---- Fake Work Item ----


@dataclass
class FakeWorkItem:
    """Minimal work item for SLA testing."""

    id: str = "wi-1"
    priority: int = 5
    submitted_at: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    deadline: datetime | None = None
    app_id: str = "default"
    run_id: str = "run-1"


class FakeWorkItemStore:
    """In-memory store returning fake incomplete items."""

    def __init__(self, items: list[FakeWorkItem] | None = None) -> None:
        self._items = items or []

    def get_incomplete(self) -> list[FakeWorkItem]:
        return list(self._items)


# ---- Tests: Construction ----


class TestSLAMonitorConstruction:
    def test_defaults(self) -> None:
        bus = EventBus()
        monitor = SLAMonitor(bus, FakeWorkItemStore())
        assert monitor._check_interval == DEFAULT_CHECK_INTERVAL
        assert monitor._running is False
        assert monitor._task is None

    def test_custom_interval(self) -> None:
        bus = EventBus()
        monitor = SLAMonitor(bus, FakeWorkItemStore(), check_interval_seconds=10.0)
        assert monitor._check_interval == 10.0


# ---- Tests: Check Cycle ----


class TestCheckCycle:
    @pytest.mark.asyncio
    async def test_no_items(self) -> None:
        """No items → no events emitted."""
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe_all(capture)
        monitor = SLAMonitor(bus, FakeWorkItemStore())
        await monitor._check_cycle()
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_no_deadline(self) -> None:
        """Items without deadlines are skipped."""
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe_all(capture)
        store = FakeWorkItemStore([FakeWorkItem(deadline=None)])
        monitor = SLAMonitor(bus, store)
        await monitor._check_cycle()
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_warning_emitted(self) -> None:
        """Item at 85% elapsed → SLA_WARNING emitted."""
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe_all(capture)

        now = datetime.now(timezone.utc)
        # Submitted 100 seconds ago, deadline in 15 seconds → 87% elapsed
        submitted = now - timedelta(seconds=100)
        deadline = now + timedelta(seconds=15)

        item = FakeWorkItem(submitted_at=submitted, deadline=deadline)
        store = FakeWorkItemStore([item])
        monitor = SLAMonitor(bus, store)
        await monitor._check_cycle()

        assert len(events) == 1
        assert events[0].type == EventType.SLA_WARNING
        assert events[0].data["work_item_id"] == "wi-1"

    @pytest.mark.asyncio
    async def test_breach_emitted(self) -> None:
        """Item past deadline → SLA_BREACH emitted + priority boosted."""
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe_all(capture)

        now = datetime.now(timezone.utc)
        submitted = now - timedelta(seconds=200)
        deadline = now - timedelta(seconds=10)  # Already past

        item = FakeWorkItem(submitted_at=submitted, deadline=deadline, priority=5)
        store = FakeWorkItemStore([item])
        monitor = SLAMonitor(bus, store)
        await monitor._check_cycle()

        assert len(events) == 1
        assert events[0].type == EventType.SLA_BREACH
        # Priority should be boosted (5 - 2 = 3)
        assert item.priority == 3

    @pytest.mark.asyncio
    async def test_no_duplicate_warning(self) -> None:
        """Same item warned only once."""
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe_all(capture)

        now = datetime.now(timezone.utc)
        submitted = now - timedelta(seconds=100)
        deadline = now + timedelta(seconds=15)

        item = FakeWorkItem(submitted_at=submitted, deadline=deadline)
        store = FakeWorkItemStore([item])
        monitor = SLAMonitor(bus, store)

        await monitor._check_cycle()
        await monitor._check_cycle()

        assert len(events) == 1  # Only one warning

    @pytest.mark.asyncio
    async def test_no_duplicate_breach(self) -> None:
        """Same item breached only once."""
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe_all(capture)

        now = datetime.now(timezone.utc)
        submitted = now - timedelta(seconds=200)
        deadline = now - timedelta(seconds=10)

        item = FakeWorkItem(submitted_at=submitted, deadline=deadline)
        store = FakeWorkItemStore([item])
        monitor = SLAMonitor(bus, store)

        await monitor._check_cycle()
        await monitor._check_cycle()

        assert len(events) == 1  # Only one breach

    @pytest.mark.asyncio
    async def test_null_store(self) -> None:
        """None store → silently skip."""
        bus = EventBus()
        monitor = SLAMonitor(bus, None)  # type: ignore[arg-type]
        await monitor._check_cycle()  # Should not raise


# ---- Tests: Priority Boost ----


class TestPriorityBoost:
    def test_boost_normal(self) -> None:
        item = FakeWorkItem(priority=5)
        SLAMonitor._apply_priority_boost(item)
        assert item.priority == 3

    def test_boost_clamp_zero(self) -> None:
        item = FakeWorkItem(priority=1)
        SLAMonitor._apply_priority_boost(item)
        assert item.priority == 0

    def test_boost_already_zero(self) -> None:
        item = FakeWorkItem(priority=0)
        SLAMonitor._apply_priority_boost(item)
        assert item.priority == 0

    def test_custom_boost(self) -> None:
        item = FakeWorkItem(priority=10)
        SLAMonitor._apply_priority_boost(item, boost=5)
        assert item.priority == 5


# ---- Tests: Start/Stop ----


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        bus = EventBus()
        monitor = SLAMonitor(bus, FakeWorkItemStore(), check_interval_seconds=0.1)

        await monitor.start()
        assert monitor._running is True
        assert monitor._task is not None

        await monitor.stop()
        assert monitor._running is False
        assert monitor._task is None

    @pytest.mark.asyncio
    async def test_double_start(self) -> None:
        bus = EventBus()
        monitor = SLAMonitor(bus, FakeWorkItemStore(), check_interval_seconds=0.1)

        await monitor.start()
        task1 = monitor._task
        await monitor.start()  # Should be no-op
        assert monitor._task is task1

        await monitor.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self) -> None:
        bus = EventBus()
        monitor = SLAMonitor(bus, FakeWorkItemStore())
        await monitor.stop()  # Should not raise


# ---- Tests: Naive Deadline Handling ----


class TestNaiveDeadline:
    @pytest.mark.asyncio
    async def test_naive_deadline_treated_as_utc(self) -> None:
        """Deadlines without timezone are treated as UTC."""
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe_all(capture)

        now = datetime.now(timezone.utc)
        submitted = now - timedelta(seconds=200)
        # Naive datetime (no tzinfo) that is in the past
        deadline_naive = (now - timedelta(seconds=10)).replace(tzinfo=None)

        item = FakeWorkItem(submitted_at=submitted, deadline=deadline_naive)
        store = FakeWorkItemStore([item])
        monitor = SLAMonitor(bus, store)
        await monitor._check_cycle()

        assert len(events) == 1
        assert events[0].type == EventType.SLA_BREACH
