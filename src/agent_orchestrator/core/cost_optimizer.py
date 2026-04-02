"""Cost Optimizer — Recommends LLM model tiers based on task complexity.

Analyzes task attributes (story points, description length, files involved,
skill type) to compute a complexity score and recommend an appropriate
model tier (economy, standard, premium). Provides sprint-level cost
estimation with optimization savings.

Stateless: All functions are pure computations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ModelRecommendation:
    """Result of a model recommendation for a given task.

    Attributes:
        provider: LLM provider name (e.g. "anthropic", "openai").
        model: Specific model identifier.
        estimated_cost_per_task: Rough cost estimate in USD.
        reason: Human-readable explanation for the recommendation.
    """

    provider: str
    model: str
    estimated_cost_per_task: float
    reason: str


# Cost tiers mapping provider models to approximate per-1K-token costs
MODEL_TIERS: dict[str, list[dict[str, str | float]]] = {
    "economy": [
        {"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "cost_per_1k_tokens": 0.001},
        {"provider": "openai", "model": "gpt-4o-mini", "cost_per_1k_tokens": 0.00015},
    ],
    "standard": [
        {"provider": "anthropic", "model": "claude-sonnet-4-6", "cost_per_1k_tokens": 0.003},
        {"provider": "openai", "model": "gpt-4o", "cost_per_1k_tokens": 0.005},
    ],
    "premium": [
        {"provider": "anthropic", "model": "claude-opus-4-6", "cost_per_1k_tokens": 0.015},
        {"provider": "openai", "model": "o3", "cost_per_1k_tokens": 0.01},
    ],
}

# Skill-based complexity weight multipliers
_SKILL_WEIGHTS: dict[str, float] = {
    "security": 1.5,
    "architecture": 1.5,
    "backend": 1.0,
    "frontend": 0.8,
    "qa": 0.7,
    "fullstack": 1.0,
}


def calculate_complexity_score(
    story_points: int = 1,
    description_length: int = 0,
    files_involved: int = 0,
    skill_required: str = "fullstack",
) -> float:
    """Score task complexity on a 0-10 scale.

    Args:
        story_points: Estimated story points (1-13 typical).
        description_length: Character count of task description.
        files_involved: Number of files the task touches.
        skill_required: Primary skill domain for the task.

    Returns:
        Complexity score between 0.0 and 10.0.
    """
    score = 0.0
    score += min(story_points * 1.5, 5.0)
    score += min(description_length / 500, 2.0)
    score += min(files_involved * 0.5, 2.0)

    weight = _SKILL_WEIGHTS.get(skill_required, 1.0)
    score *= weight

    return min(score, 10.0)


def recommend_model(
    complexity_score: float,
    preferred_provider: str = "anthropic",
) -> ModelRecommendation:
    """Recommend a model tier based on complexity score.

    Args:
        complexity_score: Task complexity on a 0-10 scale.
        preferred_provider: Preferred LLM provider name.

    Returns:
        ModelRecommendation with provider, model, cost estimate, and reason.
    """
    if complexity_score <= 3.0:
        tier = "economy"
        reason = f"Simple task (complexity {complexity_score:.1f}/10) — economy model sufficient"
    elif complexity_score <= 6.0:
        tier = "standard"
        reason = f"Medium task (complexity {complexity_score:.1f}/10) — standard model recommended"
    else:
        tier = "premium"
        reason = f"Complex task (complexity {complexity_score:.1f}/10) — premium model needed"

    models = MODEL_TIERS[tier]
    # Prefer the user's preferred provider; fall back to first in tier
    model = next(
        (m for m in models if m["provider"] == preferred_provider),
        models[0],
    )

    # Rough estimate: ~10K tokens per task
    cost_per_1k = float(model["cost_per_1k_tokens"])
    estimated_cost = cost_per_1k * 10

    return ModelRecommendation(
        provider=str(model["provider"]),
        model=str(model["model"]),
        estimated_cost_per_task=estimated_cost,
        reason=reason,
    )


def estimate_sprint_cost(
    tasks: list[dict[str, object]],
    preferred_provider: str = "anthropic",
) -> dict[str, object]:
    """Estimate total sprint cost with optimization vs. premium-only.

    Args:
        tasks: List of task dicts with keys: title, story_points,
            description, files_involved, skill_required.
        preferred_provider: Preferred LLM provider name.

    Returns:
        Dict with optimized_total, premium_total, savings,
        savings_percentage, and per-task recommendations.
    """
    optimized_cost = 0.0
    premium_cost = 0.0
    recommendations: list[dict[str, object]] = []

    for task in tasks:
        description = task.get("description", "")
        desc_len = len(str(description)) if description else 0

        score = calculate_complexity_score(
            story_points=int(task.get("story_points", 1) or 1),
            description_length=desc_len,
            files_involved=int(task.get("files_involved", 0) or 0),
            skill_required=str(task.get("skill_required", "fullstack")),
        )

        rec = recommend_model(score, preferred_provider)
        optimized_cost += rec.estimated_cost_per_task

        premium_rec = recommend_model(10.0, preferred_provider)  # Force premium
        premium_cost += premium_rec.estimated_cost_per_task

        recommendations.append({
            "task": str(task.get("title", "Unknown")),
            "complexity": round(score, 1),
            "recommended_tier": rec.model,
            "estimated_cost": round(rec.estimated_cost_per_task, 4),
            "reason": rec.reason,
        })

    savings = premium_cost - optimized_cost
    savings_pct = (savings / premium_cost * 100) if premium_cost > 0 else 0

    return {
        "optimized_total": round(optimized_cost, 4),
        "premium_total": round(premium_cost, 4),
        "savings": round(savings, 4),
        "savings_percentage": round(savings_pct, 1),
        "task_recommendations": recommendations,
    }
