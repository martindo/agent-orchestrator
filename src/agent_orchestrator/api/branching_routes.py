"""API routes for workflow branching evaluation."""

from __future__ import annotations

from fastapi import APIRouter

from agent_orchestrator.core.workflow_branching import (
    evaluate_branch_condition,
    resolve_next_phase,
)

router = APIRouter(prefix="/branching", tags=["branching"])


@router.post("/evaluate")
async def evaluate_condition(body: dict) -> dict:
    """Evaluate a branch condition expression against a context."""
    condition: str = body.get("condition", "")
    context: dict = body.get("context", {})
    result = evaluate_branch_condition(condition, context)
    return {"condition": condition, "context": context, "result": result}


@router.post("/resolve")
async def resolve_phase(body: dict) -> dict:
    """Resolve the next phase given a phase config and execution result."""
    phase_config: dict = body.get("phase_config", {})
    execution_result: dict = body.get("execution_result", {})
    next_phase = resolve_next_phase(phase_config, execution_result)
    return {"next_phase": next_phase}
