"""MCP Client Manager — manages connections to external MCP servers.

Uses the official `mcp` Python SDK for session lifecycle, tool discovery,
and invocation. All SDK imports are lazy — the platform works without
the mcp package installed.

Thread-safe: Uses asyncio.Lock for session state.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from agent_orchestrator.mcp.exceptions import (
    MCPConfigurationError,
    MCPConnectionError,
    MCPToolCallError,
    MCPResourceError,
)
from agent_orchestrator.mcp.models import (
    MCPClientConfig,
    MCPPromptInfo,
    MCPResourceInfo,
    MCPServerConfig,
    MCPSessionInfo,
    MCPToolInfo,
    MCPTransportType,
)

logger = logging.getLogger(__name__)


def _check_mcp_sdk() -> None:
    """Raise MCPConfigurationError if the mcp SDK is not installed."""
    try:
        import mcp  # noqa: F401
    except ImportError as exc:
        msg = (
            "The 'mcp' package is required for MCP support. "
            "Install it with: pip install 'agent-orchestrator[mcp]'"
        )
        raise MCPConfigurationError(msg) from exc


def _resolve_env_vars(env: dict[str, str]) -> dict[str, str]:
    """Resolve ${VAR} references in environment variable values."""
    resolved: dict[str, str] = {}
    for key, value in env.items():
        if value.startswith("${") and value.endswith("}"):
            env_name = value[2:-1]
            resolved[key] = os.environ.get(env_name, "")
        else:
            resolved[key] = value
    return resolved


class MCPClientManager:
    """Manages connections to external MCP servers.

    Lifecycle: connect → discover → call_tool/read_resource/get_prompt → disconnect

    Usage:
        manager = MCPClientManager(config)
        await manager.connect_all()
        tools = await manager.discover_tools("github")
        result = await manager.call_tool("github", "list_repos", {"org": "acme"})
        await manager.disconnect_all()
    """

    def __init__(self, config: MCPClientConfig) -> None:
        self._config = config
        self._server_configs: dict[str, MCPServerConfig] = {
            s.server_id: s for s in config.servers if s.enabled
        }
        self._sessions: dict[str, Any] = {}  # server_id -> mcp ClientSession
        self._transports: dict[str, Any] = {}  # server_id -> transport context managers
        self._session_info: dict[str, MCPSessionInfo] = {}
        self._lock = asyncio.Lock()

    @property
    def connected_servers(self) -> list[str]:
        """Return IDs of currently connected servers."""
        return [
            sid for sid, info in self._session_info.items()
            if info.connected
        ]

    def get_session_info(self, server_id: str) -> MCPSessionInfo | None:
        """Get session info for a server."""
        return self._session_info.get(server_id)

    async def connect(self, server_id: str) -> None:
        """Connect to an MCP server.

        Args:
            server_id: ID of the server to connect to.

        Raises:
            MCPConfigurationError: If server_id not found or SDK missing.
            MCPConnectionError: If connection fails.
        """
        _check_mcp_sdk()

        server_config = self._server_configs.get(server_id)
        if server_config is None:
            msg = f"MCP server '{server_id}' not found in configuration"
            raise MCPConfigurationError(msg)

        async with self._lock:
            if server_id in self._sessions:
                logger.debug("Already connected to MCP server '%s'", server_id)
                return

        try:
            session, transport_ctx = await self._create_session(server_config)
            async with self._lock:
                self._sessions[server_id] = session
                self._transports[server_id] = transport_ctx
                self._session_info[server_id] = MCPSessionInfo(
                    server_id=server_id,
                    connected=True,
                )
            logger.info("Connected to MCP server '%s' (%s)", server_id, server_config.display_name)
        except MCPConfigurationError:
            raise
        except Exception as exc:
            msg = f"Failed to connect to MCP server '{server_id}': {exc}"
            raise MCPConnectionError(msg) from exc

    async def _create_session(self, config: MCPServerConfig) -> tuple[Any, Any]:
        """Create an MCP client session based on transport type."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp.client.streamable_http import streamablehttp_client

        if config.transport == MCPTransportType.STDIO:
            if config.command is None:
                msg = f"stdio transport requires 'command' for server '{config.server_id}'"
                raise MCPConfigurationError(msg)

            env = _resolve_env_vars(config.env)
            server_params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=env or None,
            )

            # stdio_client returns an async context manager yielding (read, write)
            transport_ctx = stdio_client(server_params)
            streams = await transport_ctx.__aenter__()
            read_stream, write_stream = streams
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            await session.initialize()
            return session, transport_ctx

        if config.transport in (MCPTransportType.STREAMABLE_HTTP, MCPTransportType.SSE):
            if config.url is None:
                msg = f"HTTP transport requires 'url' for server '{config.server_id}'"
                raise MCPConfigurationError(msg)

            headers = dict(config.headers)
            if config.credential_env_var:
                token = os.environ.get(config.credential_env_var, "")
                if token:
                    headers["Authorization"] = f"Bearer {token}"

            transport_ctx = streamablehttp_client(url=config.url, headers=headers)
            streams = await transport_ctx.__aenter__()
            read_stream, write_stream, _ = streams
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            await session.initialize()
            return session, transport_ctx

        msg = f"Unsupported transport type: {config.transport}"
        raise MCPConfigurationError(msg)

    async def connect_all(self) -> dict[str, bool]:
        """Connect to all configured servers with auto_connect=True.

        Returns:
            Dict mapping server_id to success boolean.
        """
        results: dict[str, bool] = {}
        for server_id, config in self._server_configs.items():
            if not config.auto_connect:
                results[server_id] = False
                continue
            try:
                await self.connect(server_id)
                results[server_id] = True
            except (MCPConnectionError, MCPConfigurationError) as exc:
                logger.warning("Failed to connect to '%s': %s", server_id, exc)
                results[server_id] = False
        return results

    async def disconnect(self, server_id: str) -> None:
        """Disconnect from an MCP server.

        Args:
            server_id: ID of the server to disconnect from.
        """
        async with self._lock:
            session = self._sessions.pop(server_id, None)
            transport_ctx = self._transports.pop(server_id, None)
            self._session_info.pop(server_id, None)

        if session is not None:
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                logger.debug("Error closing MCP session for '%s'", server_id, exc_info=True)

        if transport_ctx is not None:
            try:
                await transport_ctx.__aexit__(None, None, None)
            except Exception:
                logger.debug("Error closing transport for '%s'", server_id, exc_info=True)

        logger.info("Disconnected from MCP server '%s'", server_id)

    async def disconnect_all(self) -> None:
        """Disconnect from all connected servers."""
        server_ids = list(self._sessions.keys())
        for server_id in server_ids:
            await self.disconnect(server_id)

    def _get_session(self, server_id: str) -> Any:
        """Get active session, raising if not connected."""
        session = self._sessions.get(server_id)
        if session is None:
            msg = f"Not connected to MCP server '{server_id}'"
            raise MCPConnectionError(msg)
        return session

    async def discover_tools(self, server_id: str) -> list[MCPToolInfo]:
        """Discover tools offered by a connected MCP server.

        Args:
            server_id: ID of the connected server.

        Returns:
            List of MCPToolInfo for available tools.
        """
        session = self._get_session(server_id)
        try:
            result = await session.list_tools()
            tools = [
                MCPToolInfo(
                    server_id=server_id,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                )
                for tool in result.tools
            ]
            # Update session info
            async with self._lock:
                old = self._session_info.get(server_id)
                if old is not None:
                    self._session_info[server_id] = MCPSessionInfo(
                        server_id=server_id,
                        connected=True,
                        tools=tools,
                        resources=old.resources,
                        prompts=old.prompts,
                    )
            logger.info("Discovered %d tools from '%s'", len(tools), server_id)
            return tools
        except Exception as exc:
            msg = f"Failed to discover tools from '{server_id}': {exc}"
            raise MCPConnectionError(msg) from exc

    async def discover_resources(self, server_id: str) -> list[MCPResourceInfo]:
        """Discover resources offered by a connected MCP server."""
        session = self._get_session(server_id)
        try:
            result = await session.list_resources()
            resources = [
                MCPResourceInfo(
                    server_id=server_id,
                    uri=str(res.uri),
                    name=res.name,
                    description=res.description or "",
                    mime_type=getattr(res, "mimeType", None),
                )
                for res in result.resources
            ]
            async with self._lock:
                old = self._session_info.get(server_id)
                if old is not None:
                    self._session_info[server_id] = MCPSessionInfo(
                        server_id=server_id,
                        connected=True,
                        tools=old.tools,
                        resources=resources,
                        prompts=old.prompts,
                    )
            logger.info("Discovered %d resources from '%s'", len(resources), server_id)
            return resources
        except Exception as exc:
            msg = f"Failed to discover resources from '{server_id}': {exc}"
            raise MCPConnectionError(msg) from exc

    async def discover_prompts(self, server_id: str) -> list[MCPPromptInfo]:
        """Discover prompt templates offered by a connected MCP server."""
        session = self._get_session(server_id)
        try:
            result = await session.list_prompts()
            prompts = [
                MCPPromptInfo(
                    server_id=server_id,
                    name=prompt.name,
                    description=prompt.description or "",
                    arguments=[
                        {"name": arg.name, "description": arg.description or "", "required": getattr(arg, "required", False)}
                        for arg in (prompt.arguments or [])
                    ],
                )
                for prompt in result.prompts
            ]
            async with self._lock:
                old = self._session_info.get(server_id)
                if old is not None:
                    self._session_info[server_id] = MCPSessionInfo(
                        server_id=server_id,
                        connected=True,
                        tools=old.tools,
                        resources=old.resources,
                        prompts=prompts,
                    )
            logger.info("Discovered %d prompts from '%s'", len(prompts), server_id)
            return prompts
        except Exception as exc:
            msg = f"Failed to discover prompts from '{server_id}': {exc}"
            raise MCPConnectionError(msg) from exc

    async def call_tool(
        self, server_id: str, tool_name: str, arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a tool on a connected MCP server.

        Args:
            server_id: ID of the connected server.
            tool_name: Name of the tool to call.
            arguments: Tool arguments.

        Returns:
            Tool result as a dict with 'content' and 'isError' keys.

        Raises:
            MCPToolCallError: If the tool call fails.
        """
        session = self._get_session(server_id)
        try:
            result = await session.call_tool(tool_name, arguments or {})
            content_parts = []
            for part in result.content:
                if hasattr(part, "text"):
                    content_parts.append({"type": "text", "text": part.text})
                elif hasattr(part, "data"):
                    content_parts.append({"type": "resource", "data": part.data})
                else:
                    content_parts.append({"type": "unknown", "value": str(part)})
            return {
                "content": content_parts,
                "isError": getattr(result, "isError", False),
            }
        except Exception as exc:
            msg = f"Tool call '{tool_name}' on '{server_id}' failed: {exc}"
            raise MCPToolCallError(msg) from exc

    async def read_resource(self, server_id: str, uri: str) -> dict[str, Any]:
        """Read a resource from a connected MCP server.

        Args:
            server_id: ID of the connected server.
            uri: Resource URI.

        Returns:
            Resource content as a dict.

        Raises:
            MCPResourceError: If the resource read fails.
        """
        session = self._get_session(server_id)
        try:
            result = await session.read_resource(uri)
            contents = []
            for part in result.contents:
                entry: dict[str, Any] = {"uri": str(part.uri)}
                if hasattr(part, "text"):
                    entry["text"] = part.text
                if hasattr(part, "mimeType"):
                    entry["mimeType"] = part.mimeType
                contents.append(entry)
            return {"contents": contents}
        except Exception as exc:
            msg = f"Resource read '{uri}' on '{server_id}' failed: {exc}"
            raise MCPResourceError(msg) from exc

    async def get_prompt(
        self, server_id: str, prompt_name: str, arguments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Get a prompt from a connected MCP server.

        Args:
            server_id: ID of the connected server.
            prompt_name: Name of the prompt.
            arguments: Prompt arguments.

        Returns:
            Prompt messages as a dict.
        """
        session = self._get_session(server_id)
        try:
            result = await session.get_prompt(prompt_name, arguments or {})
            messages = []
            for msg in result.messages:
                messages.append({
                    "role": msg.role,
                    "content": msg.content.text if hasattr(msg.content, "text") else str(msg.content),
                })
            return {
                "description": getattr(result, "description", ""),
                "messages": messages,
            }
        except Exception as exc:
            msg_str = f"Prompt '{prompt_name}' on '{server_id}' failed: {exc}"
            raise MCPToolCallError(msg_str) from exc
