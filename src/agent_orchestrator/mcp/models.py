"""MCP integration models — configuration and runtime data types.

All models are Pydantic v2 frozen dataclasses.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MCPTransportType(str, Enum):
    """Transport protocol for MCP server connections."""
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


class MCPServerConfig(BaseModel):
    """Configuration for connecting to an external MCP server."""
    model_config = {"frozen": True}

    server_id: str = Field(description="Unique identifier for this server")
    display_name: str = Field(description="Human-readable name")
    transport: MCPTransportType = Field(description="Transport protocol")
    url: str | None = Field(default=None, description="URL for streamable_http/sse transport")
    command: str | None = Field(default=None, description="Command for stdio transport")
    args: list[str] = Field(default_factory=list, description="Command arguments for stdio")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")
    credential_env_var: str | None = Field(default=None, description="Env var name for credentials")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers")
    auto_connect: bool = Field(default=True, description="Connect on engine start")
    capability_type_override: str | None = Field(default=None, description="Override CapabilityType mapping")
    enabled: bool = True


class MCPClientConfig(BaseModel):
    """Client-side MCP configuration."""
    model_config = {"frozen": True}

    servers: list[MCPServerConfig] = Field(default_factory=list)
    default_capability_type: str = Field(default="external_api", description="Default CapabilityType for MCP tools")
    tool_prefix: str = Field(default="mcp", description="Prefix for registered tool provider IDs")


class MCPServerHostConfig(BaseModel):
    """Configuration for hosting an MCP server."""
    model_config = {"frozen": True}

    enabled: bool = False
    mount_path: str = Field(default="/mcp", description="ASGI mount path")
    session_ttl_seconds: int = Field(default=3600, description="Session TTL")
    max_sessions: int = Field(default=100, description="Maximum concurrent sessions")
    audit_all_invocations: bool = Field(default=True, description="Audit every MCP invocation")


class MCPProfileConfig(BaseModel):
    """Complete MCP configuration for a profile."""
    model_config = {"frozen": True}

    client: MCPClientConfig = Field(default_factory=MCPClientConfig)
    server: MCPServerHostConfig = Field(default_factory=MCPServerHostConfig)


class MCPToolInfo(BaseModel):
    """Discovered MCP tool metadata."""
    model_config = {"frozen": True}

    server_id: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPResourceInfo(BaseModel):
    """Discovered MCP resource metadata."""
    model_config = {"frozen": True}

    server_id: str
    uri: str
    name: str
    description: str = ""
    mime_type: str | None = None


class MCPPromptInfo(BaseModel):
    """Discovered MCP prompt metadata."""
    model_config = {"frozen": True}

    server_id: str
    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = Field(default_factory=list)


class MCPSessionInfo(BaseModel):
    """Runtime session state for an MCP server connection."""
    model_config = {"frozen": True}

    server_id: str
    connected: bool = False
    tools: list[MCPToolInfo] = Field(default_factory=list)
    resources: list[MCPResourceInfo] = Field(default_factory=list)
    prompts: list[MCPPromptInfo] = Field(default_factory=list)
