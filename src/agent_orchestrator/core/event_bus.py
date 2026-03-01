"""EventBus — Internal pub/sub that decouples engine from UI/API/webhooks.

Provides typed event emission and subscription. All subscribers are
called asynchronously and errors are logged without blocking publishers.

Thread-safe: All public methods use internal lock for subscriber management.

Event types:
- work.* — submitted, started, phase_entered, phase_exited, completed, failed
- agent.* — started, completed, error, scaled
- governance.* — decision, escalation, review_completed
- config.* — reloaded
- system.* — started, stopped, error
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[["Event"], Coroutine[Any, Any, None]]


class EventType(str, Enum):
    """All event types emitted by the orchestration engine."""

    # Work item events
    WORK_SUBMITTED = "work.submitted"
    WORK_STARTED = "work.started"
    WORK_PHASE_ENTERED = "work.phase_entered"
    WORK_PHASE_EXITED = "work.phase_exited"
    WORK_COMPLETED = "work.completed"
    WORK_FAILED = "work.failed"

    # Agent events
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_ERROR = "agent.error"
    AGENT_SCALED = "agent.scaled"
    AGENT_CREATED = "agent.created"
    AGENT_UPDATED = "agent.updated"
    AGENT_DELETED = "agent.deleted"

    # Governance events
    GOVERNANCE_DECISION = "governance.decision"
    GOVERNANCE_ESCALATION = "governance.escalation"
    GOVERNANCE_REVIEW_COMPLETED = "governance.review_completed"

    # Config events
    CONFIG_RELOADED = "config.reloaded"

    # System events
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPED = "system.stopped"
    SYSTEM_ERROR = "system.error"


@dataclass(frozen=True)
class Event:
    """Immutable event emitted by the engine.

    Args:
        type: The event type.
        data: Event payload (varies by type).
        source: Module/component that emitted the event.
        timestamp: When the event was created.
    """

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Async pub/sub event bus for internal orchestration events.

    Thread-safe: Subscriber management uses internal lock.
    Async: Event emission is async; handlers are called concurrently.

    Usage:
        bus = EventBus()
        bus.subscribe(EventType.WORK_SUBMITTED, my_handler)
        await bus.emit(Event(type=EventType.WORK_SUBMITTED, data={...}))
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventHandler]] = {}
        self._wildcard_subscribers: list[EventHandler] = []
        self._lock = threading.Lock()

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type.

        Args:
            event_type: The event type to listen for.
            handler: Async callable to invoke on event.
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)
        logger.debug("Subscribed handler to %s", event_type.value)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all event types.

        Args:
            handler: Async callable to invoke on any event.
        """
        with self._lock:
            self._wildcard_subscribers.append(handler)
        logger.debug("Subscribed wildcard handler")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> bool:
        """Unsubscribe a handler from an event type.

        Args:
            event_type: The event type to unsubscribe from.
            handler: The handler to remove.

        Returns:
            True if handler was found and removed.
        """
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            try:
                handlers.remove(handler)
                return True
            except ValueError:
                return False

    async def emit(self, event: Event) -> None:
        """Emit an event to all subscribers.

        Handlers are called concurrently. Errors in handlers are logged
        but do not prevent other handlers from executing.

        Args:
            event: The event to emit.
        """
        with self._lock:
            type_handlers = list(self._subscribers.get(event.type, []))
            wildcard_handlers = list(self._wildcard_subscribers)

        all_handlers = type_handlers + wildcard_handlers
        if not all_handlers:
            return

        logger.debug(
            "Emitting %s to %d handler(s)", event.type.value, len(all_handlers),
        )

        tasks = [self._safe_call(handler, event) for handler in all_handlers]
        await asyncio.gather(*tasks)

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        """Call a handler, catching and logging any errors."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                "Event handler error for %s: %s",
                event.type.value, e, exc_info=True,
            )

    def clear(self) -> None:
        """Remove all subscribers."""
        with self._lock:
            self._subscribers.clear()
            self._wildcard_subscribers.clear()
