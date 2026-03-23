"""Routes for JSON Schema extraction from runtime models.

GET /api/studio/schemas              — all schemas grouped by component
GET /api/studio/schemas/{component}  — schemas for one component
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from studio.schemas.extractor import extract_all_schemas, extract_component_schema
from studio.exceptions import SchemaExtractionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/schemas", tags=["schemas"])


@router.get("", response_model=None)
def get_all_schemas() -> dict[str, dict[str, Any]]:
    """Return JSON schemas for all runtime model components."""
    try:
        return extract_all_schemas()
    except SchemaExtractionError as exc:
        logger.error("Schema extraction failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{component}", response_model=None)
def get_component_schema(component: str) -> dict[str, Any]:
    """Return JSON schemas for a specific component.

    Path parameters:
        component: One of 'agents', 'workflow', 'governance',
                   'workitems', 'app', 'profile'.
    """
    try:
        return extract_component_schema(component)
    except SchemaExtractionError as exc:
        logger.error("Schema extraction failed for '%s': %s", component, exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
