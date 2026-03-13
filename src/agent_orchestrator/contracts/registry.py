"""Contract Registry — thread-safe registration and lookup for contracts.

Provides a single in-process store for CapabilityContracts and ArtifactContracts.
Domain modules register their contracts here at startup; platform components
query the registry to resolve validation rules.

Thread-safe: all mutations are protected by a reentrant lock.
"""

from __future__ import annotations

import logging
import threading

from .models import ArtifactContract, CapabilityContract

logger = logging.getLogger(__name__)


class ContractRegistry:
    """Thread-safe registry for capability and artifact contracts.

    Domain modules may register contracts without modifying platform core:

        registry = ContractRegistry()
        registry.register_capability_contract(
            CapabilityContract(
                contract_id="my-search-contract",
                capability_type="search",
                operation_name="query",
                input_schema={"required": ["q"], "properties": {"q": {"type": "string"}}},
            )
        )

    The registry is intentionally kept separate from the connector registry so that
    contracts remain a pure governance concern, not an execution concern.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._capability_contracts: dict[str, CapabilityContract] = {}
        self._artifact_contracts: dict[str, ArtifactContract] = {}

    # ---- Capability Contracts ----

    def register_capability_contract(self, contract: CapabilityContract) -> None:
        """Register a capability contract.

        If a contract with the same contract_id already exists it is replaced.

        Args:
            contract: The capability contract to register.
        """
        with self._lock:
            existed = contract.contract_id in self._capability_contracts
            self._capability_contracts[contract.contract_id] = contract
            verb = "Updated" if existed else "Registered"
            logger.info(
                "%s capability contract: id=%s capability_type=%s operation=%s",
                verb,
                contract.contract_id,
                contract.capability_type,
                contract.operation_name,
            )

    def get_capability_contract(self, contract_id: str) -> CapabilityContract | None:
        """Return a capability contract by its ID, or None if not registered.

        Args:
            contract_id: Unique contract identifier.
        """
        with self._lock:
            return self._capability_contracts.get(contract_id)

    def find_capability_contracts(
        self,
        capability_type: str,
        operation_name: str,
    ) -> list[CapabilityContract]:
        """Return all contracts matching the given capability_type and operation_name.

        Args:
            capability_type: CapabilityType string value (e.g. "search").
            operation_name: Operation string (e.g. "query").

        Returns:
            List of matching contracts, ordered by registration time (oldest first).
        """
        with self._lock:
            return [
                c
                for c in self._capability_contracts.values()
                if c.capability_type == capability_type
                and c.operation_name == operation_name
            ]

    def list_capability_contracts(self) -> list[CapabilityContract]:
        """Return all registered capability contracts."""
        with self._lock:
            return list(self._capability_contracts.values())

    def unregister_capability_contract(self, contract_id: str) -> bool:
        """Remove a capability contract by ID.

        Args:
            contract_id: Unique contract identifier.

        Returns:
            True if the contract existed and was removed, False otherwise.
        """
        with self._lock:
            if contract_id in self._capability_contracts:
                del self._capability_contracts[contract_id]
                logger.info("Unregistered capability contract: id=%s", contract_id)
                return True
            return False

    # ---- Artifact Contracts ----

    def register_artifact_contract(self, contract: ArtifactContract) -> None:
        """Register an artifact contract.

        If a contract with the same contract_id already exists it is replaced.

        Args:
            contract: The artifact contract to register.
        """
        with self._lock:
            existed = contract.contract_id in self._artifact_contracts
            self._artifact_contracts[contract.contract_id] = contract
            verb = "Updated" if existed else "Registered"
            logger.info(
                "%s artifact contract: id=%s artifact_type=%s",
                verb,
                contract.contract_id,
                contract.artifact_type,
            )

    def get_artifact_contract(self, contract_id: str) -> ArtifactContract | None:
        """Return an artifact contract by its ID, or None if not registered.

        Args:
            contract_id: Unique contract identifier.
        """
        with self._lock:
            return self._artifact_contracts.get(contract_id)

    def find_artifact_contracts(self, artifact_type: str) -> list[ArtifactContract]:
        """Return all contracts matching the given artifact_type.

        Args:
            artifact_type: Artifact type string (e.g. "search_result").

        Returns:
            List of matching contracts, ordered by registration time (oldest first).
        """
        with self._lock:
            return [
                c
                for c in self._artifact_contracts.values()
                if c.artifact_type == artifact_type
            ]

    def list_artifact_contracts(self) -> list[ArtifactContract]:
        """Return all registered artifact contracts."""
        with self._lock:
            return list(self._artifact_contracts.values())

    def unregister_artifact_contract(self, contract_id: str) -> bool:
        """Remove an artifact contract by ID.

        Args:
            contract_id: Unique contract identifier.

        Returns:
            True if the contract existed and was removed, False otherwise.
        """
        with self._lock:
            if contract_id in self._artifact_contracts:
                del self._artifact_contracts[contract_id]
                logger.info("Unregistered artifact contract: id=%s", contract_id)
                return True
            return False

    # ---- Summary ----

    def summary(self) -> dict:
        """Return a summary of registered contracts."""
        with self._lock:
            return {
                "capability_contracts": len(self._capability_contracts),
                "artifact_contracts": len(self._artifact_contracts),
                "capability_contract_ids": list(self._capability_contracts.keys()),
                "artifact_contract_ids": list(self._artifact_contracts.keys()),
            }
