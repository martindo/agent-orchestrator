"""Routes for template import/export.

GET  /api/studio/templates           — list available templates
POST /api/studio/templates/import    — import a template into the working team
POST /api/studio/templates/export    — export the current team to a template dir
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.config import StudioConfig
from studio.exceptions import TemplateExportError, TemplateImportError
from studio.ir.models import TeamSpec
from studio.templates.manager import export_template, import_template, list_templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/templates", tags=["templates"])


class ImportRequest(BaseModel):
    """Request body for template import."""

    template_name: str | None = None
    template_path: str | None = None


class ExportRequest(BaseModel):
    """Request body for template export."""

    output_name: str | None = None
    output_path: str | None = None


def _get_config(request: Request) -> StudioConfig:
    """Get Studio config from app state."""
    return request.app.state.studio_config  # type: ignore[attr-defined]


def _get_state(request: Request) -> dict[str, Any]:
    """Get the app-level state dict."""
    return request.app.state.studio_state  # type: ignore[attr-defined]


@router.get("", response_model=None)
def get_templates(request: Request) -> dict[str, Any]:
    """List available profile templates in the profiles directory."""
    config = _get_config(request)
    templates = list_templates(config.resolved_profiles_dir)
    return {
        "templates": templates,
        "count": len(templates),
        "profiles_dir": str(config.resolved_profiles_dir),
    }


@router.post("/import", response_model=None)
def import_template_route(body: ImportRequest, request: Request) -> dict[str, Any]:
    """Import a template into the current working team.

    Either provide ``template_name`` (looked up in profiles dir) or
    ``template_path`` (absolute path to a profile directory).
    """
    config = _get_config(request)

    if body.template_path:
        profile_dir = Path(body.template_path)
    elif body.template_name:
        profile_dir = config.resolved_profiles_dir / body.template_name
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either template_name or template_path",
        )

    try:
        team = import_template(profile_dir)
    except TemplateImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = _get_state(request)
    state["current_team"] = team
    logger.info("Imported template from %s", profile_dir)
    return team.model_dump()


@router.post("/export", response_model=None)
def export_template_route(body: ExportRequest, request: Request) -> dict[str, Any]:
    """Export the current working team as a profile template.

    Writes YAML files to the specified or default output directory.
    """
    config = _get_config(request)
    state = _get_state(request)
    team: TeamSpec | None = state.get("current_team")
    if team is None:
        raise HTTPException(status_code=404, detail="No team loaded")

    if body.output_path:
        output_dir = Path(body.output_path)
    else:
        name = body.output_name or team.name.lower().replace(" ", "-")
        output_dir = config.resolved_profiles_dir / name

    try:
        files = export_template(team, output_dir)
    except TemplateExportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "output_dir": str(output_dir),
        "files": [str(f) for f in files],
        "count": len(files),
    }
