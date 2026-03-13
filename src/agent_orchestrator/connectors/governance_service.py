"""ConnectorGovernanceService — runtime governance for connector lifecycle.

Provides enable/disable, module/role scoping, permission policy management,
and context-aware discovery without any domain semantics.

All mutations operate on frozen Pydantic models via model_copy(update={...})
and re-register the updated config with the registry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..exceptions import OrchestratorError
from .models import (
    CapabilityType,
    ConnectorConfig,
    ConnectorInvocationRequest,
    ConnectorPermissionPolicy,
)
from .permissions import PermissionOutcome, evaluate_permission_detailed
from .registry import ConnectorRegistry

logger = logging.getLogger(__name__)


class ConnectorGovernanceError(OrchestratorError):
    """Raised when a governance operation cannot be completed."""


@dataclass(frozen=True)
class ConnectorDiscoveryItem:
    """Describes a connector that is accessible in a given execution context."""

    connector_id: str
    provider_id: str
    capability_type: str
    display_name: str
    provider_available: bool
    available_operations: list[str]
    scoped_modules: list[str]
    scoped_agent_roles: list[str]

    def as_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "connector_id": self.connector_id,
            "provider_id": self.provider_id,
            "capability_type": self.capability_type,
            "display_name": self.display_name,
            "provider_available": self.provider_available,
            "available_operations": list(self.available_operations),
            "scoped_modules": list(self.scoped_modules),
            "scoped_agent_roles": list(self.scoped_agent_roles),
        }


@dataclass(frozen=True)
class EffectivePermissions:
    """Resolved permission set for a connector in a given execution context."""

    connector_id: str
    enabled: bool
    scoped_modules: list[str]
    scoped_agent_roles: list[str]
    allowed_operations: list[str]
    denied_operations: list[str]
    requires_approval_operations: list[str]

    def as_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "connector_id": self.connector_id,
            "enabled": self.enabled,
            "scoped_modules": list(self.scoped_modules),
            "scoped_agent_roles": list(self.scoped_agent_roles),
            "allowed_operations": list(self.allowed_operations),
            "denied_operations": list(self.denied_operations),
            "requires_approval_operations": list(self.requires_approval_operations),
        }


class ConnectorGovernanceService:
    """Runtime governance for connector availability and permissions.

    Wraps a ConnectorRegistry to provide:
    - Lifecycle management: enable/disable connectors at runtime
    - Scoping: restrict connectors to specific modules or agent roles
    - Policy management: add/remove permission policies on configs
    - Discovery: enumerate connectors available for a given execution context
    - Effective permissions: resolve what a context can actually do

    All mutations replace frozen ConnectorConfig instances via
    ``model_copy(update={...})`` and re-register with the registry.
    The registry itself is the single source of truth.

    Usage::

        governance = ConnectorGovernanceService(registry)
        governance.disable_connector("ticketing.jira")
        governance.update_scoping("ticketing.jira", scoped_modules=["incident-response"])
        items = governance.discover(module_name="incident-response", agent_role="triage")
    """

    def __init__(self, registry: ConnectorRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Lifecycle management
    # ------------------------------------------------------------------

    def enable_connector(self, connector_id: str) -> ConnectorConfig:
        """Enable a connector so it participates in execution and discovery.

        Args:
            connector_id: The connector configuration ID to enable.

        Returns:
            The updated ConnectorConfig.

        Raises:
            ConnectorGovernanceError: If no config is registered for the ID.
        """
        updated = self._replace_config(connector_id, enabled=True)
        logger.info("Connector enabled: %s", connector_id)
        return updated

    def disable_connector(self, connector_id: str) -> ConnectorConfig:
        """Disable a connector, blocking execution and hiding it from discovery.

        Args:
            connector_id: The connector configuration ID to disable.

        Returns:
            The updated ConnectorConfig.

        Raises:
            ConnectorGovernanceError: If no config is registered for the ID.
        """
        updated = self._replace_config(connector_id, enabled=False)
        logger.info("Connector disabled: %s", connector_id)
        return updated

    # ------------------------------------------------------------------
    # Scoping
    # ------------------------------------------------------------------

    def update_scoping(
        self,
        connector_id: str,
        scoped_modules: list[str] | None = None,
        scoped_agent_roles: list[str] | None = None,
    ) -> ConnectorConfig:
        """Update module and/or agent-role scoping for a connector.

        Pass an empty list to clear a restriction; pass None to leave the
        existing value unchanged.

        Args:
            connector_id: The connector configuration ID to update.
            scoped_modules: New module allow-list, or None to leave unchanged.
            scoped_agent_roles: New role allow-list, or None to leave unchanged.

        Returns:
            The updated ConnectorConfig.

        Raises:
            ConnectorGovernanceError: If no config is registered for the ID.
        """
        config = self._get_config_or_raise(connector_id)
        updates: dict = {}
        if scoped_modules is not None:
            updates["scoped_modules"] = list(scoped_modules)
        if scoped_agent_roles is not None:
            updates["scoped_agent_roles"] = list(scoped_agent_roles)
        if not updates:
            return config
        updated = config.model_copy(update=updates)
        self._registry.register_config(updated)
        logger.info(
            "Connector scoping updated: %s modules=%r roles=%r",
            connector_id, updates.get("scoped_modules"), updates.get("scoped_agent_roles"),
        )
        return updated

    # ------------------------------------------------------------------
    # Permission policy management
    # ------------------------------------------------------------------

    def add_policy(
        self,
        connector_id: str,
        policy: ConnectorPermissionPolicy,
    ) -> ConnectorConfig:
        """Append a permission policy to a connector configuration.

        Args:
            connector_id: The connector configuration ID.
            policy: The ConnectorPermissionPolicy to add.

        Returns:
            The updated ConnectorConfig with the policy appended.

        Raises:
            ConnectorGovernanceError: If no config is registered for the ID.
        """
        config = self._get_config_or_raise(connector_id)
        new_policies = list(config.permission_policies) + [policy]
        updated = config.model_copy(update={"permission_policies": new_policies})
        self._registry.register_config(updated)
        logger.info(
            "Policy added to connector %r: policy_id=%r", connector_id, policy.policy_id
        )
        return updated

    def remove_policy(self, connector_id: str, policy_id: str) -> ConnectorConfig:
        """Remove a permission policy from a connector configuration.

        Args:
            connector_id: The connector configuration ID.
            policy_id: The policy_id of the policy to remove.

        Returns:
            The updated ConnectorConfig with the policy removed.

        Raises:
            ConnectorGovernanceError: If no config is registered, or if the
                policy_id does not exist in the config.
        """
        config = self._get_config_or_raise(connector_id)
        remaining = [p for p in config.permission_policies if p.policy_id != policy_id]
        if len(remaining) == len(config.permission_policies):
            raise ConnectorGovernanceError(
                f"Policy {policy_id!r} not found on connector {connector_id!r}"
            )
        updated = config.model_copy(update={"permission_policies": remaining})
        self._registry.register_config(updated)
        logger.info(
            "Policy removed from connector %r: policy_id=%r", connector_id, policy_id
        )
        return updated

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(
        self,
        module_name: str | None = None,
        agent_role: str | None = None,
    ) -> list[ConnectorDiscoveryItem]:
        """Return connectors accessible in the given execution context.

        A connector is accessible when:
        - Its config has ``enabled=True``
        - ``scoped_modules`` is empty OR ``module_name`` is in the list
        - ``scoped_agent_roles`` is empty OR ``agent_role`` is in the list

        Args:
            module_name: Execution context module name, or None (match-all).
            agent_role: Execution context agent role, or None (match-all).

        Returns:
            List of ConnectorDiscoveryItem instances for accessible connectors.
        """
        results: list[ConnectorDiscoveryItem] = []
        for config in self._registry.list_configs():
            if not config.enabled:
                continue
            if config.scoped_modules and module_name not in config.scoped_modules:
                continue
            if config.scoped_agent_roles and agent_role not in config.scoped_agent_roles:
                continue

            provider = self._registry.get_provider(config.provider_id)
            provider_available = (
                provider is not None and provider.get_descriptor().enabled
            )
            operations: list[str] = []
            if provider:
                operations = [
                    op.operation for op in provider.get_descriptor().operations
                ]

            results.append(
                ConnectorDiscoveryItem(
                    connector_id=config.connector_id,
                    provider_id=config.provider_id,
                    capability_type=config.capability_type.value,
                    display_name=config.display_name,
                    provider_available=provider_available,
                    available_operations=operations,
                    scoped_modules=list(config.scoped_modules),
                    scoped_agent_roles=list(config.scoped_agent_roles),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Effective permissions
    # ------------------------------------------------------------------

    def get_effective_permissions(
        self,
        connector_id: str,
        module_name: str | None = None,
        agent_role: str | None = None,
    ) -> EffectivePermissions:
        """Resolve which operations are allowed/denied/gated for a context.

        Evaluates each operation declared by the connector's provider against
        all attached permission policies, using the given module and role as
        the execution context.

        Args:
            connector_id: The connector configuration ID.
            module_name: Execution context module name, or None.
            agent_role: Execution context agent role, or None.

        Returns:
            EffectivePermissions summarising the resolved access.

        Raises:
            ConnectorGovernanceError: If no config is registered for the ID.
        """
        config = self._get_config_or_raise(connector_id)

        provider = self._registry.get_provider(config.provider_id)
        operations: list[str] = []
        if provider:
            operations = [
                op.operation for op in provider.get_descriptor().operations
            ]

        allowed: list[str] = []
        denied: list[str] = []
        requires_approval: list[str] = []

        ctx = {
            "module_name": module_name or "",
            "agent_role": agent_role or "",
        }

        for op in operations:
            req = ConnectorInvocationRequest(
                capability_type=config.capability_type,
                operation=op,
                parameters={},
                context=ctx,
            )
            result = evaluate_permission_detailed(req, list(config.permission_policies))
            if result.outcome == PermissionOutcome.DENY:
                denied.append(op)
            elif result.outcome == PermissionOutcome.REQUIRES_APPROVAL:
                requires_approval.append(op)
            else:
                allowed.append(op)

        return EffectivePermissions(
            connector_id=connector_id,
            enabled=config.enabled,
            scoped_modules=list(config.scoped_modules),
            scoped_agent_roles=list(config.scoped_agent_roles),
            allowed_operations=allowed,
            denied_operations=denied,
            requires_approval_operations=requires_approval,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_config_or_raise(self, connector_id: str) -> ConnectorConfig:
        """Return the config for connector_id or raise ConnectorGovernanceError."""
        config = self._registry.get_config(connector_id)
        if config is None:
            raise ConnectorGovernanceError(
                f"No connector config registered for id={connector_id!r}"
            )
        return config

    def _replace_config(self, connector_id: str, **updates: object) -> ConnectorConfig:
        """Create an updated copy of a config and re-register it.

        Uses Pydantic v2 model_copy(update={...}) to produce a new frozen
        instance, then registers it with the registry (replacing the old one).
        """
        config = self._get_config_or_raise(connector_id)
        updated = config.model_copy(update=updates)
        self._registry.register_config(updated)
        return updated
