"""Routes for extension stub generation.

POST /api/studio/extensions/connector      — generate a connector provider stub
POST /api/studio/extensions/event-handler  — generate an event handler stub
POST /api/studio/extensions/hook           — generate a phase context hook stub
POST /api/studio/extensions/all            — generate all stubs for current team
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.config import StudioConfig
from studio.exceptions import ExtensionStubError
from studio.extensions.generator import (
    generate_all_stubs,
    generate_connector_stub,
    generate_event_handler_stub,
    generate_hook_stub,
)
from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/extensions", tags=["extensions"])


class ConnectorStubRequest(BaseModel):
    """Request body for connector stub generation."""

    provider_id: str
    display_name: str
    capability: str = "EXTERNAL_API"
    write_to_disk: bool = False
    output_dir: str | None = None


class EventHandlerStubRequest(BaseModel):
    """Request body for event handler stub generation."""

    handler_name: str
    event_types: list[str] | None = None
    write_to_disk: bool = False
    output_dir: str | None = None


class HookStubRequest(BaseModel):
    """Request body for hook stub generation."""

    phase_id: str
    hook_name: str | None = None
    write_to_disk: bool = False
    output_dir: str | None = None


class GenerateAllRequest(BaseModel):
    """Request body for generating all stubs."""

    output_dir: str | None = None
    force: bool = False


def _get_config(request: Request) -> StudioConfig:
    """Get Studio config from app state."""
    return request.app.state.studio_config  # type: ignore[attr-defined]


def _require_team(request: Request) -> TeamSpec:
    """Get current team or raise 404."""
    state = request.app.state.studio_state  # type: ignore[attr-defined]
    team: TeamSpec | None = state.get("current_team")
    if team is None:
        raise HTTPException(status_code=404, detail="No team loaded")
    return team


@router.post("/connector", response_model=None)
def generate_connector(body: ConnectorStubRequest, request: Request) -> dict[str, Any]:
    """Generate a connector provider Python stub."""
    code = generate_connector_stub(body.provider_id, body.display_name, body.capability)
    result: dict[str, Any] = {
        "provider_id": body.provider_id,
        "code": code,
        "written": False,
    }

    if body.write_to_disk and body.output_dir:
        output_path = Path(body.output_dir) / "extensions" / "connectors" / f"{body.provider_id}.py"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(code, encoding="utf-8")
        result["written"] = True
        result["path"] = str(output_path)

    return result


@router.post("/event-handler", response_model=None)
def generate_event_handler(body: EventHandlerStubRequest, request: Request) -> dict[str, Any]:
    """Generate an event handler Python stub."""
    code = generate_event_handler_stub(body.handler_name, body.event_types)
    result: dict[str, Any] = {
        "handler_name": body.handler_name,
        "code": code,
        "written": False,
    }

    if body.write_to_disk and body.output_dir:
        safe_name = body.handler_name.replace("-", "_")
        output_path = Path(body.output_dir) / "extensions" / "handlers" / f"{safe_name}.py"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(code, encoding="utf-8")
        result["written"] = True
        result["path"] = str(output_path)

    return result


@router.post("/hook", response_model=None)
def generate_hook(body: HookStubRequest, request: Request) -> dict[str, Any]:
    """Generate a phase context hook Python stub."""
    code = generate_hook_stub(body.phase_id, body.hook_name)
    result: dict[str, Any] = {
        "phase_id": body.phase_id,
        "code": code,
        "written": False,
    }

    if body.write_to_disk and body.output_dir:
        name = body.hook_name or f"hook_{body.phase_id}"
        output_path = Path(body.output_dir) / "extensions" / "hooks" / f"{name}.py"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(code, encoding="utf-8")
        result["written"] = True
        result["path"] = str(output_path)

    return result


@router.post("/all", response_model=None)
def generate_all_extensions(body: GenerateAllRequest, request: Request) -> dict[str, Any]:
    """Generate all extension stubs for the current team."""
    team = _require_team(request)
    config = _get_config(request)

    output_dir = Path(body.output_dir) if body.output_dir else config.resolved_profiles_dir / team.name.lower().replace(" ", "-")

    try:
        result = generate_all_stubs(team, output_dir, force=body.force)
    except ExtensionStubError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "files": result.files,
        "written": [str(p) for p in result.written],
        "skipped": result.skipped,
        "output_dir": str(output_dir),
    }
