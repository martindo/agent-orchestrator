"""Agent-to-agent communication hub for cross-role assistance requests.

Provides a centralized message broker where agents can request help from
agents in other roles and receive responses asynchronously.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AssistanceRequest:
    """A request from one agent to another role for assistance."""

    id: str
    requesting_agent_id: str
    target_role: str  # e.g., "security", "qa", "architect"
    work_item_id: str
    question: str
    context: dict[str, Any] = field(default_factory=dict)
    response: Optional[str] = None
    responding_agent_id: Optional[str] = None
    status: str = "pending"  # pending, responded, timeout, cancelled
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    responded_at: Optional[str] = None


class AgentCommunicationHub:
    """Broker for agent-to-agent assistance requests."""

    def __init__(self) -> None:
        self.requests: list[AssistanceRequest] = []
        self._counter = 0

    def request_assistance(
        self,
        requesting_agent_id: str,
        target_role: str,
        work_item_id: str,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> AssistanceRequest:
        """Create a new assistance request targeting a specific role.

        Args:
            requesting_agent_id: ID of the agent asking for help.
            target_role: Role that should respond (e.g. "security").
            work_item_id: Related work item ID.
            question: The question or request text.
            context: Optional additional context data.

        Returns:
            The created AssistanceRequest.
        """
        self._counter += 1
        req = AssistanceRequest(
            id=f"assist-{self._counter}",
            requesting_agent_id=requesting_agent_id,
            target_role=target_role,
            work_item_id=work_item_id,
            question=question,
            context=context or {},
        )
        self.requests.append(req)
        logger.info(
            "Assistance requested: %s from %s to role %s",
            req.id, requesting_agent_id, target_role,
        )
        return req

    def respond(
        self,
        request_id: str,
        responding_agent_id: str,
        response: str,
    ) -> Optional[AssistanceRequest]:
        """Respond to a pending assistance request.

        Args:
            request_id: ID of the request to respond to.
            responding_agent_id: ID of the agent providing the response.
            response: The response text.

        Returns:
            The updated request, or None if not found / already responded.
        """
        req = next((r for r in self.requests if r.id == request_id), None)
        if not req or req.status != "pending":
            return None
        req.response = response
        req.responding_agent_id = responding_agent_id
        req.status = "responded"
        req.responded_at = datetime.utcnow().isoformat()
        logger.info("Assistance responded: %s by %s", request_id, responding_agent_id)
        return req

    def get_pending_for_role(self, role: str) -> list[AssistanceRequest]:
        """Return all pending requests targeting a given role."""
        return [r for r in self.requests if r.target_role == role and r.status == "pending"]

    def get_for_work_item(self, work_item_id: str) -> list[AssistanceRequest]:
        """Return all requests associated with a work item."""
        return [r for r in self.requests if r.work_item_id == work_item_id]

    def get_all(self, limit: int = 50) -> list[AssistanceRequest]:
        """Return the most recent requests up to *limit*."""
        return self.requests[-limit:]


# Singleton
communication_hub = AgentCommunicationHub()
