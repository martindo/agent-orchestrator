"""MCP Server — exposes platform capabilities via MCP protocol.

Uses the official `mcp` SDK's FastMCP class and Streamable HTTP transport.
All SDK imports are lazy — the server is only created when explicitly enabled.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from agent_orchestrator.mcp.exceptions import MCPConfigurationError
from agent_orchestrator.mcp.models import MCPServerHostConfig

if TYPE_CHECKING:
    from agent_orchestrator.core.engine import OrchestrationEngine

logger = logging.getLogger(__name__)


def _check_mcp_sdk() -> None:
    """Raise MCPConfigurationError if the mcp SDK is not installed."""
    try:
        import mcp  # noqa: F401
    except ImportError as exc:
        msg = (
            "The 'mcp' package is required for MCP server support. "
            "Install it with: pip install 'agent-orchestrator[mcp]'"
        )
        raise MCPConfigurationError(msg) from exc


def create_mcp_server(
    engine: "OrchestrationEngine",
    config: MCPServerHostConfig,
) -> Any:
    """Create an MCP server instance with tools, resources, and prompts.

    The server dynamically generates tools from ConnectorRegistry and
    exposes engine capabilities as resources and prompts.

    Args:
        engine: The running OrchestrationEngine.
        config: MCP server hosting configuration.

    Returns:
        mcp.server.fastmcp.FastMCP server instance.

    Raises:
        MCPConfigurationError: If MCP SDK not installed.
    """
    _check_mcp_sdk()

    from mcp.server.fastmcp import FastMCP

    server = FastMCP(
        "Agent Orchestrator",
        instructions="Agent orchestration & governance platform with governed tool execution.",
    )

    # Register tools
    from agent_orchestrator.mcp.server_tools import register_tools
    register_tools(server, engine)

    # Register resources
    from agent_orchestrator.mcp.server_resources import register_resources
    register_resources(server, engine)

    # Register prompts
    from agent_orchestrator.mcp.server_prompts import register_prompts
    register_prompts(server, engine)

    logger.info("MCP server created with tools, resources, and prompts")
    return server


def create_mcp_asgi_app(
    engine: "OrchestrationEngine",
    config: MCPServerHostConfig,
) -> Any:
    """Create an ASGI app for the MCP server using Streamable HTTP transport.

    This can be mounted on a FastAPI application at the configured path.

    Args:
        engine: The running OrchestrationEngine.
        config: MCP server hosting configuration.

    Returns:
        ASGI application suitable for mounting on FastAPI.

    Raises:
        MCPConfigurationError: If MCP SDK not installed.
    """
    server = create_mcp_server(engine, config)
    return server.streamable_http_app()
