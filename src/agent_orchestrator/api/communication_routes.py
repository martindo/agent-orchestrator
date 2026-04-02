"""API routes for agent-to-agent communication hub."""

from __future__ import annotations

from fastapi import APIRouter

from agent_orchestrator.core.agent_communication import communication_hub

router = APIRouter(prefix="/communication", tags=["communication"])


@router.post("/request")
async def request_assistance(body: dict) -> dict:
    """Create a new assistance request from one agent to a target role."""
    req = communication_hub.request_assistance(
        requesting_agent_id=body.get("requesting_agent_id", ""),
        target_role=body.get("target_role", ""),
        work_item_id=body.get("work_item_id", ""),
        question=body.get("question", ""),
        context=body.get("context", {}),
    )
    return {"success": True, "data": req.__dict__}


@router.post("/respond/{request_id}")
async def respond_to_request(request_id: str, body: dict) -> dict:
    """Respond to a pending assistance request."""
    req = communication_hub.respond(
        request_id,
        body.get("responding_agent_id", ""),
        body.get("response", ""),
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
