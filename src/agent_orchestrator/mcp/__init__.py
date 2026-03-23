"""MCP (Model Context Protocol) integration for the agent orchestrator.

Public exports are guarded so the package works even without the ``mcp``
SDK installed — only the models and exceptions are always available.
"""

from agent_orchestrator.mcp.exceptions import (
    MCPConfigurationError,
    MCPConnectionError,
    MCPError,
    MCPResourceError,
    MCPToolCallError,
)
from agent_orchestrator.mcp.models import (
    MCPClientConfig,
    MCPProfileConfig,
    MCPServerConfig,
    MCPServerHostConfig,
    MCPTransportType,
)

__all__: list[str] = [
    # Models (always available)
    "MCPTransportType",
    "MCPServerConfig",
    "MCPClientConfig",
    "MCPServerHostConfig",
    "MCPProfileConfig",
    # Exceptions (always available)
    "MCPError",
    "MCPConnectionError",
    "MCPToolCallError",
    "MCPResourceError",
    "MCPConfigurationError",
]

# --- Guarded imports: require the ``mcp`` SDK at runtime ---

try:
    from agent_orchestrator.mcp.client import MCPClientManager  # noqa: F401

    __all__.append("MCPClientManager")
except ImportError:
    pass

try:
    from agent_orchestrator.mcp.bridge import (  # noqa: F401
        MCPConnectorBridge,
        MCPToolConnectorProvider,
    )

    __all__.extend(["MCPToolConnectorProvider", "MCPConnectorBridge"])
except ImportError:
    pass

try:
    from agent_orchestrator.mcp.server import (  # noqa: F401
        create_mcp_asgi_app,
        create_mcp_server,
    )

    __all__.extend(["create_mcp_server", "create_mcp_asgi_app"])
except ImportError:
    pass
