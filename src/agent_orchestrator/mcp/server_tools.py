"""MCP Server Tools — dynamically generates MCP tools from ConnectorRegistry.

Exposes both connector-backed tools (from registered providers) and
static orchestration tools (engine lifecycle, work items, agents).
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_orchestrator.core.engine import OrchestrationEngine

logger = logging.getLogger(__name__)


def register_tools(server: Any, engine: "OrchestrationEngine") -> None:
    """Register all MCP tools on the server.

    Args:
        server: FastMCP server instance.
        engine: The running OrchestrationEngine.
    """
    _register_orchestration_tools(server, engine)
    _register_connector_tools(server, engine)


def _register_orchestration_tools(server: Any, engine: "OrchestrationEngine") -> None:
    """Register static orchestration tools."""

    @server.tool()
    async def orchestrator_get_status() -> dict[str, Any]:
        """Get the current engine status including queue, pipeline, and agent stats."""
        return engine.get_status()

    @server.tool()
    async def orchestrator_list_workitems() -> list[dict[str, Any]]:
        """List all work items in the pipeline."""
        return engine.list_work_items()

    @server.tool()
    async def orchestrator_get_workitem(work_id: str) -> dict[str, Any]:
        """Get a specific work item by ID.

        Args:
            work_id: The work item ID.
        """
        item = engine.get_work_item(work_id)
        if item is None:
            return {"error": f"Work item '{work_id}' not found"}
        return {
            "id": item.id,
            "type_id": item.type_id,
            "title": item.title,
            "status": item.status.value,
            "priority": item.priority,
            "data": item.data,
            "current_phase": item.current_phase,
            "run_id": item.run_id,
            "app_id": item.app_id,
        }

    @server.tool()
    async def orchestrator_submit_workitem(
        type_id: str,
        title: str,
        data: dict[str, Any] | None = None,
        priority: int = 5,
    ) -> dict[str, Any]:
        """Submit a new work item for processing.

        Args:
            type_id: Work item type ID.
            title: Title for the work item.
            data: Optional work item data payload.
            priority: Priority (0=highest, default 5).
        """
        import uuid
        from agent_orchestrator.core.work_queue import WorkItem

        work_item = WorkItem(
            id=f"work-{uuid.uuid4().hex[:8]}",
            type_id=type_id,
            title=title,
            data=data or {},
            priority=priority,
        )
        try:
            work_id = await engine.submit_work(work_item)
            return {"work_id": work_id, "status": "submitted"}
        except Exception as exc:
            return {"error": str(exc)}

    @server.tool()
    async def orchestrator_list_agents() -> list[dict[str, Any]]:
        """List all agent definitions in the active profile."""
        try:
            profile = engine._config.get_profile()
            return [
                {
                    "id": a.id,
                    "name": a.name,
                    "description": a.description,
                    "phases": a.phases,
                    "enabled": a.enabled,
                    "provider": a.llm.provider,
                    "model": a.llm.model,
                }
                for a in profile.agents
            ]
        except Exception as exc:
            return [{"error": str(exc)}]

    @server.tool()
    async def orchestrator_engine_pause() -> dict[str, str]:
        """Pause the orchestration engine."""
        await engine.pause()
        return {"status": engine.state.value}

    @server.tool()
    async def orchestrator_engine_resume() -> dict[str, str]:
        """Resume the orchestration engine."""
        await engine.resume()
        return {"status": engine.state.value}

    logger.debug("Registered orchestration tools")


def _register_connector_tools(server: Any, engine: "OrchestrationEngine") -> None:
    """Register dynamic tools from ConnectorRegistry.

    Each registered connector provider's operations become MCP tools.
    Tool names are prefixed with 'connector_' to avoid collisions.
    """
    registry = engine._connector_registry
    seen_operations: set[str] = set()

    for descriptor in registry.list_providers():
        for op in descriptor.operations:
            tool_key = f"{descriptor.provider_id}:{op.operation}"
            if tool_key in seen_operations:
                continue
            seen_operations.add(tool_key)

            _register_single_connector_tool(server, engine, descriptor.provider_id, op)

    logger.debug("Registered %d connector-backed tools", len(seen_operations))


def _register_single_connector_tool(
    server: Any,
    engine: "OrchestrationEngine",
    provider_id: str,
    op: Any,
) -> None:
    """Register a single connector operation as an MCP tool."""
    tool_name = f"connector_{provider_id}_{op.operation}".replace(".", "_").replace("-", "_")
    description = f"[{provider_id}] {op.description}" if op.description else f"Connector: {provider_id}/{op.operation}"

    async def _handler(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        service = engine.connector_service
        if service is None:
            return {"error": "Connector service not available"}
        try:
            result = await service.execute(
                capability_type=op.capability_type,
                operation=op.operation,
                parameters=parameters or {},
                preferred_provider=provider_id,
            )
            return {
                "status": result.status.value,
                "payload": result.payload,
                "error_message": result.error_message,
                "duration_ms": result.duration_ms,
            }
        except Exception as exc:
            return {"error": str(exc)}

    # Use the server's tool decorator programmatically
    _handler.__name__ = tool_name
    _handler.__doc__ = description
    server.tool()(_handler)
