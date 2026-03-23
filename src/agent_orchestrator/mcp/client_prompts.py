"""MCP Client Prompts — resolves prompt templates from external MCP servers.

Fetches prompt templates that can be used in agent prompt building,
allowing agents to leverage prompts defined in external MCP servers.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from agent_orchestrator.mcp.exceptions import MCPToolCallError

if TYPE_CHECKING:
    from agent_orchestrator.mcp.client_manager import MCPClientManager

logger = logging.getLogger(__name__)


class MCPPromptResolver:
    """Resolves prompt templates from connected MCP servers.

    Used during agent prompt building to incorporate external prompt
    templates into agent system prompts.
    """

    def __init__(self, client_manager: "MCPClientManager") -> None:
        self._client_manager = client_manager

    async def resolve_prompt(
        self,
        server_id: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> str:
        """Resolve a prompt template from an MCP server.

        Args:
            server_id: ID of the MCP server.
            prompt_name: Name of the prompt template.
            arguments: Optional prompt arguments.

        Returns:
            Resolved prompt text.

        Raises:
            MCPToolCallError: If prompt resolution fails.
        """
        result = await self._client_manager.get_prompt(
            server_id, prompt_name, arguments,
        )
        messages = result.get("messages", [])
        parts: list[str] = []
        for msg in messages:
            content = msg.get("content", "")
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    async def list_available_prompts(self) -> dict[str, list[dict[str, Any]]]:
        """List all available prompts from all connected servers.

        Returns:
            Dict mapping server_id to list of prompt info dicts.
        """
        result: dict[str, list[dict[str, Any]]] = {}
        for server_id in self._client_manager.connected_servers:
            try:
                prompts = await self._client_manager.discover_prompts(server_id)
                result[server_id] = [
                    {
                        "name": p.name,
                        "description": p.description,
                        "arguments": p.arguments,
                    }
                    for p in prompts
                ]
            except Exception as exc:
                logger.warning("Failed to list prompts from '%s': %s", server_id, exc)
                result[server_id] = []
        return result
