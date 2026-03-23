"""Routes for the AI Workflow Recommender.

Three endpoints:
- POST /recommend/greenfield — recommend from a project description
- POST /recommend/codebase-prompt — generate a codebase analysis prompt
- POST /recommend/from-codebase — recommend from codebase analysis JSON

Greenfield uses a three-tier strategy:
1. Static domain catalog (instant, no API cost)
2. LLM-generated agents for unknown domains (cached and persisted)
3. Software dev archetypes fallback
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from studio.recommend.engine import (
    RecommendationResult,
    generate_codebase_prompt,
    recommend_from_codebase,
    recommend_from_description,
    recommend_from_description_with_llm,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/recommend", tags=["recommend"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class GreenfieldRequest(BaseModel):
    """Request body for greenfield recommendations."""

    description: str


class CodebasePromptRequest(BaseModel):
    """Request body for codebase prompt generation."""

    project_description: str | None = None
    focus_areas: list[str] = Field(default_factory=list)


class FromCodebaseRequest(BaseModel):
    """Request body for codebase-based recommendations."""

    analysis: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_llm_settings(request: Request) -> tuple[dict[str, str], dict[str, str]]:
    """Extract LLM API keys and endpoints from app state."""
    if not hasattr(request.app.state, "llm_settings"):
        return {}, {}
    store = request.app.state.llm_settings
    return store.get("api_keys", {}), store.get("endpoints", {})


def _ensure_domain_cache_initialized(request: Request) -> None:
    """Initialize domain cache storage on first call."""
    if not hasattr(request.app.state, "_domain_cache_initialized"):
        from studio.recommend.domain_cache import init_storage
        config = request.app.state.studio_config
        init_storage(config.workspace_dir)
        request.app.state._domain_cache_initialized = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/greenfield")
async def greenfield_recommend(body: GreenfieldRequest, request: Request) -> dict[str, Any]:
    """Recommend agents and phases from a freeform project description.

    Uses static catalogs first, falls back to LLM generation for unknown domains.
    """
    _ensure_domain_cache_initialized(request)

    try:
        # First try static catalogs + persistent cache (instant)
        result = recommend_from_description(body.description)

        # If no domain was detected (got software dev fallback),
        # try LLM generation for the actual domain
        if not result.detected_domain:
            api_keys, endpoints = _get_llm_settings(request)
            if api_keys:
                llm_result = await recommend_from_description_with_llm(
                    body.description, api_keys, endpoints
                )
                if llm_result and llm_result.agents:
                    return llm_result.model_dump()

        return result.model_dump()
    except Exception as exc:
        logger.error("Greenfield recommendation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/codebase-prompt")
def get_codebase_prompt(body: CodebasePromptRequest) -> dict[str, str]:
    """Generate a prompt the user can paste into their coding assistant."""
    try:
        return generate_codebase_prompt(
            project_description=body.project_description,
            focus_areas=body.focus_areas,
        )
    except Exception as exc:
        logger.error("Codebase prompt generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/from-codebase")
async def codebase_recommend(body: FromCodebaseRequest, request: Request) -> dict[str, Any]:
    """Recommend agents and phases from a codebase analysis JSON.

    Detects domain from project name/description first.
    Falls back to LLM generation if no domain matched, then to software dev mapping.
    """
    _ensure_domain_cache_initialized(request)

    if not body.analysis:
        raise HTTPException(status_code=400, detail="Analysis object is required")
    try:
        result = recommend_from_codebase(body.analysis)

        # If no domain detected, try LLM with project description
        if not result.detected_domain:
            description = body.analysis.get("description", "")
            project_name = body.analysis.get("project_name", "")
            combined = f"{project_name} {description}".strip()
            if combined:
                api_keys, endpoints = _get_llm_settings(request)
                if api_keys:
                    llm_result = await recommend_from_description_with_llm(
                        combined, api_keys, endpoints
                    )
                    if llm_result and llm_result.agents:
                        return llm_result.model_dump()

        return result.model_dump()
    except Exception as exc:
        logger.error("Codebase recommendation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
