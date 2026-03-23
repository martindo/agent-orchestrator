"""Team Registry — thread-safe registration and lookup for capabilities.

Mirrors the ContractRegistry pattern: single in-process store with
reentrant lock protection for all mutations.
"""

from __future__ import annotations

import logging
import threading

from agent_orchestrator.catalog.models import CapabilityRegistration
from agent_orchestrator.contracts.models import LifecycleState

logger = logging.getLogger(__name__)


class TeamRegistry:
    """Thread-safe registry for capability registrations.

    Usage:
        registry = TeamRegistry()
        registry.register(registration)
        result = registry.get("market_research.v1")
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._registrations: dict[str, CapabilityRegistration] = {}

    def register(self, registration: CapabilityRegistration) -> None:
        """Register or update a capability.

        If a registration with the same capability_id exists it is replaced.

        Args:
            registration: The capability registration to store.
        """
        with self._lock:
            existed = registration.capability_id in self._registrations
            self._registrations[registration.capability_id] = registration
            verb = "Updated" if existed else "Registered"
            logger.info(
                "%s capability: id=%s profile=%s status=%s",
                verb,
                registration.capability_id,
                registration.profile_name,
                registration.status.value,
            )

    def get(self, capability_id: str) -> CapabilityRegistration | None:
        """Return a registration by ID, or None if not found.

        Args:
            capability_id: Unique capability identifier.
        """
        with self._lock:
            return self._registrations.get(capability_id)

    def find(
        self,
        *,
        tags: list[str] | None = None,
        status: LifecycleState | None = None,
        profile_name: str | None = None,
    ) -> list[CapabilityRegistration]:
        """Return registrations matching all provided filters.

        Args:
            tags: If provided, registration must contain all listed tags.
            status: If provided, registration must have this lifecycle state.
            profile_name: If provided, registration must be bound to this profile.

        Returns:
            List of matching registrations.
        """
        with self._lock:
            results: list[CapabilityRegistration] = []
            for reg in self._registrations.values():
                if tags and not all(t in reg.tags for t in tags):
                    continue
                if status is not None and reg.status != status:
                    continue
                if profile_name is not None and reg.profile_name != profile_name:
                    continue
                results.append(reg)
            return results

    def list_all(self) -> list[CapabilityRegistration]:
        """Return all registered capabilities."""
        with self._lock:
            return list(self._registrations.values())

    def unregister(self, capability_id: str) -> bool:
        """Remove a capability by ID.

        Args:
            capability_id: Unique capability identifier.

        Returns:
            True if the capability existed and was removed, False otherwise.
        """
        with self._lock:
            if capability_id in self._registrations:
                del self._registrations[capability_id]
                logger.info("Unregistered capability: id=%s", capability_id)
                return True
            return False

    def summary(self) -> dict:
        """Return a summary of registered capabilities."""
        with self._lock:
            status_counts: dict[str, int] = {}
            for reg in self._registrations.values():
                key = reg.status.value
                status_counts[key] = status_counts.get(key, 0) + 1
            return {
                "total": len(self._registrations),
                "capability_ids": list(self._registrations.keys()),
                "by_status": status_counts,
            }
