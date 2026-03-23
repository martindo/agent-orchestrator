"""Routes for creating, reading, updating, and managing TeamSpec objects.

POST /api/studio/teams                — create a new team
GET  /api/studio/teams/current        — get the current working team
PUT  /api/studio/teams/current        — update the current working team
POST /api/studio/teams/from-template  — import a team from a template

The Studio backend holds a single "working team" in memory.  All editor
operations read/write this object.  The team is persisted when exported
or deployed.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/teams", tags=["teams"])


class CreateTeamRequest(BaseModel):
    """Request body for creating a new team."""

    name: str
    description: str = ""


class ImportTemplateRequest(BaseModel):
    """Request body for importing from a template."""

    template_path: str


def _get_state(request: Request) -> dict[str, Any]:
    """Get the app-level state dict from the request."""
    return request.app.state.studio_state  # type: ignore[attr-defined]


@router.post("", response_model=None)
def create_team(body: CreateTeamRequest, request: Request) -> dict[str, Any]:
    """Create a new empty team and set it as the current working team."""
    team = TeamSpec(name=body.name, description=body.description)
    state = _get_state(request)
    state["current_team"] = team
    logger.info("Created new team: %s", body.name)
    return team.model_dump()


@router.get("/current", response_model=None)
def get_current_team(request: Request) -> dict[str, Any]:
    """Return the current working team."""
    state = _get_state(request)
    team: TeamSpec | None = state.get("current_team")
    if team is None:
        raise HTTPException(status_code=404, detail="No team loaded. Create or import one first.")
    return team.model_dump()


@router.put("/current", response_model=None)
def update_current_team(body: dict[str, Any], request: Request) -> dict[str, Any]:
    """Replace the current working team with the provided data.

    Accepts a full TeamSpec JSON object and validates it.
    """
    try:
        team = TeamSpec(**body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid team data: {exc}") from exc

    state = _get_state(request)
    state["current_team"] = team
    logger.info("Updated current team: %s", team.name)
    return team.model_dump()


@router.post("/from-template", response_model=None)
def import_from_template(body: ImportTemplateRequest, request: Request) -> dict[str, Any]:
    """Import a team from a profile template directory."""
    from pathlib import Path
    from studio.templates.manager import import_template
    from studio.exceptions import TemplateImportError

    template_path = Path(body.template_path)
    try:
        team = import_template(template_path)
    except TemplateImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = _get_state(request)
    state["current_team"] = team
    logger.info("Imported team from template: %s", template_path)
    return team.model_dump()
