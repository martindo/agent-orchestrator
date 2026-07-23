"""MCP session lifecycle runs enter+exit in one task (audit 6.2).

The old manager entered the transport/session context managers in connect()'s
task and exited them in disconnect()'s — raising anyio's "exit cancel scope in a
different task" against live servers. _MCPSessionHandle now owns the whole
lifecycle in a single dedicated task; this test proves enter and exit happen in
that same task (and not the caller's).
"""

from __future__ import annotations

import asyncio

import mcp
import mcp.client.stdio
import pytest

from agent_orchestrator.mcp.client_manager import _MCPSessionHandle
from agent_orchestrator.mcp.models import MCPServerConfig, MCPTransportType

pytestmark = pytest.mark.asyncio


def _stdio_config() -> MCPServerConfig:
    return MCPServerConfig(
        server_id="test", display_name="T",
        transport=MCPTransportType.STDIO, command="echo", args=["hi"],
    )


class _RecordingCtx:
    """Async context manager that records the task it's entered/exited in."""

    def __init__(self, tasks: dict, name: str, value) -> None:
        self._tasks = tasks
        self._name = name
        self._value = value

    async def __aenter__(self):
        self._tasks[f"{self._name}_enter"] = asyncio.current_task()
        return self._value

    async def __aexit__(self, *exc) -> bool:
        self._tasks[f"{self._name}_exit"] = asyncio.current_task()
        return False


async def test_enter_and_exit_happen_in_one_task(monkeypatch):
    tasks: dict = {}
    read, write = object(), object()

    class _FakeSession:
        def __init__(self, r, w) -> None:
            pass

        async def __aenter__(self):
            tasks["session_enter"] = asyncio.current_task()
            return self

        async def __aexit__(self, *exc) -> bool:
            tasks["session_exit"] = asyncio.current_task()
            return False

        async def initialize(self) -> None:
            tasks["initialized"] = True

    monkeypatch.setattr(
        mcp.client.stdio, "stdio_client",
        lambda params: _RecordingCtx(tasks, "transport", (read, write)),
    )
    monkeypatch.setattr(mcp.client.stdio, "StdioServerParameters", lambda **kw: object())
    monkeypatch.setattr(mcp, "ClientSession", _FakeSession)

    handle = _MCPSessionHandle(_stdio_config())
    session = await handle.open()
    assert isinstance(session, _FakeSession)
    assert tasks["initialized"] is True

    await handle.close()

    runner = tasks["transport_enter"]
    assert runner is not None
    assert runner is not asyncio.current_task()          # not the caller's task
    assert tasks["transport_exit"] is runner             # transport enter+exit same task
    assert tasks["session_enter"] is runner              # session entered in the runner
    assert tasks["session_exit"] is runner               # …and exited in the same one


async def test_setup_failure_surfaces_from_open(monkeypatch):
    def _boom(params):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(mcp.client.stdio, "stdio_client", _boom)
    monkeypatch.setattr(mcp.client.stdio, "StdioServerParameters", lambda **kw: object())

    handle = _MCPSessionHandle(_stdio_config())
    with pytest.raises(RuntimeError, match="spawn failed"):
        await handle.open()
