"""Tests for MCP Server creation and tool generation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_orchestrator.mcp.models import MCPServerHostConfig
from agent_orchestrator.mcp.server_session import MCPSessionContext, MCPSessionRegistry


class TestMCPSessionContext:
    def test_creation(self) -> None:
        ctx = MCPSessionContext(session_id="sess-1")
        assert ctx.session_id == "sess-1"
        assert ctx.tool_call_count == 0
        assert ctx.metadata == {}

    def test_touch(self) -> None:
        ctx = MCPSessionContext(session_id="sess-1")
        # Force last_activity to be in the past
        ctx.last_activity = ctx.last_activity - 1.0
        old_activity = ctx.last_activity
        ctx.touch()
        assert ctx.last_activity > old_activity

    def test_expired(self) -> None:
        ctx = MCPSessionContext(session_id="sess-1")
        # Force expiration by setting last_activity far in the past
        ctx.last_activity = ctx.last_activity - 10000
        assert ctx.is_expired(ttl_seconds=1) is True

    def test_not_expired(self) -> None:
        ctx = MCPSessionContext(session_id="sess-1")
        assert ctx.is_expired(ttl_seconds=3600) is False


class TestMCPSessionRegistry:
    def test_create_session(self) -> None:
        reg = MCPSessionRegistry(ttl_seconds=3600, max_sessions=10)
        session = reg.create_session("s1", metadata={"user": "test"})
        assert session.session_id == "s1"
        assert session.metadata == {"user": "test"}

    def test_get_session(self) -> None:
        reg = MCPSessionRegistry()
        reg.create_session("s1")
        session = reg.get_session("s1")
        assert session is not None
        assert session.session_id == "s1"

    def test_get_nonexistent(self) -> None:
        reg = MCPSessionRegistry()
        assert reg.get_session("nope") is None

    def test_remove_session(self) -> None:
        reg = MCPSessionRegistry()
        reg.create_session("s1")
        assert reg.remove_session("s1") is True
        assert reg.remove_session("s1") is False

    def test_max_sessions_exceeded(self) -> None:
        reg = MCPSessionRegistry(max_sessions=2)
        reg.create_session("s1")
        reg.create_session("s2")
        with pytest.raises(ValueError, match="Maximum sessions"):
            reg.create_session("s3")

    def test_expired_session_evicted(self) -> None:
        reg = MCPSessionRegistry(ttl_seconds=0)  # immediate expiry
        reg.create_session("s1")
        import time
        time.sleep(0.01)
        assert reg.get_session("s1") is None

    def test_active_count(self) -> None:
        reg = MCPSessionRegistry()
        reg.create_session("s1")
        reg.create_session("s2")
        assert reg.active_count == 2

    def test_list_sessions(self) -> None:
        reg = MCPSessionRegistry()
        reg.create_session("s1")
        reg.create_session("s2")
        sessions = reg.list_sessions()
        assert len(sessions) == 2


class TestMCPServerHostConfig:
    def test_defaults(self) -> None:
        config = MCPServerHostConfig()
        assert config.enabled is False
        assert config.mount_path == "/mcp"

    def test_custom(self) -> None:
        config = MCPServerHostConfig(
            enabled=True,
            mount_path="/custom",
            session_ttl_seconds=7200,
            max_sessions=50,
        )
        assert config.enabled is True
        assert config.session_ttl_seconds == 7200
