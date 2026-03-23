"""Tests for MCP Client Manager — mocks the MCP SDK."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_orchestrator.mcp.client_manager import MCPClientManager, _resolve_env_vars
from agent_orchestrator.mcp.exceptions import (
    MCPConfigurationError,
    MCPConnectionError,
    MCPToolCallError,
    MCPResourceError,
)
from agent_orchestrator.mcp.models import (
    MCPClientConfig,
    MCPServerConfig,
    MCPTransportType,
)


def _make_config(*servers: MCPServerConfig) -> MCPClientConfig:
    return MCPClientConfig(servers=list(servers))


def _stdio_server(server_id: str = "test") -> MCPServerConfig:
    return MCPServerConfig(
        server_id=server_id,
        display_name="Test",
        transport=MCPTransportType.STDIO,
        command="echo",
        args=["hello"],
    )


def _http_server(server_id: str = "api") -> MCPServerConfig:
    return MCPServerConfig(
        server_id=server_id,
        display_name="API",
        transport=MCPTransportType.STREAMABLE_HTTP,
        url="http://localhost:8080/mcp",
    )


class TestResolveEnvVars:
    def test_passthrough(self) -> None:
        assert _resolve_env_vars({"KEY": "value"}) == {"KEY": "value"}

    def test_env_reference(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "secret123")
        result = _resolve_env_vars({"TOKEN": "${MY_TOKEN}"})
        assert result == {"TOKEN": "secret123"}

    def test_missing_env(self) -> None:
        result = _resolve_env_vars({"TOKEN": "${NONEXISTENT_VAR_12345}"})
        assert result == {"TOKEN": ""}

    def test_empty(self) -> None:
        assert _resolve_env_vars({}) == {}


class TestMCPClientManagerInit:
    def test_filters_disabled(self) -> None:
        disabled = MCPServerConfig(
            server_id="off",
            display_name="Off",
            transport=MCPTransportType.STDIO,
            enabled=False,
        )
        mgr = MCPClientManager(_make_config(_stdio_server(), disabled))
        assert "test" in mgr._server_configs
        assert "off" not in mgr._server_configs

    def test_empty_config(self) -> None:
        mgr = MCPClientManager(MCPClientConfig())
        assert mgr.connected_servers == []


class TestMCPClientManagerConnect:
    @pytest.mark.asyncio
    async def test_unknown_server_raises(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))
        with patch("agent_orchestrator.mcp.client_manager._check_mcp_sdk"):
            with pytest.raises(MCPConfigurationError, match="not found"):
                await mgr.connect("nonexistent")

    @pytest.mark.asyncio
    async def test_missing_sdk_raises(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))
        with patch.dict("sys.modules", {"mcp": None}):
            with pytest.raises(MCPConfigurationError, match="mcp.*package"):
                await mgr.connect("test")

    @pytest.mark.asyncio
    async def test_stdio_missing_command_raises(self) -> None:
        no_cmd = MCPServerConfig(
            server_id="bad",
            display_name="Bad",
            transport=MCPTransportType.STDIO,
            command=None,
        )
        mgr = MCPClientManager(_make_config(no_cmd))
        # Mock the SDK check to pass
        with patch("agent_orchestrator.mcp.client_manager._check_mcp_sdk"):
            with pytest.raises(MCPConnectionError):
                await mgr.connect("bad")

    @pytest.mark.asyncio
    async def test_http_missing_url_raises(self) -> None:
        no_url = MCPServerConfig(
            server_id="bad",
            display_name="Bad",
            transport=MCPTransportType.STREAMABLE_HTTP,
            url=None,
        )
        mgr = MCPClientManager(_make_config(no_url))
        with patch("agent_orchestrator.mcp.client_manager._check_mcp_sdk"):
            with pytest.raises(MCPConnectionError):
                await mgr.connect("bad")


class TestMCPClientManagerDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_nonexistent(self) -> None:
        """Disconnecting a non-connected server should not raise."""
        mgr = MCPClientManager(_make_config())
        await mgr.disconnect("nonexistent")

    @pytest.mark.asyncio
    async def test_disconnect_cleans_state(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))
        # Simulate a connected session
        mock_session = AsyncMock()
        mock_transport = AsyncMock()
        mgr._sessions["test"] = mock_session
        mgr._transports["test"] = mock_transport

        from agent_orchestrator.mcp.models import MCPSessionInfo
        mgr._session_info["test"] = MCPSessionInfo(server_id="test", connected=True)

        await mgr.disconnect("test")

        assert "test" not in mgr._sessions
        assert "test" not in mgr._transports
        assert "test" not in mgr._session_info


class TestMCPClientManagerToolCall:
    @pytest.mark.asyncio
    async def test_not_connected_raises(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))
        with pytest.raises(MCPConnectionError, match="Not connected"):
            await mgr.call_tool("test", "some_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))

        mock_content = MagicMock()
        mock_content.text = "result text"
        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        mgr._sessions["test"] = mock_session

        result = await mgr.call_tool("test", "my_tool", {"key": "value"})
        assert result["isError"] is False
        assert len(result["content"]) == 1
        assert result["content"][0]["text"] == "result text"

    @pytest.mark.asyncio
    async def test_call_tool_error(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("boom"))
        mgr._sessions["test"] = mock_session

        with pytest.raises(MCPToolCallError, match="boom"):
            await mgr.call_tool("test", "my_tool", {})


class TestMCPClientManagerResource:
    @pytest.mark.asyncio
    async def test_read_resource_not_connected(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))
        with pytest.raises(MCPConnectionError):
            await mgr.read_resource("test", "file:///test")


class TestMCPClientManagerDiscoverTools:
    @pytest.mark.asyncio
    async def test_discover_tools(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))

        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.description = "Search something"
        mock_tool.inputSchema = {"type": "object", "properties": {"q": {"type": "string"}}}

        mock_result = MagicMock()
        mock_result.tools = [mock_tool]

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        mgr._sessions["test"] = mock_session

        from agent_orchestrator.mcp.models import MCPSessionInfo
        mgr._session_info["test"] = MCPSessionInfo(server_id="test", connected=True)

        tools = await mgr.discover_tools("test")
        assert len(tools) == 1
        assert tools[0].name == "search"
        assert tools[0].server_id == "test"

    @pytest.mark.asyncio
    async def test_discover_tools_not_connected(self) -> None:
        mgr = MCPClientManager(_make_config(_stdio_server()))
        with pytest.raises(MCPConnectionError):
            await mgr.discover_tools("test")
