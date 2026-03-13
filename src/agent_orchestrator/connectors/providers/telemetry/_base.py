"""Shared base for telemetry capability connector providers."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from ...models import (
    CapabilityType,
    ConnectorCostInfo,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorStatus,
    ExternalArtifact,
)
from ...normalized import TelemetryArtifact

logger = logging.getLogger(__name__)

_TELEMETRY_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="query_metrics",
        description="Query time-series metrics using a provider query expression",
        capability_type=CapabilityType.TELEMETRY,
        read_only=True,
        required_parameters=["query"],
        optional_parameters=["start", "end", "step"],
    ),
    ConnectorOperationDescriptor(
        operation="get_logs",
        description="Retrieve log entries matching a filter expression",
        capability_type=CapabilityType.TELEMETRY,
        read_only=True,
        required_parameters=["query"],
        optional_parameters=["start", "end", "limit"],
    ),
    ConnectorOperationDescriptor(
        operation="list_alerts",
        description="List active or configured alerts and monitors",
        capability_type=CapabilityType.TELEMETRY,
        read_only=True,
        required_parameters=[],
        optional_parameters=["state", "limit"],
    ),
    ConnectorOperationDescriptor(
        operation="get_health",
        description="Check the health and connectivity of the telemetry backend",
        capability_type=CapabilityType.TELEMETRY,
        read_only=True,
        required_parameters=[],
        optional_parameters=[],
    ),
]


class TelemetryProviderError(Exception):
    """Raised when a telemetry provider encounters an unrecoverable error."""


class BaseTelemetryProvider(ABC):
    """Abstract base with common execute() dispatch for telemetry providers.

    Subclasses implement _query_metrics(), _get_logs(), _list_alerts(), and
    _get_health(). Each must return a tuple of
    (dict, ConnectorCostInfo | None) where the dict is an ExternalArtifact
    or TelemetryArtifact model_dump().

    All operations are read_only=True; they do not mutate remote state.
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.TELEMETRY],
            operations=_TELEMETRY_OPS,
            enabled=self.is_available(),
            auth_required=True,
            auth_type="api_key",
            version="1.0",
        )

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    def is_available(self) -> bool:
        """Return True if the provider has a non-empty API key configured."""
        return bool(getattr(self, "_api_key", None))

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        """Dispatch the request to the appropriate handler and return a result.

        Args:
            request: Connector invocation request with operation and parameters.

        Returns:
            ConnectorInvocationResult with status, payload, and cost info.
        """
        start = time.monotonic()
        op = request.operation
        params = request.parameters

        try:
            payload, cost_info = await self._dispatch(op, params)
        except TelemetryProviderError as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self.provider_id,
                provider=self.provider_id,
                capability_type=request.capability_type,
                operation=op,
                status=ConnectorStatus.FAILURE,
                error_message=str(exc),
                duration_ms=duration_ms,
            )

        if payload is None:
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self.provider_id,
                provider=self.provider_id,
                capability_type=request.capability_type,
                operation=op,
                status=ConnectorStatus.NOT_FOUND,
                error_message=f"Unknown operation: {op!r}",
            )

        duration_ms = (time.monotonic() - start) * 1000
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id=self.provider_id,
            provider=self.provider_id,
            capability_type=request.capability_type,
            operation=op,
            status=ConnectorStatus.SUCCESS,
            payload=payload,
            cost_info=cost_info,
            duration_ms=duration_ms,
        )

    async def _dispatch(
        self, op: str, params: dict
    ) -> tuple[dict, ConnectorCostInfo | None] | tuple[None, None]:
        """Route an operation name to the corresponding handler method."""
        if op == "query_metrics":
            return await self._query_metrics(
                query=params["query"],
                start=params.get("start"),
                end=params.get("end"),
                step=params.get("step"),
            )
        if op == "get_logs":
            return await self._get_logs(
                query=params["query"],
                start=params.get("start"),
                end=params.get("end"),
                limit=params.get("limit"),
            )
        if op == "list_alerts":
            return await self._list_alerts(
                state=params.get("state"),
                limit=params.get("limit"),
            )
        if op == "get_health":
            return await self._get_health()
        return None, None

    @abstractmethod
    async def _query_metrics(
        self,
        query: str,
        start: str | None,
        end: str | None,
        step: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _get_logs(
        self,
        query: str,
        start: str | None,
        end: str | None,
        limit: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _list_alerts(
        self,
        state: str | None,
        limit: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _get_health(self) -> tuple[dict, ConnectorCostInfo | None]: ...

    @staticmethod
    def _make_metric_artifact(
        provider: str,
        connector_id: str,
        metric_name: str,
        value: float,
        unit: str | None,
        labels: dict[str, str],
        interval_seconds: float | None,
        raw_payload: dict,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap a telemetry metric in a platform-standard ExternalArtifact.

        The normalized_payload contains a TelemetryArtifact-shaped dict.

        Args:
            provider: Provider ID.
            connector_id: Connector ID (typically same as provider).
            metric_name: Name of the metric being reported.
            value: Numeric metric value.
            unit: Optional unit label (e.g. "bytes", "requests/s").
            labels: Key-value label dimensions for the metric.
            interval_seconds: Sampling interval in seconds, or None.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict (provider, query, etc.).

        Returns:
            ExternalArtifact with resource_type "metric" and
            normalized_payload containing TelemetryArtifact fields.
        """
        normalized = TelemetryArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.TELEMETRY,
            metric_name=metric_name,
            value=value,
            unit=unit,
            labels=labels,
            interval_seconds=interval_seconds,
        )
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.TELEMETRY,
            resource_type="metric",
            raw_payload=raw_payload,
            normalized_payload=normalized.model_dump(mode="json"),
            references=[],
            provenance=provenance,
        )

    @staticmethod
    def _make_list_artifact(
        provider: str,
        connector_id: str,
        resource_type: str,
        items: list[dict],
        raw_payload: dict,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap a list of telemetry items in a platform-standard ExternalArtifact.

        The raw_payload holds the provider's original response.
        normalized_payload is omitted because TelemetryArtifact represents a
        single metric, not a list.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            resource_type: Resource type label (e.g. "log_entries", "alerts").
            items: List of item dicts from the provider response.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict.

        Returns:
            ExternalArtifact with the given resource_type and raw_payload only.
        """
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.TELEMETRY,
            resource_type=resource_type,
            raw_payload=raw_payload,
            normalized_payload=None,
            references=[],
            provenance=provenance,
        )
