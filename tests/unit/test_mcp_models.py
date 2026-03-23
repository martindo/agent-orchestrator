"""Tests for MCP Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_orchestrator.mcp.models import (
    MCPClientConfig,
    MCPProfileConfig,
    MCPPromptInfo,
    MCPResourceInfo,
    MCPServerConfig,
    MCPServerHostConfig,
    MCPSessionInfo,
    MCPToolInfo,
    MCPTransportType,
)


class TestMCPTransportType:
    def test_enum_values(self) -> None:
        assert MCPTransportType.STDIO == "stdio"
        assert MCPTransportType.STREAMABLE_HTTP == "streamable_http"
        assert MCPTransportType.SSE == "sse"


class TestMCPServerConfig:
    def test_minimal_stdio(self) -> None:
        config = MCPServerConfig(
            server_id="test",
            display_name="Test Server",
            transport=MCPTransportType.STDIO,
            command="npx",
            args=["-y", "test-server"],
        )
        assert config.server_id == "test"
        assert config.transport == MCPTransportType.STDIO
        assert config.command == "npx"
        assert config.auto_connect is True
        assert config.enabled is True
        assert config.url is None

    def test_http_config(self) -> None:
        config = MCPServerConfig(
            server_id="api",
            display_name="API Server",
            transport=MCPTransportType.STREAMABLE_HTTP,
            url="http://localhost:8080/mcp",
            headers={"X-Custom": "value"},
        )
        assert config.url == "http://localhost:8080/mcp"
        assert config.headers == {"X-Custom": "value"}
        assert config.command is None

    def test_env_vars(self) -> None:
        config = MCPServerConfig(
            server_id="gh",
            display_name="GitHub",
            transport=MCPTransportType.STDIO,
            command="npx",
            env={"TOKEN": "${GITHUB_TOKEN}"},
        )
        assert config.env == {"TOKEN": "${GITHUB_TOKEN}"}

    def test_frozen(self) -> None:
        config = MCPServerConfig(
            server_id="test",
            display_name="Test",
            transport=MCPTransportType.STDIO,
        )
        with pytest.raises(ValidationError):
            config.server_id = "changed"

    def test_capability_override(self) -> None:
        config = MCPServerConfig(
            server_id="repo",
            display_name="Repo Server",
            transport=MCPTransportType.STDIO,
            capability_type_override="repository",
        )
        assert config.capability_type_override == "repository"


class TestMCPClientConfig:
    def test_defaults(self) -> None:
        config = MCPClientConfig()
        assert config.servers == []
        assert config.default_capability_type == "external_api"
        assert config.tool_prefix == "mcp"

    def test_with_servers(self) -> None:
        server = MCPServerConfig(
            server_id="s1",
            display_name="S1",
            transport=MCPTransportType.STDIO,
        )
        config = MCPClientConfig(servers=[server])
        assert len(config.servers) == 1
        assert config.servers[0].server_id == "s1"


class TestMCPServerHostConfig:
    def test_defaults(self) -> None:
        config = MCPServerHostConfig()
        assert config.enabled is False
        assert config.mount_path == "/mcp"
        assert config.session_ttl_seconds == 3600
        assert config.max_sessions == 100
        assert config.audit_all_invocations is True

    def test_enabled(self) -> None:
        config = MCPServerHostConfig(enabled=True, mount_path="/custom-mcp")
        assert config.enabled is True
        assert config.mount_path == "/custom-mcp"


class TestMCPProfileConfig:
    def test_defaults(self) -> None:
        config = MCPProfileConfig()
        assert config.client.servers == []
        assert config.server.enabled is False

    def test_full_config(self) -> None:
        config = MCPProfileConfig(
            client=MCPClientConfig(
                servers=[
                    MCPServerConfig(
                        server_id="gh",
                        display_name="GitHub",
                        transport=MCPTransportType.STDIO,
                        command="npx",
                    ),
                ],
            ),
            server=MCPServerHostConfig(enabled=True),
        )
        assert len(config.client.servers) == 1
        assert config.server.enabled is True


class TestMCPToolInfo:
    def test_creation(self) -> None:
        tool = MCPToolInfo(
            server_id="test",
            name="list_repos",
            description="List repositories",
            input_schema={
                "type": "object",
                "properties": {"org": {"type": "string"}},
                "required": ["org"],
            },
        )
        assert tool.name == "list_repos"
        assert "org" in tool.input_schema["properties"]

    def test_defaults(self) -> None:
        tool = MCPToolInfo(server_id="s", name="t")
        assert tool.description == ""
        assert tool.input_schema == {}


class TestMCPResourceInfo:
    def test_creation(self) -> None:
        res = MCPResourceInfo(
            server_id="test",
            uri="file:///tmp/data.json",
            name="data",
            mime_type="application/json",
        )
        assert res.uri == "file:///tmp/data.json"
        assert res.mime_type == "application/json"


class TestMCPPromptInfo:
    def test_creation(self) -> None:
        prompt = MCPPromptInfo(
            server_id="test",
            name="code_review",
            description="Code review prompt",
            arguments=[{"name": "language", "required": True}],
        )
        assert prompt.name == "code_review"
        assert len(prompt.arguments) == 1


class TestMCPSessionInfo:
    def test_defaults(self) -> None:
        session = MCPSessionInfo(server_id="test")
        assert session.connected is False
        assert session.tools == []
        assert session.resources == []
        assert session.prompts == []

    def test_with_tools(self) -> None:
        tool = MCPToolInfo(server_id="test", name="search")
        session = MCPSessionInfo(
            server_id="test",
            connected=True,
            tools=[tool],
        )
        assert session.connected is True
        assert len(session.tools) == 1
