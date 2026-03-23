"""Routes for profile validation.

POST /api/studio/validate           — validate the current team (Studio-side)
POST /api/studio/validate/runtime   — validate via runtime integration
POST /api/studio/validate/condition — validate a single condition expression
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studio.conditions.builder import validate_condition
from studio.ir.models import TeamSpec
from studio.validation.validator import (
    StudioValidationResult,
    validate_team,
    validate_team_via_runtime,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/validate", tags=["validation"])


class ConditionValidateRequest(BaseModel):
    """Request body for validating a condition expression."""

    expression: str


def _require_team(request: Request) -> TeamSpec:
    """Get the current team or raise 404."""
    state = request.app.state.studio_state  # type: ignore[attr-defined]
    team: TeamSpec | None = state.get("current_team")
    if team is None:
        raise HTTPException(status_code=404, detail="No team loaded")
    return team


def _result_to_dict(result: StudioValidationResult) -> dict[str, Any]:
    """Convert validation result to a JSON-serializable dict."""
    return {
        "is_valid": result.is_valid,
        "errors": [
            {"message": msg.message, "path": msg.path, "severity": msg.severity}
            for msg in result.errors
        ],
        "warnings": [
            {"message": msg.message, "path": msg.path, "severity": msg.severity}
            for msg in result.warnings
        ],
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
    }


@router.post("", response_model=None)
def validate_current_team(request: Request) -> dict[str, Any]:
    """Run Studio-side structural validation on the current team.

    Fast validation that doesn't require the runtime to be running.
    """
    team = _require_team(request)
    result = validate_team(team)
    return _result_to_dict(result)


@router.post("/runtime", response_model=None)
def validate_via_runtime(request: Request) -> dict[str, Any]:
    """Run full validation including runtime cross-reference checks.

    Converts IR → ProfileConfig and calls the runtime's validate_profile().
    Falls back to Studio-side validation if the runtime is not installed.
    """
    team = _require_team(request)
    result = validate_team_via_runtime(team)
    return _result_to_dict(result)


@router.post("/condition", response_model=None)
def validate_condition_expression(body: ConditionValidateRequest) -> dict[str, Any]:
    """Validate a single condition expression.

    Returns validation errors for the expression, or an empty list if valid.
    """
    errors = validate_condition(body.expression)
    return {
        "expression": body.expression,
        "is_valid": len(errors) == 0,
        "errors": errors,
    }
