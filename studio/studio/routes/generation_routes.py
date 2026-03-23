"""Routes for YAML generation and preview.

POST /api/studio/generate           — generate all YAML files
POST /api/studio/generate/{component} — generate a single component
GET  /api/studio/preview            — preview all YAML without writing to disk
GET  /api/studio/preview/{component} — preview a single component
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from studio.exceptions import GenerationError
from studio.generation.generator import generate_component_yaml, generate_profile_yaml
from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio", tags=["generation"])


def _require_team(request: Request) -> TeamSpec:
    """Get the current team or raise 404."""
    state = request.app.state.studio_state  # type: ignore[attr-defined]
    team: TeamSpec | None = state.get("current_team")
    if team is None:
        raise HTTPException(status_code=404, detail="No team loaded")
    return team


@router.get("/preview", response_model=None)
def preview_all(request: Request) -> dict[str, str]:
    """Preview all generated YAML files without writing to disk.

    Returns a dict mapping filename to YAML content string.
    """
    team = _require_team(request)
    try:
        return generate_profile_yaml(team)
    except GenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/preview/{component}", response_model=None)
def preview_component(component: str, request: Request) -> dict[str, str]:
    """Preview YAML for a single component.

    Path parameters:
        component: One of 'agents', 'workflow', 'governance', 'workitems', 'app'.
    """
    team = _require_team(request)
    try:
        content = generate_component_yaml(team, component)
        return {"filename": f"{component}.yaml", "content": content}
    except GenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
