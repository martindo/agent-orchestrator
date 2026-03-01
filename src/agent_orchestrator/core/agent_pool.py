"""AgentPool — Manages agent instances with concurrency limits.

Creates agent instances from AgentDefinition configs, enforces
concurrency limits per agent type, and tracks agent state.

Thread-safe: All public methods use internal lock.

State Ownership:
- AgentPool owns agent instance lifecycle and availability tracking.
- AgentExecutor owns individual execution state.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from agent_orchestrator.configuration.models import AgentDefinition

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    """Lifecycle state of an agent instance."""

    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    SHUTDOWN = "shutdown"


@dataclass
class AgentInstance:
    """A running instance of an agent definition.

    Tracks the runtime state of a single agent instance.
    Multiple instances can exist per AgentDefinition (up to concurrency limit).
    """

    instance_id: str
    definition: AgentDefinition
    state: AgentState = AgentState.IDLE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime | None = None
    tasks_completed: int = 0
    current_work_id: str | None = None


class AgentPool:
    """Manages a pool of agent instances with concurrency limits.

    Thread-safe: All public methods use internal lock.

    Usage:
        pool = AgentPool()
        pool.register_definitions([agent_def_1, agent_def_2])
        instance = pool.acquire("agent-id")
        # ... use instance ...
        pool.release(instance.instance_id)
    """

    def __init__(self) -> None:
        self._definitions: dict[str, AgentDefinition] = {}
        self._instances: dict[str, AgentInstance] = {}
        self._by_definition: dict[str, list[str]] = {}  # def_id -> [instance_ids]
        self._lock = threading.Lock()
        self._instance_counter = 0

    def register_definitions(self, definitions: list[AgentDefinition]) -> None:
        """Register agent definitions (does not create instances yet).

        Args:
            definitions: Agent definitions to register.
        """
        with self._lock:
            for defn in definitions:
                if defn.enabled:
                    self._definitions[defn.id] = defn
                    if defn.id not in self._by_definition:
                        self._by_definition[defn.id] = []
                    logger.debug(
                        "Registered agent definition '%s' (concurrency=%d)",
                        defn.id, defn.concurrency,
                    )

    def acquire(self, definition_id: str, work_id: str | None = None) -> AgentInstance | None:
        """Acquire an idle agent instance, creating one if under concurrency limit.

        Args:
            definition_id: ID of the agent definition to acquire.
            work_id: Optional work item ID being processed.

        Returns:
            AgentInstance if available, None if at concurrency limit or not found.
        """
        with self._lock:
            defn = self._definitions.get(definition_id)
            if defn is None:
                logger.warning("Unknown agent definition '%s'", definition_id)
                return None

            instance_ids = self._by_definition.get(definition_id, [])

            # Try to find an idle instance
            for iid in instance_ids:
                instance = self._instances.get(iid)
                if instance is not None and instance.state == AgentState.IDLE:
                    instance.state = AgentState.RUNNING
                    instance.current_work_id = work_id
                    instance.last_active = datetime.now(timezone.utc)
                    logger.debug("Acquired existing instance '%s'", iid)
                    return instance

            # Create new instance if under limit
            if len(instance_ids) < defn.concurrency:
                instance = self._create_instance(defn, work_id)
                logger.debug(
                    "Created new instance '%s' for '%s' (%d/%d)",
                    instance.instance_id, definition_id,
                    len(instance_ids) + 1, defn.concurrency,
                )
                return instance

            logger.debug(
                "Agent '%s' at concurrency limit (%d/%d)",
                definition_id, len(instance_ids), defn.concurrency,
            )
            return None

    def _create_instance(
        self, defn: AgentDefinition, work_id: str | None,
    ) -> AgentInstance:
        """Create a new agent instance (must hold lock)."""
        self._instance_counter += 1
        instance_id = f"{defn.id}-{self._instance_counter}"
        instance = AgentInstance(
            instance_id=instance_id,
            definition=defn,
            state=AgentState.RUNNING,
            current_work_id=work_id,
            last_active=datetime.now(timezone.utc),
        )
        self._instances[instance_id] = instance
        self._by_definition[defn.id].append(instance_id)
        return instance

    def release(self, instance_id: str, success: bool = True) -> None:
        """Release an agent instance back to the pool.

        Args:
            instance_id: ID of the instance to release.
            success: Whether the task completed successfully.
        """
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance is None:
                logger.warning("Unknown instance '%s'", instance_id)
                return

            if success:
                instance.state = AgentState.IDLE
                instance.tasks_completed += 1
            else:
                instance.state = AgentState.ERROR

            instance.current_work_id = None
            instance.last_active = datetime.now(timezone.utc)
            logger.debug("Released instance '%s' (success=%s)", instance_id, success)

    def get_instance(self, instance_id: str) -> AgentInstance | None:
        """Get an instance by ID."""
        with self._lock:
            return self._instances.get(instance_id)

    def get_stats(self) -> dict[str, Any]:
        """Get pool statistics per agent definition."""
        with self._lock:
            stats: dict[str, Any] = {}
            for def_id, instance_ids in self._by_definition.items():
                instances = [self._instances[iid] for iid in instance_ids if iid in self._instances]
                defn = self._definitions.get(def_id)
                stats[def_id] = {
                    "max_concurrency": defn.concurrency if defn else 0,
                    "total_instances": len(instances),
                    "idle": sum(1 for i in instances if i.state == AgentState.IDLE),
                    "running": sum(1 for i in instances if i.state == AgentState.RUNNING),
                    "error": sum(1 for i in instances if i.state == AgentState.ERROR),
                    "total_completed": sum(i.tasks_completed for i in instances),
                }
            return stats

    def scale(self, definition_id: str, new_concurrency: int) -> None:
        """Update concurrency limit for an agent definition.

        Args:
            definition_id: Agent definition ID.
            new_concurrency: New concurrency limit.
        """
        with self._lock:
            defn = self._definitions.get(definition_id)
            if defn is None:
                logger.warning("Cannot scale unknown agent '%s'", definition_id)
                return
            # Create unfrozen copy with updated concurrency
            updated = defn.model_copy(update={"concurrency": new_concurrency})
            self._definitions[definition_id] = updated
            logger.info(
                "Scaled agent '%s' concurrency to %d", definition_id, new_concurrency,
            )

    def update_definition(self, definition: AgentDefinition) -> None:
        """Replace a registered agent definition.

        Updates the definition for all idle instances of this agent type.
        Running instances keep their current definition until released.

        Thread-safe: Uses internal lock.

        Args:
            definition: Updated agent definition.
        """
        with self._lock:
            if definition.id not in self._definitions:
                logger.warning(
                    "Cannot update unknown agent definition '%s'", definition.id,
                )
                return

            self._definitions[definition.id] = definition

            # Update idle instances with new definition
            for iid in self._by_definition.get(definition.id, []):
                instance = self._instances.get(iid)
                if instance is not None and instance.state == AgentState.IDLE:
                    instance.definition = definition

            logger.info("Updated agent definition '%s'", definition.id)

    def unregister_definition(self, definition_id: str) -> bool:
        """Remove an agent definition and shut down all its instances.

        Thread-safe: Uses internal lock.

        Args:
            definition_id: ID of the agent definition to remove.

        Returns:
            True if definition was found and removed.
        """
        with self._lock:
            if definition_id not in self._definitions:
                logger.warning(
                    "Cannot unregister unknown agent definition '%s'", definition_id,
                )
                return False

            # Shutdown and remove all instances for this definition
            instance_ids = self._by_definition.pop(definition_id, [])
            for iid in instance_ids:
                instance = self._instances.pop(iid, None)
                if instance is not None:
                    instance.state = AgentState.SHUTDOWN

            del self._definitions[definition_id]
            logger.info(
                "Unregistered agent definition '%s' (%d instances removed)",
                definition_id, len(instance_ids),
            )
            return True

    def shutdown(self) -> None:
        """Shutdown all agent instances."""
        with self._lock:
            for instance in self._instances.values():
                instance.state = AgentState.SHUTDOWN
            logger.info("Shut down %d agent instances", len(self._instances))
