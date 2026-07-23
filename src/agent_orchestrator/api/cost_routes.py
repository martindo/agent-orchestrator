"""Cost optimization API routes.

Exposes endpoints for estimating sprint costs and getting model
recommendations based on task complexity scoring.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agent_orchestrator.core.cost_optimizer import (
    calculate_complexity_score,
    estimate_sprint_cost,
    recommend_model,
)

router = APIRouter(prefix="/cost", tags=["cost"])


class EstimateCostRequest(BaseModel):
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    preferred_provider: str = "anthropic"


class ModelRecommendationRequest(BaseModel):
    story_points: int = 1
    description: str = ""
    files_involved: int = 0
    skill_required: str = "fullstack"
    preferred_provider: str = "anthropic"


@router.post("/estimate")
async def estimate_cost(body: EstimateCostRequest) -> dict[str, object]:
    """Estimate sprint cost with optimization recommendations.

    Returns:
        Cost estimation with optimized vs. premium totals and savings.
    """
    return estimate_sprint_cost(body.tasks, body.preferred_provider)


@router.post("/recommend-model")
async def get_model_recommendation(body: ModelRecommendationRequest) -> dict[str, object]:
    """Get a model recommendation for a single task.

    Returns:
        Complexity score and model recommendation.
    """
    score = calculate_complexity_score(
        story_points=body.story_points or 1,
        description_length=len(body.description),
        files_involved=body.files_involved,
        skill_required=body.skill_required,
    )
    rec = recommend_model(score, body.preferred_provider)
    return {
        "complexity_score": round(score, 1),
        "recommendation": {
            "provider": rec.provider,
            "model": rec.model,
            "estimated_cost_per_task": rec.estimated_cost_per_task,
            "reason": rec.reason,
        },
    }
