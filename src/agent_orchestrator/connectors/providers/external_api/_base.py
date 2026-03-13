"""Shared base for external_api capability connector providers."""
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

logger = logging.getLogger(__name__)

_EXTERNAL_API_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="get",
        description="HTTP GET request to the configured API",
        capability_type=CapabilityType.EXTERNAL_API,
        read_only=True,
        required_parameters=["path"],
        optional_parameters=["headers", "params"],
    ),
    ConnectorOperationDescriptor(
        operation="post",
        description="HTTP POST request to the configured API",
        capability_type=CapabilityType.EXTERNAL_API,
        read_only=False,
        required_parameters=["path", "body"],
        optional_parameters=["headers", "params"],
    ),
    ConnectorOperationDescriptor(
        operation="put",
        description="HTTP PUT request to the configured API",
        capability_type=CapabilityType.EXTERNAL_API,
        read_only=False,
        required_parameters=["path", "body"],
        optional_parameters=["headers", "params"],
    ),
    ConnectorOperationDescriptor(
        operation="patch",
        description="HTTP PATCH request to the configured API",
        capability_type=CapabilityType.EXTERNAL_API,
        read_only=False,
        required_parameters=["path", "body"],
        optional_parameters=["headers", "params"],
    ),
    ConnectorOperationDescriptor(
        operation="delete",
        description="HTTP DELETE request to the configured API",
        capability_type=CapabilityType.EXTERNAL_API,
        read_only=False,
        required_parameters=["path"],
        optional_parameters=["headers", "params"],
    ),
]


class ExternalApiProviderError(Exception):
    """Raised when an external API provider encounters an unrecoverable error."""


class BaseExternalApiProvider(ABC):
    """Abstract base with common execute() dispatch for external API providers.

    Subclasses implement _make_request(); dispatch routing is handled here.
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.EXTERNAL_API],
            operations=_EXTERNAL_API_OPS,
            enabled=self.is_available(),
            auth_required=False,
            auth_type="custom",
            version="1.0",
        )

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    def is_available(self) -> bool:
        """Return True if the provider has a base URL configured."""
        return bool(getattr(self, "_base_url", None))

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
        except ExternalApiProviderError as exc:
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
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Route operation name to _make_request with extracted parameters.

        Args:
            op: Operation name (get, post, put, patch, delete).
            params: Raw parameters dict from the invocation request.

        Returns:
            Tuple of (payload dict, optional cost info).

        Raises:
            ExternalApiProviderError: For unknown operations.
        """
        path: str = params["path"]
        body: dict | None = params.get("body")
        headers: dict | None = params.get("headers")
        request_params: dict | None = params.get("params")

        if op in ("get", "post", "put", "patch", "delete"):
            return await self._make_request(
                method=op.upper(),
                path=path,
                body=body,
                headers=headers,
                params=request_params,
            )

        raise ExternalApiProviderError(f"Unknown operation: {op!r}")

    @abstractmethod
    async def _make_request(
        self,
        method: str,
        path: str,
        body: dict | None,
        headers: dict | None,
        params: dict | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @staticmethod
    def _make_response_artifact(
        provider: str,
        connector_id: str,
        method: str,
        path: str,
        status_code: int,
        response_body: dict | str,
        response_headers: dict,
        raw_payload: dict,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap an HTTP response in a platform-standard ExternalArtifact.

        Raw API responses are too varied to normalize, so normalized_payload
        is always None. The raw_payload captures the full request/response context.

        Args:
            provider: Provider ID string.
            connector_id: Connector ID string (typically same as provider).
            method: HTTP method used (GET, POST, etc.).
            path: URL path that was requested.
            status_code: HTTP response status code.
            response_body: Parsed response body (dict or str).
            response_headers: Response headers dict.
            raw_payload: Full raw payload dict for the artifact.
            provenance: Provenance dict (base_url, auth_type, etc.).

        Returns:
            ExternalArtifact with normalized_payload=None and raw_payload set.
        """
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.EXTERNAL_API,
            resource_type="api_response",
            normalized_payload=None,
            raw_payload={
                "method": method,
                "path": path,
                "status_code": status_code,
                "response": response_body,
                "response_headers": response_headers,
            },
            provenance=provenance,
        )
