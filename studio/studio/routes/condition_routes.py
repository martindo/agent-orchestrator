"""Routes for condition expression building and parsing.

POST /api/studio/conditions/build    — build expression from structured parts
POST /api/studio/conditions/parse    — parse expression into structured parts
POST /api/studio/conditions/validate — validate an expression
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from studio.conditions.builder import (
    SUPPORTED_OPERATORS,
    build_condition,
    parse_condition,
    validate_condition,
)
from studio.exceptions import ConditionParseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/conditions", tags=["conditions"])


class BuildRequest(BaseModel):
    """Request body for building a condition expression."""

    field: str
    operator: str
    value: str


class ParseRequest(BaseModel):
    """Request body for parsing a condition expression."""

    expression: str


class ValidateRequest(BaseModel):
    """Request body for validating a condition expression."""

    expression: str


@router.get("/operators", response_model=None)
def get_operators() -> dict[str, Any]:
    """Return the list of supported condition operators."""
    return {
        "operators": list(SUPPORTED_OPERATORS),
        "descriptions": {
            ">=": "Greater than or equal to",
            "<=": "Less than or equal to",
            "!=": "Not equal to",
            "==": "Equal to",
            ">": "Greater than",
            "<": "Less than",
            "in": "Is contained in list",
        },
    }


@router.post("/build", response_model=None)
def build_condition_route(body: BuildRequest) -> dict[str, Any]:
    """Build a condition expression from field, operator, and value."""
    try:
        expression = build_condition(body.field, body.operator, body.value)
        return {
            "expression": expression,
            "field": body.field,
            "operator": body.operator,
            "value": body.value,
        }
    except ConditionParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/parse", response_model=None)
def parse_condition_route(body: ParseRequest) -> dict[str, Any]:
    """Parse a condition expression into structured parts."""
    try:
        parts = parse_condition(body.expression)
        return {
            "expression": body.expression,
            "field": parts.field,
            "operator": parts.operator,
            "value": parts.value,
        }
    except ConditionParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/validate", response_model=None)
def validate_condition_route(body: ValidateRequest) -> dict[str, Any]:
    """Validate a condition expression for correctness."""
    errors = validate_condition(body.expression)
    return {
        "expression": body.expression,
        "is_valid": len(errors) == 0,
        "errors": errors,
    }
