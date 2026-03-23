"""Routes for coding-assistant prompt pack generation.

POST /api/studio/prompts/generate — generate a prompt pack for the current team
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.config import StudioConfig
from studio.ir.models import TeamSpec
from studio.prompts.generator import generate_prompt_pack

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/prompts", tags=["prompts"])


class GeneratePromptPackRequest(BaseModel):
    """Request body for prompt pack generation."""

    output_dir: str | None = None
    include_connector: str | None = None


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


@router.post("/generate", response_model=None)
def generate_prompts(body: GeneratePromptPackRequest, request: Request) -> dict[str, Any]:
    """Generate a coding-assistant prompt pack for the current team.

    Creates Markdown prompt files for Claude Code, Cursor, etc.
    """
    team = _require_team(request)
    config = _get_config(request)

    if body.output_dir:
        output_dir = Path(body.output_dir)
    else:
        slug = team.name.lower().replace(" ", "-")
        output_dir = config.resolved_profiles_dir / slug

    pack = generate_prompt_pack(
        team,
        output_dir,
        include_connector=body.include_connector,
    )

    return {
        "prompts": {name: content for name, content in pack.prompts.items()},
        "written": [str(p) for p in pack.written],
        "count": len(pack.prompts),
        "output_dir": str(output_dir),
    }
