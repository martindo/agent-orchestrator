"""API routes for workflow branching evaluation."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agent_orchestrator.core.workflow_branching import (
    evaluate_branch_condition,
    resolve_next_phase,
)

router = APIRouter(prefix="/branching", tags=["branching"])


class EvaluateConditionRequest(BaseModel):
    condition: str = Field(..., min_length=1)
    context: dict = Field(default_factory=dict)


class ResolvePhaseRequest(BaseModel):
    phase_config: dict
    execution_result: dict = Field(default_factory=dict)


@router.post("/evaluate")
async def evaluate_condition(body: EvaluateConditionRequest) -> dict:
    """Evaluate a branch condition expression against a context."""
    result = evaluate_branch_condition(body.condition, body.context)
    return {"condition": body.condition, "context": body.context, "result": result}


@router.post("/resolve")
async def resolve_phase(body: ResolvePhaseRequest) -> dict:
    """Resolve the next phase given a phase config and execution result."""
    next_phase = resolve_next_phase(body.phase_config, body.execution_result)
    return {"next_phase": next_phase}
