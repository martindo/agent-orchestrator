"""Tests for cost pricing and model recommendations (audit 4.5).

Locks in valid current model IDs and real usage-based pricing (input/output
rates) instead of the prior flat `cost_per_1k * 10` guess with stale IDs.
"""

from __future__ import annotations

import pytest

from agent_orchestrator.core.cost_optimizer import (
    MODEL_TIERS,
    _TOKEN_PRICING,
    estimate_sprint_cost,
    price_usage,
    recommend_model,
)


# ---- Model IDs are current/valid --------------------------------------------


def test_no_stale_model_ids():
    all_models = {m["model"] for tier in MODEL_TIERS.values() for m in tier}
    assert "claude-sonnet-4-6" not in all_models  # never existed
    assert "claude-opus-4-6" not in all_models
    assert "claude-sonnet-5" in all_models
    assert "claude-opus-4-8" in all_models


def test_every_tier_model_has_pricing():
    for tier in MODEL_TIERS.values():
        for entry in tier:
            assert entry["model"] in _TOKEN_PRICING, entry["model"]


# ---- price_usage ------------------------------------------------------------


def test_price_usage_splits_input_output():
    # gpt-4o: input 0.0025/1k, output 0.01/1k → 1000 in + 1000 out = 0.0025+0.01
    cost = price_usage("gpt-4o", 1000, 1000)
    assert cost == pytest.approx(0.0025 + 0.01)


def test_price_usage_scales_with_tokens():
    assert price_usage("gpt-4o", 2000, 0) == pytest.approx(2 * 0.0025)
    assert price_usage("gpt-4o", 0, 500) == pytest.approx(0.5 * 0.01)


def test_price_usage_unknown_model_is_zero():
    assert price_usage("totally-made-up", 1000, 1000) == 0.0


# ---- recommend_model --------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_tier_model",
    [
        (1.0, "claude-haiku-4-5-20251001"),  # economy
        (5.0, "claude-sonnet-5"),            # standard
        (9.0, "claude-opus-4-8"),            # premium
    ],
)
def test_recommend_model_tier(score, expected_tier_model):
    rec = recommend_model(score, preferred_provider="anthropic")
    assert rec.model == expected_tier_model
    # Estimate is derived from real rates → positive and non-fabricated.
    assert rec.estimated_cost_per_task > 0
    assert rec.provider == "anthropic"


def test_recommend_prefers_provider():
    assert recommend_model(5.0, preferred_provider="openai").provider == "openai"


def test_premium_costs_more_than_economy():
    econ = recommend_model(1.0, "anthropic").estimated_cost_per_task
    prem = recommend_model(9.0, "anthropic").estimated_cost_per_task
    assert prem > econ


# ---- estimate_sprint_cost ---------------------------------------------------


def test_sprint_cost_shows_savings():
    tasks = [
        {"title": "tiny", "story_points": 1, "description": "x", "skill_required": "qa"},
        {"title": "big", "story_points": 13, "description": "y" * 2000,
         "files_involved": 10, "skill_required": "architecture"},
    ]
    result = estimate_sprint_cost(tasks, preferred_provider="anthropic")
    assert result["optimized_total"] <= result["premium_total"]
    assert result["savings"] >= 0
    assert len(result["task_recommendations"]) == 2
