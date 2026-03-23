"""MCP Server Governance — applies governance checks to MCP tool calls.

Ensures all MCP server tool invocations go through the same governance
pipeline as internal connector calls: permission check → Governor evaluation
→ execution → audit logging.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from agent_orchestrator.governance.audit_logger import RecordType

if TYPE_CHECKING:
    from agent_orchestrator.core.engine import OrchestrationEngine
    from agent_orchestrator.governance.governor import Resolution

logger = logging.getLogger(__name__)


class GovernedToolDispatcher:
    """Dispatches MCP tool calls with governance checks.

    Flow:
    1. Session permission check
    2. Governor.evaluate() — non-blocking
    3. ConnectorService.execute() or engine method
    4. AuditLogger.append() with MCP_INVOCATION record type
    """

    def __init__(self, engine: "OrchestrationEngine") -> None:
        self._engine = engine

    async def dispatch(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str = "",
    ) -> dict[str, Any]:
        """Dispatch a tool call through governance.

        Args:
            tool_name: Name of the tool being called.
            arguments: Tool arguments.
            session_id: MCP session ID for tracking.

        Returns:
            Tool result dict, potentially with governance warnings.
        """
        governor = self._engine.governor
        audit_logger = self._engine.audit_logger

        # Governor evaluation
        if governor is not None:
            from agent_orchestrator.governance.governor import Resolution
            decision = governor.evaluate(
                {"tool_name": tool_name, "session_id": session_id},
            )

            if decision.resolution == Resolution.ABORT:
                self._audit_invocation(
                    tool_name, arguments, session_id,
                    status="denied",
                    reason=decision.reason,
                )
                return {
                    "error": f"Governance denied: {decision.reason}",
                    "governance_resolution": "abort",
                }

            if decision.resolution == Resolution.QUEUE_FOR_REVIEW:
                review_queue = self._engine.review_queue
                review_id = ""
                if review_queue is not None:
                    review_id = review_queue.enqueue(
                        work_id=f"mcp:{session_id}",
                        phase_id="mcp_invocation",
                        reason=decision.reason,
                        decision_data={"tool_name": tool_name},
                    )
                self._audit_invocation(
                    tool_name, arguments, session_id,
                    status="queued_for_review",
                    reason=decision.reason,
                )
                return {
                    "error": "Queued for review",
                    "governance_resolution": "queue_for_review",
                    "review_id": review_id,
                }

            if decision.resolution.value == "allow_with_warning":
                # Continue but include warning
                logger.warning(
                    "MCP tool '%s' allowed with warning: %s",
                    tool_name, decision.warnings,
                )

        # Audit successful invocation
        self._audit_invocation(
            tool_name, arguments, session_id,
            status="allowed",
        )

        return {"governance_resolution": "allow"}

    def _audit_invocation(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str,
        status: str = "",
        reason: str = "",
    ) -> None:
        """Record an MCP invocation in the audit trail."""
        audit_logger = self._engine.audit_logger
        if audit_logger is None:
            return

        # Use SYSTEM_EVENT since MCP_INVOCATION may not be added yet
        record_type = RecordType.SYSTEM_EVENT
        # Try MCP_INVOCATION if available
        try:
            record_type = RecordType("mcp_invocation")
        except ValueError:
            pass

        audit_logger.append(
            record_type=record_type,
            action=f"mcp.tool.{tool_name}",
            summary=f"MCP tool invocation: {tool_name} (status={status})",
            data={
                "tool_name": tool_name,
                "session_id": session_id,
                "status": status,
                "reason": reason,
                "argument_keys": list(arguments.keys()),
            },
        )
