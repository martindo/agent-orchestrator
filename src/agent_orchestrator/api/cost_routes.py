"""Cost optimization API routes.

Exposes endpoints for estimating sprint costs and getting model
recommendations based on task complexity scoring.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from agent_orchestrator.core.cost_optimizer import (
    calculate_complexity_score,
    estimate_sprint_cost,
    recommend_model,
)

router = APIRouter(prefix="/cost", tags=["cost"])


@router.post("/estimate")
async def estimate_cost(body: dict[str, Any]) -> dict[str, object]:
    """Estimate sprint cost with optimization recommendations.

    Accepts a dict with 'tasks' (list of task dicts) and optional
    'preferred_provider' (default: "anthropic").

    Returns:
        Cost estimation with optimized vs. premium totals and savings.
    """
    tasks = body.get("tasks", [])
    provider = body.get("preferred_provider", "anthropic")
    return estimate_sprint_cost(tasks, str(provider))


@router.post("/recommend-model")
async def get_model_recommendation(body: dict[str, Any]) -> dict[str, object]:
    """Get a model recommendation for a single task.

    Accepts task attributes: story_points, description, files_involved,
    skill_required, preferred_provider.

    Returns:
        Complexity score and model recommendation.
    """
    description = body.get("description", "")
    score = calculate_complexity_score(
        story_points=int(body.get("story_points", 1) or 1),
        description_length=len(str(description)) if description else 0,
        files_involved=int(body.get("files_involved", 0) or 0),
        skill_required=str(body.get("skill_required", "fullstack")),
    )
    provider = body.get("preferred_provider", "anthropic")
    rec = recommend_model(score, str(provider))
    return {
        "complexity_score": round(score, 1),
        "recommendation": {
            "provider": rec.provider,
            "model": rec.model,
            "estimated_cost_per_task": rec.estimated_cost_per_task,
            "reason": rec.reason,
        },
    }
