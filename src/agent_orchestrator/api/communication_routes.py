"""API routes for agent-to-agent communication hub."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agent_orchestrator.core.agent_communication import communication_hub

router = APIRouter(prefix="/communication", tags=["communication"])


class AssistanceRequest(BaseModel):
    requesting_agent_id: str = Field(..., min_length=1)
    target_role: str = Field(..., min_length=1)
    work_item_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    context: dict = Field(default_factory=dict)


class RespondRequest(BaseModel):
    responding_agent_id: str = Field(..., min_length=1)
    response: str = Field(..., min_length=1)


@router.post("/request")
async def request_assistance(body: AssistanceRequest) -> dict:
    """Create a new assistance request from one agent to a target role."""
    req = communication_hub.request_assistance(
        requesting_agent_id=body.requesting_agent_id,
        target_role=body.target_role,
        work_item_id=body.work_item_id,
        question=body.question,
        context=body.context,
    )
    return {"success": True, "data": req.__dict__}


@router.post("/respond/{request_id}")
async def respond_to_request(request_id: str, body: RespondRequest) -> dict:
    """Respond to a pending assistance request."""
    req = communication_hub.respond(
        request_id,
        body.responding_agent_id,
        body.response,
    )
    if not req:
        return {"success": False, "error": "Request not found or already responded"}
    return {"success": True, "data": req.__dict__}


@router.get("/pending/{role}")
async def get_pending_for_role(role: str) -> dict:
    """List all pending assistance requests for a given role."""
    reqs = communication_hub.get_pending_for_role(role)
    return {"data": [r.__dict__ for r in reqs], "total": len(reqs)}


@router.get("/work-item/{work_item_id}")
async def get_for_work_item(work_item_id: str) -> dict:
    """List all assistance requests related to a work item."""
    reqs = communication_hub.get_for_work_item(work_item_id)
    return {"data": [r.__dict__ for r in reqs], "total": len(reqs)}


@router.get("/history")
async def get_history(limit: int = 50) -> dict:
    """List recent assistance request history."""
    reqs = communication_hub.get_all(limit)
    return {"data": [r.__dict__ for r in reqs], "total": len(reqs)}
