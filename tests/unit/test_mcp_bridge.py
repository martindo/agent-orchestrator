"""Tests for MCP-to-Connector Bridge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorStatus,
)
from agent_orchestrator.connectors.registry import ConnectorRegistry
from agent_orchestrator.mcp.bridge import (
    MCPConnectorBridge,
    MCPToolConnectorProvider,
    _extract_parameters,
    _resolve_capability_type,
)
from agent_orchestrator.mcp.models import MCPClientConfig, MCPServerConfig, MCPToolInfo, MCPTransportType


def _make_tool(
    name: str = "test_tool",
    server_id: str = "srv",
    input_schema: dict | None = None,
) -> MCPToolInfo:
    return MCPToolInfo(
        server_id=server_id,
        name=name,
        description=f"Tool {name}",
        input_schema=input_schema or {},
    )


class TestExtractParameters:
    def test_empty_schema(self) -> None:
        req, opt = _extract_parameters({})
        assert req == []
        assert opt == []

    def test_with_required(self) -> None:
        schema = {
            "properties": {"a": {}, "b": {}, "c": {}},
            "required": ["a", "c"],
        }
        req, opt = _extract_parameters(schema)
        assert req == ["a", "c"]
        assert opt == ["b"]

    def test_all_optional(self) -> None:
        schema = {"properties": {"x": {}, "y": {}}}
        req, opt = _extract_parameters(schema)
        assert req == []
        assert opt == ["x", "y"]


class TestResolveCapabilityType:
    def test_valid_override(self) -> None:
        tool = _make_tool()
        config = MCPClientConfig(default_capability_type="external_api")
        result = _resolve_capability_type(tool, config, "repository")
        assert result == CapabilityType.REPOSITORY

    def test_config_default(self) -> None:
        tool = _make_tool()
        config = MCPClientConfig(default_capability_type="search")
        result = _resolve_capability_type(tool, config, None)
        assert result == CapabilityType.SEARCH

    def test_invalid_falls_back(self) -> None:
        tool = _make_tool()
        config = MCPClientConfig(default_capability_type="invalid_type")
        result = _resolve_capability_type(tool, config, None)
        assert result == CapabilityType.EXTERNAL_API


class TestMCPToolConnectorProvider:
    def test_get_descriptor(self) -> None:
        tool = _make_tool(
            input_schema={
                "properties": {"query": {}, "limit": {}},
                "required": ["query"],
            },
        )
        mock_client = MagicMock()
        provider = MCPToolConnectorProvider(
            tool=tool,
            client_manager=mock_client,
            capability_type=CapabilityType.SEARCH,
            tool_prefix="mcp",
        )
        desc = provider.get_descriptor()
        assert desc.provider_id == "mcp.srv.test_tool"
        assert CapabilityType.SEARCH in desc.capability_types
        assert len(desc.operations) == 1
        assert desc.operations[0].operation == "test_tool"
        assert desc.operations[0].required_parameters == ["query"]
        assert desc.operations[0].optional_parameters == ["limit"]

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        tool = _make_tool()
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "hello"}],
            "isError": False,
        })

        provider = MCPToolConnectorProvider(
            tool=tool,
            client_manager=mock_client,
            capability_type=CapabilityType.EXTERNAL_API,
        )

        from agent_orchestrator.connectors.models import ConnectorInvocationRequest
        request = ConnectorInvocationRequest(
            capability_type=CapabilityType.EXTERNAL_API,
            operation="test_tool",
            parameters={"key": "value"},
        )
        result = await provider.execute(request)
        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload is not None
        assert result.duration_ms is not None
        mock_client.call_tool.assert_called_once_with("srv", "test_tool", {"key": "value"})

    @pytest.mark.asyncio
    async def test_execute_error(self) -> None:
        tool = _make_tool()
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={
            "content": [],
            "isError": True,
        })

        provider = MCPToolConnectorProvider(
            tool=tool,
            client_manager=mock_client,
            capability_type=CapabilityType.EXTERNAL_API,
        )

        from agent_orchestrator.connectors.models import ConnectorInvocationRequest
        request = ConnectorInvocationRequest(
            capability_type=CapabilityType.EXTERNAL_API,
            operation="test_tool",
            parameters={},
        )
        result = await provider.execute(request)
        assert result.status == ConnectorStatus.FAILURE

    @pytest.mark.asyncio
    async def test_execute_exception(self) -> None:
        from agent_orchestrator.mcp.exceptions import MCPToolCallError
        tool = _make_tool()
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=MCPToolCallError("fail"))

        provider = MCPToolConnectorProvider(
            tool=tool,
            client_manager=mock_client,
            capability_type=CapabilityType.EXTERNAL_API,
        )

        from agent_orchestrator.connectors.models import ConnectorInvocationRequest
        request = ConnectorInvocationRequest(
            capability_type=CapabilityType.EXTERNAL_API,
            operation="test_tool",
            parameters={},
        )
        result = await provider.execute(request)
        assert result.status == ConnectorStatus.FAILURE
        assert "fail" in result.error_message


class TestMCPConnectorBridge:
    @pytest.mark.asyncio
    async def test_register_all_tools(self) -> None:
        mock_client = AsyncMock()
        mock_client.connected_servers = ["srv"]
        mock_client.discover_tools = AsyncMock(return_value=[
            _make_tool("tool_a"),
            _make_tool("tool_b"),
        ])

        registry = ConnectorRegistry()
        config = MCPClientConfig(
            servers=[MCPServerConfig(
                server_id="srv",
                display_name="Server",
                transport=MCPTransportType.STDIO,
            )],
        )

        bridge = MCPConnectorBridge(mock_client, registry, config)
        results = await bridge.register_all_tools()

        assert results == {"srv": 2}
        providers = registry.list_providers()
        assert len(providers) == 2

    @pytest.mark.asyncio
    async def test_unregister_server_tools(self) -> None:
        mock_client = AsyncMock()
        mock_client.connected_servers = ["srv"]
        mock_client.discover_tools = AsyncMock(return_value=[_make_tool("t1")])

        registry = ConnectorRegistry()
        config = MCPClientConfig(
            servers=[MCPServerConfig(
                server_id="srv",
                display_name="S",
                transport=MCPTransportType.STDIO,
            )],
        )

        bridge = MCPConnectorBridge(mock_client, registry, config)
        await bridge.register_all_tools()
        assert len(registry.list_providers()) == 1

        count = bridge.unregister_server_tools("srv")
        assert count == 1
        assert len(registry.list_providers()) == 0

    def test_list_registered_providers_empty(self) -> None:
        mock_client = MagicMock()
        bridge = MCPConnectorBridge(mock_client, ConnectorRegistry(), MCPClientConfig())
        assert bridge.list_registered_providers() == {}

    @pytest.mark.asyncio
    async def test_refresh_server(self) -> None:
        mock_client = AsyncMock()
        mock_client.connected_servers = ["srv"]
        mock_client.discover_tools = AsyncMock(return_value=[_make_tool("new_tool")])

        registry = ConnectorRegistry()
        config = MCPClientConfig(
            servers=[MCPServerConfig(
                server_id="srv",
                display_name="S",
                transport=MCPTransportType.STDIO,
            )],
        )

        bridge = MCPConnectorBridge(mock_client, registry, config)
        # First register old tools
        bridge._registered_providers["srv"] = ["old_provider"]
        # Refresh replaces
        count = await bridge.refresh_server("srv")
        assert count == 1
        assert "srv" in bridge.list_registered_providers()
