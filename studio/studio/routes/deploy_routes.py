"""Routes for deploying profiles to the runtime workspace.

POST /api/studio/deploy — deploy the current team to the runtime
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.config import StudioConfig
from studio.deploy.deployer import deploy_profile, DeployResult
from studio.exceptions import DeploymentError
from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/deploy", tags=["deploy"])


class DeployRequest(BaseModel):
    """Request body for deployment."""

    profile_name: str | None = None
    validate_first: bool = True
    trigger_reload: bool = True
    force: bool = False


def _get_config(request: Request) -> StudioConfig:
    """Get Studio config from app state."""
    return request.app.state.studio_config  # type: ignore[attr-defined]


def _require_team(request: Request) -> TeamSpec:
    """Get the current team or raise 404."""
    state = request.app.state.studio_state  # type: ignore[attr-defined]
    team: TeamSpec | None = state.get("current_team")
    if team is None:
        raise HTTPException(status_code=404, detail="No team loaded")
    return team


def _result_to_dict(result: DeployResult) -> dict[str, Any]:
    """Convert deployment result to JSON-serializable dict."""
    return {
        "success": result.success,
        "profile_dir": str(result.profile_dir),
        "files_written": [str(f) for f in result.files_written],
        "runtime_reloaded": result.runtime_reloaded,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.post("", response_model=None)
def deploy(body: DeployRequest, request: Request) -> dict[str, Any]:
    """Deploy the current working team to the runtime workspace.

    Writes YAML files, validates optionally, and triggers runtime reload.
    """
    team = _require_team(request)
    config = _get_config(request)

    try:
        result = deploy_profile(
            team,
            config,
            profile_name=body.profile_name,
            validate_first=body.validate_first,
            trigger_reload=body.trigger_reload,
            force=body.force,
        )
    except DeploymentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response = _result_to_dict(result)
    if not result.success:
        raise HTTPException(status_code=422, detail=response)

    return response
