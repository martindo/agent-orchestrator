"""MCP-to-Connector Bridge — wraps MCP tools as ConnectorProviderProtocol.

Each discovered MCP tool becomes a ConnectorProviderProtocol implementor
registered in ConnectorRegistry. This gives MCP tools the same permission
checks, contract validation, and audit logging as native connectors.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorStatus,
)
from agent_orchestrator.mcp.exceptions import MCPToolCallError
from agent_orchestrator.mcp.models import MCPClientConfig, MCPToolInfo

if TYPE_CHECKING:
    from agent_orchestrator.connectors.registry import ConnectorRegistry
    from agent_orchestrator.mcp.client_manager import MCPClientManager

logger = logging.getLogger(__name__)


def _resolve_capability_type(
    tool: MCPToolInfo, config: MCPClientConfig, server_override: str | None,
) -> CapabilityType:
    """Determine CapabilityType for an MCP tool.

    Priority: server-level override > config default > EXTERNAL_API.
    """
    override = server_override or config.default_capability_type
    try:
        return CapabilityType(override)
    except ValueError:
        logger.warning(
            "Invalid capability_type '%s' for MCP tool '%s', falling back to EXTERNAL_API",
            override, tool.name,
        )
        return CapabilityType.EXTERNAL_API


def _extract_parameters(input_schema: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Extract required and optional parameter names from JSON Schema."""
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    required_params = sorted(p for p in properties if p in required)
    optional_params = sorted(p for p in properties if p not in required)
    return required_params, optional_params


class MCPToolConnectorProvider:
    """Wraps a single MCP tool as a ConnectorProviderProtocol implementor.

    One provider per tool gives fine-grained governance: each tool can be
    individually enabled/disabled via connector configs.
    """

    def __init__(
        self,
        tool: MCPToolInfo,
        client_manager: "MCPClientManager",
        capability_type: CapabilityType,
        tool_prefix: str = "mcp",
    ) -> None:
        self._tool = tool
        self._client_manager = client_manager
        self._capability_type = capability_type
        self._provider_id = f"{tool_prefix}.{tool.server_id}.{tool.name}"
        required, optional = _extract_parameters(tool.input_schema)
        self._required_params = required
        self._optional_params = optional

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return descriptor for this MCP tool."""
        return ConnectorProviderDescriptor(
            provider_id=self._provider_id,
            display_name=f"MCP: {self._tool.server_id}/{self._tool.name}",
            capability_types=[self._capability_type],
            operations=[
                ConnectorOperationDescriptor(
                    operation=self._tool.name,
                    description=self._tool.description,
                    capability_type=self._capability_type,
                    read_only=False,
                    required_parameters=self._required_params,
                    optional_parameters=self._optional_params,
                ),
            ],
            enabled=True,
            metadata={
                "mcp_server_id": self._tool.server_id,
                "mcp_tool_name": self._tool.name,
                "mcp_input_schema": self._tool.input_schema,
            },
            parameter_schemas=self._tool.input_schema,
        )

    async def execute(
        self, request: ConnectorInvocationRequest,
    ) -> ConnectorInvocationResult:
        """Execute this MCP tool via the client manager."""
        start = time.monotonic()
        try:
            result = await self._client_manager.call_tool(
                self._tool.server_id,
                self._tool.name,
                request.parameters,
            )
            duration_ms = (time.monotonic() - start) * 1000
            is_error = result.get("isError", False)
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self._provider_id,
                provider=self._provider_id,
                capability_type=self._capability_type,
                operation=self._tool.name,
                status=ConnectorStatus.FAILURE if is_error else ConnectorStatus.SUCCESS,
                payload=result,
                duration_ms=duration_ms,
                metadata={"mcp_server_id": self._tool.server_id},
            )
        except MCPToolCallError as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self._provider_id,
                provider=self._provider_id,
                capability_type=self._capability_type,
                operation=self._tool.name,
                status=ConnectorStatus.FAILURE,
                error_message=str(exc),
                duration_ms=duration_ms,
                metadata={"mcp_server_id": self._tool.server_id},
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self._provider_id,
                provider=self._provider_id,
                capability_type=self._capability_type,
                operation=self._tool.name,
                status=ConnectorStatus.UNAVAILABLE,
                error_message=f"Unexpected error: {exc}",
                duration_ms=duration_ms,
                metadata={"mcp_server_id": self._tool.server_id},
            )


class MCPConnectorBridge:
    """Orchestrates discovery and registration of MCP tools as connectors.

    For each connected MCP server, discovers tools, creates one
    MCPToolConnectorProvider per tool, and registers them in the
    ConnectorRegistry.
    """

    def __init__(
        self,
        client_manager: "MCPClientManager",
        registry: "ConnectorRegistry",
        config: MCPClientConfig,
    ) -> None:
        self._client_manager = client_manager
        self._registry = registry
        self._config = config
        self._registered_providers: dict[str, list[str]] = {}  # server_id -> [provider_ids]

    async def register_all_tools(self) -> dict[str, int]:
        """Discover and register tools from all connected servers.

        Returns:
            Dict mapping server_id to count of registered tools.
        """
        results: dict[str, int] = {}
        for server_id in self._client_manager.connected_servers:
            count = await self.register_server_tools(server_id)
            results[server_id] = count
        return results

    async def register_server_tools(self, server_id: str) -> int:
        """Discover and register tools from a single server.

        Args:
            server_id: ID of the connected MCP server.

        Returns:
            Number of tools registered.
        """
        # Find capability_type override for this server
        server_config = None
        for sc in self._config.servers:
            if sc.server_id == server_id:
                server_config = sc
                break

        capability_override = server_config.capability_type_override if server_config else None

        tools = await self._client_manager.discover_tools(server_id)
        provider_ids: list[str] = []

        for tool in tools:
            capability_type = _resolve_capability_type(tool, self._config, capability_override)
            provider = MCPToolConnectorProvider(
                tool=tool,
                client_manager=self._client_manager,
                capability_type=capability_type,
                tool_prefix=self._config.tool_prefix,
            )
            self._registry.register_provider(provider)
            provider_ids.append(provider.get_descriptor().provider_id)

        self._registered_providers[server_id] = provider_ids
        logger.info(
            "Registered %d MCP tools from '%s' as connector providers",
            len(provider_ids), server_id,
        )
        return len(provider_ids)

    def unregister_server_tools(self, server_id: str) -> int:
        """Remove all providers registered for a server.

        Args:
            server_id: ID of the MCP server.

        Returns:
            Number of providers unregistered.
        """
        provider_ids = self._registered_providers.pop(server_id, [])
        for pid in provider_ids:
            self._registry.unregister_provider(pid)
        if provider_ids:
            logger.info("Unregistered %d MCP providers for '%s'", len(provider_ids), server_id)
        return len(provider_ids)

    async def refresh_server(self, server_id: str) -> int:
        """Re-discover and update tools for a server.

        Args:
            server_id: ID of the MCP server.

        Returns:
            Number of tools after refresh.
        """
        self.unregister_server_tools(server_id)
        return await self.register_server_tools(server_id)

    def list_registered_providers(self) -> dict[str, list[str]]:
        """Return mapping of server_id to registered provider IDs."""
        return dict(self._registered_providers)
