"""MCP Server Resources — exposes platform data as MCP resources.

Resources provide read-only access to work items, audit records,
engine status, and agent configuration.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_orchestrator.core.engine import OrchestrationEngine

logger = logging.getLogger(__name__)


def register_resources(server: Any, engine: "OrchestrationEngine") -> None:
    """Register MCP resources on the server.

    Args:
        server: FastMCP server instance.
        engine: The running OrchestrationEngine.
    """

    @server.resource("orchestrator://status")
    async def get_status() -> str:
        """Current engine status including queue, pipeline, and agent statistics."""
        return json.dumps(engine.get_status(), indent=2, default=str)

    @server.resource("orchestrator://workitems")
    async def list_workitems() -> str:
        """List of all work items currently in the pipeline."""
        return json.dumps(engine.list_work_items(), indent=2, default=str)

    @server.resource("orchestrator://config/agents")
    async def list_agents() -> str:
        """Agent definitions from the active profile."""
        try:
            profile = engine._config.get_profile()
            agents = [a.model_dump() for a in profile.agents]
            return json.dumps(agents, indent=2, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @server.resource("orchestrator://audit")
    async def get_audit() -> str:
        """Recent audit records from the governance audit trail."""
        audit_logger = engine.audit_logger
        if audit_logger is None:
            return json.dumps({"error": "Audit logger not available"})
        records = audit_logger.query(limit=50)
        return json.dumps(records, indent=2, default=str)

    @server.resource("orchestrator://config/workflow")
    async def get_workflow() -> str:
        """Workflow configuration from the active profile."""
        try:
            profile = engine._config.get_profile()
            return json.dumps(profile.workflow.model_dump(), indent=2, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @server.resource("orchestrator://config/governance")
    async def get_governance() -> str:
        """Governance configuration from the active profile."""
        try:
            profile = engine._config.get_profile()
            return json.dumps(profile.governance.model_dump(), indent=2, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @server.resource("orchestrator://connectors")
    async def list_connectors() -> str:
        """Registered connector providers and their capabilities."""
        descriptors = engine._connector_registry.list_providers()
        data = [
            {
                "provider_id": d.provider_id,
                "display_name": d.display_name,
                "capability_types": [ct.value for ct in d.capability_types],
                "operations": [op.operation for op in d.operations],
                "enabled": d.enabled,
            }
            for d in descriptors
        ]
        return json.dumps(data, indent=2, default=str)

    logger.debug("Registered MCP resources")
