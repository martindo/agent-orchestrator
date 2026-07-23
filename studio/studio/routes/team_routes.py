"""Routes for creating, reading, updating, and managing TeamSpec objects.

POST /api/studio/teams                — create a new team
GET  /api/studio/teams/current        — get the current working team
PUT  /api/studio/teams/current        — update the current working team
POST /api/studio/teams/from-template  — import a team from a template

The Studio backend holds a single "working team".  All editor operations
read/write this object.  It is also persisted to the workspace
(``current-team.yaml``) on every change and reloaded on demand, so the working
team survives a backend restart (it was previously in-memory only and lost).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/teams", tags=["teams"])

_TEAM_FILE = "current-team.yaml"


def _team_path(request: Request) -> Path | None:
    """Path to the persisted working team, or None if no workspace is set."""
    config = getattr(request.app.state, "studio_config", None)
    workspace = getattr(config, "workspace_dir", None)
    return Path(workspace) / _TEAM_FILE if workspace else None


def _save_current_team(request: Request, team: TeamSpec) -> None:
    """Persist the working team to the workspace (best-effort)."""
    path = _team_path(request)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(team.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        logger.warning("Failed to persist current team: %s", exc)


def _load_current_team(request: Request) -> TeamSpec | None:
    """Load the persisted working team from the workspace, if any."""
    path = _team_path(request)
    if path is None or not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return TeamSpec(**data) if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load current team from %s: %s", path, exc)
        return None


def _set_current_team(request: Request, team: TeamSpec) -> None:
    """Set the working team in memory and persist it."""
    _get_state(request)["current_team"] = team
    _save_current_team(request, team)


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
    _set_current_team(request, team)
    logger.info("Created new team: %s", body.name)
    return team.model_dump()


@router.get("/current", response_model=None)
def get_current_team(request: Request) -> dict[str, Any]:
    """Return the current working team.

    Falls back to the persisted team on disk (e.g. after a restart) before
    reporting that none is loaded.
    """
    state = _get_state(request)
    team: TeamSpec | None = state.get("current_team")
    if team is None:
        team = _load_current_team(request)
        if team is not None:
            state["current_team"] = team
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

    _set_current_team(request, team)
    logger.info("Updated current team: %s", team.name)
    return team.model_dump()


@router.post("/from-template", response_model=None)
def import_from_template(body: ImportTemplateRequest, request: Request) -> dict[str, Any]:
    """Import a team from a profile template directory."""
    from studio.templates.manager import import_template
    from studio.exceptions import TemplateImportError

    template_path = Path(body.template_path)
    try:
        team = import_template(template_path)
    except TemplateImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _set_current_team(request, team)
    logger.info("Imported team from template: %s", template_path)
    return team.model_dump()
