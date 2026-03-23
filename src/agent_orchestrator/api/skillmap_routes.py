"""REST API routes for the organizational skill map.

Provides CRUD, metric recording, coverage analysis, and agent profiling
for the live skill registry.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent_orchestrator.catalog.skill_models import SkillMaturity

logger = logging.getLogger(__name__)

skillmap_router = APIRouter()


# ---- Request Models ----


class RegisterSkillRequest(BaseModel):
    """Request body for registering a skill."""

    skill_id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    agent_ids: list[str] = Field(default_factory=list)
    phase_ids: list[str] = Field(default_factory=list)
    knowledge_sources: list[str] = Field(default_factory=list)


class RecordExecutionRequest(BaseModel):
    """Request body for recording a skill execution."""

    agent_id: str
    success: bool
    confidence: float = 0.0
    duration_seconds: float = 0.0


# ---- Helpers ----


def _get_skill_map(request: Request) -> Any:
    """Extract SkillMap from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The SkillMap instance.

    Raises:
        HTTPException: 503 if unavailable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    skill_map = getattr(engine, "skill_map", None)
    if skill_map is None:
        raise HTTPException(status_code=503, detail="Skill map not initialized")
    return skill_map


def _serialize_skill(skill: Any) -> dict[str, Any]:
    """Serialize a SkillRecord to a JSON-compatible dict.

    Args:
        skill: The SkillRecord to serialize.

    Returns:
        Serialized skill data.
    """
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "tags": skill.tags,
        "agent_ids": skill.agent_ids,
        "phase_ids": skill.phase_ids,
        "knowledge_sources": skill.knowledge_sources,
        "metrics": {
            "total_executions": skill.metrics.total_executions,
            "successful_executions": skill.metrics.successful_executions,
            "failed_executions": skill.metrics.failed_executions,
            "success_rate": skill.metrics.success_rate,
            "average_confidence": skill.metrics.average_confidence,
            "average_duration": skill.metrics.average_duration,
            "maturity": skill.metrics.maturity.value,
        },
        "agent_metrics": {
            agent_id: {
                "total_executions": am.total_executions,
                "success_rate": am.success_rate,
                "average_confidence": am.average_confidence,
                "maturity": am.maturity.value,
            }
            for agent_id, am in skill.agent_metrics.items()
        },
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


# ---- Routes ----


@skillmap_router.get("/skills/coverage/report")
async def get_coverage(request: Request) -> dict[str, Any]:
    """Get organizational skill coverage report.

    Identifies strong, weak, and unassigned skill areas.

    Returns:
        Coverage analysis with maturity distribution.
    """
    skill_map = _get_skill_map(request)
    coverage = skill_map.get_coverage()
    return {
        "total_skills": coverage.total_skills,
        "covered_skills": coverage.covered_skills,
        "coverage_ratio": coverage.coverage_ratio,
        "weak_skills": coverage.weak_skills,
        "strong_skills": coverage.strong_skills,
        "unassigned_skills": coverage.unassigned_skills,
        "maturity_distribution": coverage.maturity_distribution,
    }


@skillmap_router.get("/skills/agent/{agent_id}/profile")
async def get_agent_profile(
    agent_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get a performance profile for a specific agent across all skills.

    Args:
        agent_id: The agent to profile.
        request: The incoming HTTP request.

    Returns:
        Agent's skill performance profile.
    """
    skill_map = _get_skill_map(request)
    return skill_map.get_agent_profile(agent_id)


@skillmap_router.get("/skills/summary")
async def skill_summary(request: Request) -> dict[str, Any]:
    """Return summary statistics for the skill map.

    Returns:
        Summary with coverage and maturity breakdown.
    """
    skill_map = _get_skill_map(request)
    return skill_map.summary()


@skillmap_router.get("/skills")
async def list_skills(
    request: Request,
    tags: str | None = None,
    agent_id: str | None = None,
    min_success_rate: float | None = None,
    maturity: str | None = None,
) -> list[dict[str, Any]]:
    """List/discover skills with optional filters.

    Args:
        request: The incoming HTTP request.
        tags: Comma-separated tag filter.
        agent_id: Filter by agent providing the skill.
        min_success_rate: Minimum success rate filter.
        maturity: Maturity level filter.

    Returns:
        List of matching skills.
    """
    skill_map = _get_skill_map(request)

    parsed_tags: list[str] | None = None
    if tags:
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

    parsed_maturity: SkillMaturity | None = None
    if maturity:
        try:
            parsed_maturity = SkillMaturity(maturity.lower())
        except ValueError:
            valid = [m.value for m in SkillMaturity]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid maturity '{maturity}'. Valid: {valid}",
            )

    results = skill_map.find_skills(
        tags=parsed_tags,
        agent_id=agent_id,
        min_success_rate=min_success_rate,
        maturity=parsed_maturity,
    )
    return [_serialize_skill(s) for s in results]


@skillmap_router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, request: Request) -> dict[str, Any]:
    """Get a skill by ID.

    Args:
        skill_id: The skill identifier.
        request: The incoming HTTP request.

    Returns:
        Serialized skill record.
    """
    skill_map = _get_skill_map(request)
    skill = skill_map.get_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return _serialize_skill(skill)


@skillmap_router.post("/skills", status_code=201)
async def register_skill(
    body: RegisterSkillRequest,
    request: Request,
) -> dict[str, Any]:
    """Register a new skill.

    Args:
        body: Skill registration data.
        request: The incoming HTTP request.

    Returns:
        Serialized registered skill.
    """
    skill_map = _get_skill_map(request)

    from agent_orchestrator.catalog.skill_models import SkillRecord

    skill = SkillRecord(
        skill_id=body.skill_id,
        name=body.name,
        description=body.description,
        tags=body.tags,
        agent_ids=body.agent_ids,
        phase_ids=body.phase_ids,
        knowledge_sources=body.knowledge_sources,
    )
    skill_map.register_skill(skill)
    logger.info("Registered skill via API: %s", body.skill_id)
    return _serialize_skill(skill)


@skillmap_router.delete("/skills/{skill_id}")
async def unregister_skill(skill_id: str, request: Request) -> dict[str, bool]:
    """Unregister a skill by ID.

    Args:
        skill_id: The skill to remove.
        request: The incoming HTTP request.

    Returns:
        Confirmation dict.
    """
    skill_map = _get_skill_map(request)
    removed = skill_map.unregister_skill(skill_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return {"deleted": True}


@skillmap_router.post("/skills/{skill_id}/record")
async def record_execution(
    skill_id: str,
    body: RecordExecutionRequest,
    request: Request,
) -> dict[str, Any]:
    """Record an execution observation against a skill.

    Args:
        skill_id: The skill being exercised.
        body: Execution observation data.
        request: The incoming HTTP request.

    Returns:
        Updated skill summary.
    """
    skill_map = _get_skill_map(request)
    updated = skill_map.record_execution(
        skill_id,
        body.agent_id,
        success=body.success,
        confidence=body.confidence,
        duration_seconds=body.duration_seconds,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    skill = skill_map.get_skill(skill_id)
    return _serialize_skill(skill)
