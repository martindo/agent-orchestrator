"""MCP-specific exceptions.

All exceptions inherit from OrchestratorError for catch-all handling.
"""

from agent_orchestrator.exceptions import OrchestratorError


class MCPError(OrchestratorError):
    """Base exception for MCP-related errors."""


class MCPConnectionError(MCPError):
    """Failed to connect to or communicate with an MCP server."""


class MCPToolCallError(MCPError):
    """Error during MCP tool invocation."""


class MCPResourceError(MCPError):
    """Error reading an MCP resource."""


class MCPConfigurationError(MCPError):
    """Invalid MCP configuration or missing dependency."""
