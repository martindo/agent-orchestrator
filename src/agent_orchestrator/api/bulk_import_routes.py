"""Bulk import routes — Import work items from JSON or CSV.

Supports three import methods:
- JSON body with items array
- CSV file upload
- JSON file upload

Also provides a CSV template download for convenience.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

bulk_router = APIRouter()


class BulkImportRequest(BaseModel):
    """Request body for JSON bulk import."""

    items: list[dict[str, Any]] = Field(default_factory=list)


class BulkImportResult(BaseModel):
    """Response for bulk import operations."""

    success: bool
    imported: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    total_submitted: int
    source: str = "json"
    filename: str | None = None


async def _import_items(items: list[dict[str, Any]], engine: Any) -> BulkImportResult:
    """Core import logic shared by all import endpoints.

    Args:
        items: List of work item dicts.
        engine: OrchestrationEngine instance.

    Returns:
        BulkImportResult with counts and errors.
    """
    from agent_orchestrator.core.work_queue import WorkItem

    imported = 0
    errors: list[dict[str, Any]] = []

    for i, item in enumerate(items):
        try:
            if not item.get("title"):
                errors.append({"index": i, "error": "Missing title"})
                continue

            item_id = item.get("id") or f"bulk-{i}-{int(time.time())}"
            type_id = item.get("type_id", "default")

            work_item = WorkItem(
                id=item_id,
                type_id=type_id,
                title=item["title"],
                data=item.get("data", {}),
                priority=int(item.get("priority", 5)),
                app_id=item.get("app_id", "default"),
                urgency=item.get("urgency", ""),
                routing_tags=item.get("routing_tags", []),
            )

            await engine.submit_work(work_item)
            imported += 1
        except ValueError as e:
            errors.append({"index": i, "error": str(e)})
        except Exception as e:
            errors.append({"index": i, "error": str(e)})

    logger.info("Bulk import: %d imported, %d errors", imported, len(errors))
    return BulkImportResult(
        success=True,
        imported=imported,
        errors=errors,
        total_submitted=len(items),
    )


def _get_engine(request: Request) -> Any:
    """Get the OrchestrationEngine from request state."""
    return getattr(request.app.state, "engine", None)


@bulk_router.post("/bulk/import", response_model=BulkImportResult)
async def bulk_import(body: BulkImportRequest, request: Request) -> BulkImportResult:
    """Import work items from a JSON array."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    if not body.items:
        return BulkImportResult(
            success=False, imported=0, errors=[], total_submitted=0,
        )

    result = await _import_items(body.items, engine)
    result.source = "json"
    return result


@bulk_router.post("/bulk/import/csv", response_model=BulkImportResult)
async def bulk_import_csv(request: Request, file: UploadFile = File(...)) -> BulkImportResult:
    """Import work items from a CSV file.

    Expected columns: id (optional), title, description, type_id, priority, skill_required
    """
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded") from e

    reader = csv.DictReader(io.StringIO(text))
    reserved_keys = frozenset({"id", "title", "description", "type_id", "priority"})

    items: list[dict[str, Any]] = []
    for row in reader:
        priority_raw = row.get("priority", "5")
        try:
            priority = int(priority_raw)
        except (ValueError, TypeError):
            priority = 5

        item: dict[str, Any] = {
            "id": row.get("id") or f"csv-{len(items)}",
            "title": row.get("title", ""),
            "type_id": row.get("type_id", "default"),
            "priority": priority,
            "data": {
                "description": row.get("description", ""),
                **{k: v for k, v in row.items() if k not in reserved_keys},
            },
        }
        if item["title"]:
            items.append(item)

    result = await _import_items(items, engine)
    result.source = "csv"
    result.filename = file.filename
    return result


@bulk_router.post("/bulk/import/json-file", response_model=BulkImportResult)
async def bulk_import_json_file(request: Request, file: UploadFile = File(...)) -> BulkImportResult:
    """Import work items from a JSON file."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON file") from e

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items", data.get("work_items", []))
    else:
        raise HTTPException(status_code=400, detail="Expected JSON array or object with 'items' key")

    result = await _import_items(items, engine)
    result.source = "json_file"
    result.filename = file.filename
    return result


@bulk_router.get("/bulk/template/csv")
async def get_csv_template() -> StreamingResponse:
    """Download a CSV template for bulk import."""
    template = "id,title,description,type_id,priority,skill_required\n"
    template += 'item-1,"Build login page","Implement OAuth login flow",content,5,frontend\n'
    template += 'item-2,"Add API endpoint","Create REST endpoint for users",content,3,backend\n'

    return StreamingResponse(
        io.BytesIO(template.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=work-items-template.csv"},
    )
