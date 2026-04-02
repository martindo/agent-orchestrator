"""Centralized cost tracking across platform components."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform-costs", tags=["platform-costs"])


@router.get("/summary")
async def platform_cost_summary(request: Request) -> dict:
    """Aggregate costs across all platform components."""
    results: dict = {
        "agent_orchestrator": {"tokens": 0, "cost": 0.0, "available": False},
        "auto_architect": {"tokens": 0, "cost": 0.0, "available": False},
        "total_tokens": 0,
        "total_cost": 0.0,
    }

    # AO costs (local)
    try:
        engine = request.app.state.engine
        if engine and hasattr(engine, "metrics"):
            metrics = engine.metrics
            results["agent_orchestrator"] = {
                "tokens": getattr(metrics, "total_tokens", 0),
                "cost": getattr(metrics, "total_cost", 0.0),
                "available": True,
            }
    except AttributeError:
        logger.debug("Engine or metrics not available for AO cost aggregation")

    # Auto-Architect costs (remote)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://localhost:4000/api/v1/costs/summary")
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                results["auto_architect"] = {
                    "tokens": data.get("totalTokens", 0),
                    "cost": data.get("totalCost", 0.0),
                    "available": True,
                }
    except httpx.HTTPError:
        logger.debug("Auto-Architect cost endpoint not reachable")

    results["total_tokens"] = (
        results["agent_orchestrator"]["tokens"]
        + results["auto_architect"]["tokens"]
    )
    results["total_cost"] = (
        results["agent_orchestrator"]["cost"]
        + results["auto_architect"]["cost"]
    )

    return results
