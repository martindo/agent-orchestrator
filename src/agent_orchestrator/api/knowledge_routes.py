"""REST API routes for the knowledge subsystem.

Provides CRUD operations on memory records stored in the KnowledgeStore,
including querying, storing, soft-deleting, versioning, and statistics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent_orchestrator.knowledge.models import MemoryQuery, MemoryRecord, MemoryType

logger = logging.getLogger(__name__)

knowledge_router = APIRouter()


# ---- Request/Response Models ----


class StoreMemoryRequest(BaseModel):
    """Request body for creating a new memory record."""

    type: str
    title: str
    content: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.8
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoreMemoryResponse(BaseModel):
    """Response after storing a memory record."""

    memory_id: str
    content_hash: str


class DeleteMemoryResponse(BaseModel):
    """Response after soft-deleting a memory record."""

    deleted: bool = True


# ---- Helpers ----


def _get_knowledge_store(request: Request) -> Any:
    """Extract KnowledgeStore from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The KnowledgeStore instance.

    Raises:
        HTTPException: 503 if engine or knowledge_store is not available.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    store = getattr(engine, "knowledge_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Knowledge store not initialized")
    return store


def _serialize_record(record: MemoryRecord) -> dict[str, Any]:
    """Serialize a MemoryRecord to a JSON-compatible dict.

    Args:
        record: The MemoryRecord to serialize.

    Returns:
        Dictionary with all fields serialized for JSON output.
    """
    return {
        "memory_id": record.memory_id,
        "memory_type": record.memory_type.value,
        "title": record.title,
        "content": record.content,
        "content_hash": record.content_hash,
        "tags": record.tags,
        "confidence": record.confidence,
        "source_agent_id": record.source_agent_id,
        "source_work_id": record.source_work_id,
        "source_phase_id": record.source_phase_id,
        "source_run_id": record.source_run_id,
        "app_id": record.app_id,
        "timestamp": record.timestamp.isoformat(),
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "superseded_by": record.superseded_by,
        "version": record.version,
        "metadata": record.metadata,
    }


def _compute_content_hash(content: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash of the content dict.

    Args:
        content: The content dictionary to hash.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    serialized = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _resolve_memory_type(type_str: str) -> MemoryType:
    """Parse a string into a MemoryType enum value.

    Args:
        type_str: The type string (e.g., "evidence", "decision").

    Returns:
        The corresponding MemoryType enum member.

    Raises:
        HTTPException: 400 if the type string is not a valid MemoryType.
    """
    try:
        return MemoryType(type_str.lower())
    except ValueError:
        valid = [t.value for t in MemoryType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid memory type '{type_str}'. Valid types: {valid}",
        )


# ---- Routes ----


@knowledge_router.get("/knowledge/stats")
async def get_knowledge_stats(request: Request) -> dict[str, Any]:
    """Return count and summary statistics grouped by memory type."""
    store = _get_knowledge_store(request)
    stats = store.stats()
    return stats


@knowledge_router.get("/knowledge")
async def query_knowledge(
    request: Request,
    type: str | None = None,
    tags: str | None = None,
    keywords: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Query memory records with optional filters.

    Args:
        request: The incoming HTTP request.
        type: Optional memory type filter.
        tags: Optional comma-separated tag filter.
        keywords: Optional comma-separated keyword filter.
        min_confidence: Minimum confidence threshold (default 0.0).
        limit: Maximum number of records to return (default 20).

    Returns:
        List of serialized memory records matching the query.
    """
    store = _get_knowledge_store(request)

    memory_type: MemoryType | None = None
    if type is not None:
        memory_type = _resolve_memory_type(type)

    parsed_tags: list[str] | None = None
    if tags is not None:
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

    parsed_keywords: list[str] | None = None
    if keywords is not None:
        parsed_keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    query = MemoryQuery(
        memory_type=memory_type,
        tags=parsed_tags,
        keywords=parsed_keywords,
        min_confidence=min_confidence,
        limit=limit,
    )

    records = store.retrieve(query)
    return [_serialize_record(r) for r in records]


@knowledge_router.post("/knowledge")
async def store_memory(
    request: Request,
    body: StoreMemoryRequest,
) -> StoreMemoryResponse:
    """Store a new memory record explicitly.

    Args:
        request: The incoming HTTP request.
        body: The memory record data to store.

    Returns:
        The ID and content hash of the stored record.
    """
    store = _get_knowledge_store(request)

    memory_type = _resolve_memory_type(body.type)
    memory_id = str(uuid.uuid4())
    content_hash = _compute_content_hash(body.content)

    record = MemoryRecord(
        memory_id=memory_id,
        memory_type=memory_type,
        title=body.title,
        content=body.content,
        content_hash=content_hash,
        tags=body.tags,
        confidence=body.confidence,
        source_agent_id="api",
        source_work_id="",
        source_phase_id="",
        source_run_id="",
        app_id="",
        metadata=body.metadata,
    )

    store.store(record)
    logger.info("Stored memory record %s (type=%s)", memory_id, memory_type.value)

    return StoreMemoryResponse(memory_id=memory_id, content_hash=content_hash)


@knowledge_router.get("/knowledge/{memory_id}")
async def get_memory(memory_id: str, request: Request) -> dict[str, Any]:
    """Retrieve a single memory record by ID.

    Args:
        memory_id: The unique identifier of the memory record.
        request: The incoming HTTP request.

    Returns:
        Serialized memory record.

    Raises:
        HTTPException: 404 if the record is not found.
    """
    store = _get_knowledge_store(request)
    record = store.get(memory_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")
    return _serialize_record(record)


@knowledge_router.delete("/knowledge/{memory_id}")
async def delete_memory(memory_id: str, request: Request) -> DeleteMemoryResponse:
    """Soft-delete a memory record by ID.

    Args:
        memory_id: The unique identifier of the memory record to delete.
        request: The incoming HTTP request.

    Returns:
        Confirmation that the record was deleted.

    Raises:
        HTTPException: 404 if the record is not found.
    """
    store = _get_knowledge_store(request)
    deleted = store.delete(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")
    logger.info("Soft-deleted memory record %s", memory_id)
    return DeleteMemoryResponse(deleted=True)


@knowledge_router.post("/knowledge/{memory_id}/supersede")
async def supersede_memory(
    memory_id: str,
    request: Request,
    body: StoreMemoryRequest,
) -> StoreMemoryResponse:
    """Create a new version of a memory record, superseding the original.

    The old record's superseded_by field is set to the new record's ID.

    Args:
        memory_id: The ID of the memory record to supersede.
        request: The incoming HTTP request.
        body: The new memory record data.

    Returns:
        The ID and content hash of the new record.

    Raises:
        HTTPException: 404 if the original record is not found.
    """
    store = _get_knowledge_store(request)

    memory_type = _resolve_memory_type(body.type)
    new_id = str(uuid.uuid4())
    content_hash = _compute_content_hash(body.content)

    new_record = MemoryRecord(
        memory_id=new_id,
        memory_type=memory_type,
        title=body.title,
        content=body.content,
        content_hash=content_hash,
        tags=body.tags,
        confidence=body.confidence,
        source_agent_id="api",
        source_work_id="",
        source_phase_id="",
        source_run_id="",
        app_id="",
        metadata=body.metadata,
    )

    result = store.supersede(memory_id, new_record)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Memory '{memory_id}' not found — cannot supersede",
        )

    logger.info(
        "Superseded memory %s with new record %s", memory_id, new_id,
    )
    return StoreMemoryResponse(memory_id=new_id, content_hash=content_hash)
