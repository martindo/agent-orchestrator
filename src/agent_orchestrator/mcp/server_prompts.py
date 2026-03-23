"""MCP Server Prompts — exposes agent prompts as MCP prompt templates.

One prompt per AgentDefinition in the active profile, allowing external
AI clients to use the platform's agent instructions.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_orchestrator.core.engine import OrchestrationEngine

logger = logging.getLogger(__name__)


def register_prompts(server: Any, engine: "OrchestrationEngine") -> None:
    """Register MCP prompts from agent definitions.

    Args:
        server: FastMCP server instance.
        engine: The running OrchestrationEngine.
    """
    try:
        profile = engine._config.get_profile()
    except Exception:
        logger.debug("Cannot register prompts — profile not loaded")
        return

    for agent_def in profile.agents:
        _register_agent_prompt(server, agent_def)

    logger.debug("Registered %d agent prompts", len(profile.agents))


def _register_agent_prompt(server: Any, agent_def: Any) -> None:
    """Register a single agent's system prompt as an MCP prompt."""
    prompt_name = f"agent_{agent_def.id}"
    description = f"System prompt for agent '{agent_def.name}': {agent_def.description}"

    @server.prompt(name=prompt_name, description=description)
    async def _handler(
        work_item_title: str = "",
        work_item_data: str = "",
    ) -> str:
        """Get the agent's system prompt, optionally with work item context."""
        prompt = agent_def.system_prompt
        if work_item_title:
            prompt += f"\n\nCurrent work item: {work_item_title}"
        if work_item_data:
            prompt += f"\nWork item data: {work_item_data}"
        return prompt

    # Fix closure over agent_def
    _handler.__name__ = f"prompt_{agent_def.id}"
