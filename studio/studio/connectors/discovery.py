"""Connector discovery by querying the runtime API.

Studio queries ``GET /api/v1/connectors/providers`` on the running
Agent-Orchestrator instance to discover available connector providers,
their capabilities, operations, and parameter schemas.

Results are normalized into Studio's own ConnectorInfo model so the
frontend doesn't depend on the runtime's response shape.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from studio.config import StudioConfig
from studio.exceptions import ConnectorDiscoveryError

logger = logging.getLogger(__name__)

PROVIDERS_ENDPOINT = "/api/v1/connectors/providers"
CAPABILITIES_ENDPOINT = "/api/v1/connectors/capabilities"
REQUEST_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class OperationInfo:
    """A single operation a connector provider supports.

    Attributes:
        operation: Operation name (e.g. ``search``, ``send_message``).
        description: What this operation does.
        capability_type: Category (e.g. ``SEARCH``, ``MESSAGING``).
        read_only: Whether the operation only reads data.
        required_parameters: Parameters that must be provided.
        optional_parameters: Parameters that may be provided.
    """

    operation: str
    description: str
    capability_type: str
    read_only: bool
    required_parameters: list[str]
    optional_parameters: list[str]


@dataclass(frozen=True)
class ConnectorInfo:
    """Normalized view of a connector provider.

    Attributes:
        provider_id: Unique provider identifier.
        display_name: Human-readable name.
        capability_types: List of capability type strings.
        operations: Available operations.
        enabled: Whether the provider is enabled.
        auth_required: Whether authentication is needed.
        auth_type: Authentication mechanism (e.g. ``api_key``, ``oauth``).
        parameter_schemas: JSON Schema for provider parameters.
    """

    provider_id: str
    display_name: str
    capability_types: list[str]
    operations: list[OperationInfo]
    enabled: bool
    auth_required: bool
    auth_type: str = "none"
    parameter_schemas: dict[str, Any] = field(default_factory=dict)


def _parse_operation(data: dict[str, Any]) -> OperationInfo:
    """Parse a single operation descriptor from the runtime response."""
    return OperationInfo(
        operation=data.get("operation", ""),
        description=data.get("description", ""),
        capability_type=data.get("capability_type", ""),
        read_only=data.get("read_only", True),
        required_parameters=data.get("required_parameters", []),
        optional_parameters=data.get("optional_parameters", []),
    )


def _parse_provider(data: dict[str, Any]) -> ConnectorInfo:
    """Parse a provider descriptor from the runtime response."""
    operations = [_parse_operation(op) for op in data.get("operations", [])]
    return ConnectorInfo(
        provider_id=data.get("provider_id", ""),
        display_name=data.get("display_name", ""),
        capability_types=data.get("capability_types", []),
        operations=operations,
        enabled=data.get("enabled", True),
        auth_required=data.get("auth_required", False),
        auth_type=data.get("auth_type", "none"),
        parameter_schemas=data.get("parameter_schemas", {}),
    )


def discover_connectors(config: StudioConfig) -> list[ConnectorInfo]:
    """Query the runtime API for available connector providers.

    Args:
        config: Studio configuration containing the runtime API URL.

    Returns:
        List of ConnectorInfo objects describing available providers.

    Raises:
        ConnectorDiscoveryError: If the runtime is unreachable or returns an error.
    """
    url = f"{config.runtime_api_url}{PROVIDERS_ENDPOINT}"
    logger.info("Discovering connectors from %s", url)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.ConnectError as exc:
        raise ConnectorDiscoveryError(
            f"Cannot connect to runtime at {config.runtime_api_url}: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ConnectorDiscoveryError(
            f"Runtime returned HTTP {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ConnectorDiscoveryError(
            f"Timeout connecting to runtime at {config.runtime_api_url}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise ConnectorDiscoveryError(
            f"Runtime returned invalid JSON: {exc}"
        ) from exc

    # Response may be a list directly or wrapped in a key
    providers_list: list[dict[str, Any]]
    if isinstance(data, list):
        providers_list = data
    elif isinstance(data, dict) and "providers" in data:
        providers_list = data["providers"]
    else:
        providers_list = []

    connectors = [_parse_provider(p) for p in providers_list]
    logger.info("Discovered %d connector providers", len(connectors))
    return connectors


def discover_capabilities(config: StudioConfig) -> list[str]:
    """Query the runtime for available capability types.

    Args:
        config: Studio configuration.

    Returns:
        List of capability type strings.

    Raises:
        ConnectorDiscoveryError: If the query fails.
    """
    url = f"{config.runtime_api_url}{CAPABILITIES_ENDPOINT}"
    logger.info("Discovering capabilities from %s", url)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.get(url)
            response.raise_for_status()
    except (httpx.ConnectError, httpx.HTTPStatusError, httpx.TimeoutException) as exc:
        raise ConnectorDiscoveryError(
            f"Failed to discover capabilities: {exc}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise ConnectorDiscoveryError(f"Invalid JSON response: {exc}") from exc

    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "capabilities" in data:
        return data["capabilities"]
    return []
