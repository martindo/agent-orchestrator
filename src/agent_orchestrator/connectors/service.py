"""ConnectorService — primary invocation abstraction for external connectors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..exceptions import OrchestratorError
from .executor import ConnectorExecutor
from .models import (
    CapabilityType,
    ConnectorConfig,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorRetryPolicy,
    ConnectorStatus,
    ExternalArtifact,
)
from .permissions import evaluate_permission, evaluate_permission_detailed, PermissionOutcome
from .registry import ConnectorRegistry
from .trace import ConnectorExecutionTrace, ConnectorTraceStore

if TYPE_CHECKING:
    from ..adapters.metrics_adapter import MetricsCollector
    from ..contracts.validator import ContractValidator
    from ..governance.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class ConnectorServiceError(OrchestratorError):
    """Raised when the connector service encounters an unrecoverable error."""


class ConnectorService:
    """Platform-level service for executing external connector capabilities.

    Domain-agnostic: all capability types and operations are generic strings or
    CapabilityType enum values. Domain modules call this service and adapt the
    results into domain-specific artifacts.

    Usage:
        service = ConnectorService(registry=registry, audit_logger=audit_logger)
        result = await service.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={"q": "example"},
            context={"run_id": "r1", "workflow_id": "w1"},
        )
    """

    def __init__(
        self,
        registry: ConnectorRegistry,
        audit_logger: "AuditLogger | None" = None,
        metrics: "MetricsCollector | None" = None,
        trace_store: ConnectorTraceStore | None = None,
        contract_validator: "ContractValidator | None" = None,
    ) -> None:
        self._registry = registry
        self._audit_logger = audit_logger
        self._trace_store = trace_store or ConnectorTraceStore()
        self._contract_validator = contract_validator
        self._executor = ConnectorExecutor(
            trace_store=self._trace_store,
            metrics=metrics,
        )

    async def execute(
        self,
        capability_type: CapabilityType | str,
        operation: str,
        parameters: dict,
        context: dict | None = None,
        preferred_provider: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ConnectorInvocationResult:
        """Execute a connector capability.

        Args:
            capability_type: Category from CapabilityType enum or valid string value.
            operation: Specific operation to perform (e.g. "query", "create_issue").
            parameters: Operation-specific parameters.
            context: Platform context (run_id, workflow_id, agent_role, module_name, work_id).
            preferred_provider: Optional provider preference.
            timeout_seconds: Optional execution timeout.

        Returns:
            ConnectorInvocationResult with status, payload, cost info, and metadata.

        Raises:
            ConnectorServiceError: If capability_type is an invalid string value.
        """
        capability_type = self._resolve_capability_type(capability_type)

        request = ConnectorInvocationRequest(
            capability_type=capability_type,
            operation=operation,
            parameters=parameters,
            context=context or {},
            preferred_provider=preferred_provider,
            timeout_seconds=timeout_seconds,
        )

        logger.debug(
            "Connector invocation: capability=%s op=%s request_id=%s",
            capability_type.value,
            operation,
            request.request_id,
        )

        access_result = self._check_config_access(
            capability_type,
            context=context or {},
            request_id=request.request_id,
            operation=operation,
        )
        if access_result is not None:
            self._maybe_audit(request, access_result)
            return access_result

        policies = self._collect_policies(capability_type, context=context or {})
        perm = evaluate_permission_detailed(request, policies)
        if perm.outcome == PermissionOutcome.DENY:
            result = ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id="platform",
                provider="platform",
                capability_type=capability_type,
                operation=operation,
                status=ConnectorStatus.PERMISSION_DENIED,
                error_message=f"Denied by policy: {perm.reason}",
            )
            self._maybe_audit(request, result)
            return result

        if perm.outcome == PermissionOutcome.REQUIRES_APPROVAL:
            result = ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id="platform",
                provider="platform",
                capability_type=capability_type,
                operation=operation,
                status=ConnectorStatus.REQUIRES_APPROVAL,
                error_message=f"Requires approval: {perm.reason}",
            )
            self._maybe_audit(request, result)
            return result

        self._validate_input_contract(capability_type, operation, parameters, context or {})

        provider = self._registry.find_provider_for_operation(
            capability_type, operation, preferred_provider
        )
        if provider is None:
            result = ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id="platform",
                provider="platform",
                capability_type=capability_type,
                operation=operation,
                status=ConnectorStatus.UNAVAILABLE,
                error_message=(
                    f"No provider available for capability_type={capability_type.value}"
                ),
            )
            self._maybe_audit(request, result)
            return result

        retry_policy = self._get_retry_policy(capability_type)
        result = await self._executor.execute(provider, request, retry_policy)
        self._maybe_audit(request, result)

        if result.payload is not None:
            self._validate_output_contract(
                capability_type, operation, result.payload, context or {}
            )

        return result

    def wrap_result_as_artifact(
        self,
        result: ConnectorInvocationResult,
        resource_type: str,
        provenance: dict | None = None,
    ) -> ExternalArtifact:
        """Wrap a ConnectorInvocationResult in a domain-agnostic ExternalArtifact.

        Domain modules may transform this further into domain-specific artifacts.

        Args:
            result: The invocation result to wrap.
            resource_type: Logical type label for the resource (e.g. "document").
            provenance: Additional provenance metadata to include.

        Returns:
            ExternalArtifact containing the result payload and provenance.
        """
        return ExternalArtifact(
            source_connector=result.connector_id,
            provider=result.provider,
            capability_type=result.capability_type,
            resource_type=resource_type,
            raw_payload=result.payload,
            provenance={
                "request_id": result.request_id,
                "operation": result.operation,
                "status": result.status.value,
                **(provenance or {}),
            },
        )

    def list_available_capabilities(self) -> list[CapabilityType]:
        """Return all capability types for which providers are registered."""
        capabilities: set[CapabilityType] = set()
        for descriptor in self._registry.list_providers():
            capabilities.update(descriptor.capability_types)
        return sorted(capabilities, key=lambda c: c.value)

    def list_providers(self):
        """Return descriptors for all registered providers."""
        return self._registry.list_providers()

    def get_traces(
        self,
        run_id: str | None = None,
        connector_id: str | None = None,
        capability_type: CapabilityType | None = None,
        limit: int = 100,
    ) -> list[ConnectorExecutionTrace]:
        """Query connector execution traces.

        Args:
            run_id: Filter by run ID.
            connector_id: Filter by connector ID.
            capability_type: Filter by capability type.
            limit: Maximum number of results.

        Returns:
            List of matching traces, newest first.
        """
        return self._trace_store.query(
            run_id=run_id,
            connector_id=connector_id,
            capability_type=capability_type,
            limit=limit,
        )

    def get_trace_summary(self) -> dict:
        """Return aggregated summary of connector execution traces."""
        return self._trace_store.get_summary()

    def get_configs(self) -> list[ConnectorConfig]:
        """Return all registered connector configurations."""
        return self._registry.list_configs()

    def get_connector_auth_config(self, connector_id: str) -> dict | None:
        """Return auth config for a connector (no credentials — config metadata only).

        Args:
            connector_id: The connector ID to look up.

        Returns:
            Auth config dict or None if connector not found or has no auth config.
        """
        config = self._registry.get_config(connector_id)
        if config is None:
            return None
        return config.auth_config

    def _resolve_capability_type(
        self, capability_type: CapabilityType | str
    ) -> CapabilityType:
        """Normalize capability_type to a CapabilityType enum value.

        Raises:
            ConnectorServiceError: If the string value is not a valid CapabilityType.
        """
        if isinstance(capability_type, CapabilityType):
            return capability_type
        try:
            return CapabilityType(capability_type)
        except ValueError as exc:
            raise ConnectorServiceError(
                f"Unknown capability_type: {capability_type!r}. "
                f"Valid types: {[c.value for c in CapabilityType]}"
            ) from exc

    def _check_config_access(
        self,
        capability_type: CapabilityType,
        context: dict,
        request_id: str,
        operation: str,
    ) -> "ConnectorInvocationResult | None":
        """Check connector config-level access (enabled + scoping) before policy evaluation.

        Returns a terminal ConnectorInvocationResult if access is blocked, or None
        if execution should proceed.  Three cases:

        1. No configs registered for this capability → None (allow; policy-free execution)
        2. All matching configs disabled → UNAVAILABLE
        3. Scoped configs exist but none match module/role → PERMISSION_DENIED
        """
        configs = [
            c for c in self._registry.list_configs()
            if c.capability_type == capability_type
        ]
        if not configs:
            return None

        enabled_configs = [c for c in configs if c.enabled]
        if not enabled_configs:
            return ConnectorInvocationResult(
                request_id=request_id,
                connector_id="platform",
                provider="platform",
                capability_type=capability_type,
                operation=operation,
                status=ConnectorStatus.UNAVAILABLE,
                error_message=(
                    f"All connectors for capability_type={capability_type.value} are disabled"
                ),
            )

        module_name: str | None = context.get("module_name") or None
        agent_role: str | None = context.get("agent_role") or None

        accessible = []
        for c in enabled_configs:
            if c.scoped_modules and module_name not in c.scoped_modules:
                continue
            if c.scoped_agent_roles and agent_role not in c.scoped_agent_roles:
                continue
            accessible.append(c)

        if not accessible:
            return ConnectorInvocationResult(
                request_id=request_id,
                connector_id="platform",
                provider="platform",
                capability_type=capability_type,
                operation=operation,
                status=ConnectorStatus.PERMISSION_DENIED,
                error_message=(
                    f"No connector config accessible for module_name={module_name!r} "
                    f"agent_role={agent_role!r} capability_type={capability_type.value}"
                ),
            )

        return None

    def _collect_policies(self, capability_type: CapabilityType, context: dict | None = None):
        """Collect permission policies applicable to the given capability type and context."""
        ctx = context or {}
        module_name: str | None = ctx.get("module_name") or None
        agent_role: str | None = ctx.get("agent_role") or None
        policies = []
        for config in self._registry.list_configs():
            if config.capability_type != capability_type or not config.enabled:
                continue
            if config.scoped_modules and module_name not in config.scoped_modules:
                continue
            if config.scoped_agent_roles and agent_role not in config.scoped_agent_roles:
                continue
            policies.extend(config.permission_policies)
        return policies

    def _get_retry_policy(
        self, capability_type: CapabilityType
    ) -> ConnectorRetryPolicy | None:
        """Retrieve retry policy from the matching ConnectorConfig, if configured."""
        for config in self._registry.list_configs():
            if config.capability_type == capability_type and config.enabled:
                return config.retry_policy
        return None

    def _validate_input_contract(
        self,
        capability_type: CapabilityType,
        operation: str,
        parameters: dict,
        context: dict,
    ) -> None:
        """Validate connector input parameters against the capability contract, if registered."""
        if self._contract_validator is None:
            return
        try:
            self._contract_validator.validate_capability_input(
                capability_type.value, operation, parameters, context
            )
        except Exception:
            logger.warning("Contract input validation error", exc_info=True)

    def _validate_output_contract(
        self,
        capability_type: CapabilityType,
        operation: str,
        payload: dict,
        context: dict,
    ) -> None:
        """Validate connector output payload against the capability contract, if registered."""
        if self._contract_validator is None:
            return
        try:
            self._contract_validator.validate_capability_output(
                capability_type.value, operation, payload, context
            )
        except Exception:
            logger.warning("Contract output validation error", exc_info=True)

    def _maybe_audit(
        self,
        request: ConnectorInvocationRequest,
        result: ConnectorInvocationResult,
    ) -> None:
        """Emit a connector invocation audit record if an audit logger is configured."""
        if self._audit_logger is None:
            return
        try:
            from .audit import log_connector_invocation
            log_connector_invocation(self._audit_logger, request, result)
        except Exception:
            logger.warning("Failed to audit connector invocation", exc_info=True)
