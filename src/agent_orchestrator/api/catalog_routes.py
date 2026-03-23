"""REST API routes for the capability catalog.

Provides CRUD operations on capability registrations and an invoke
endpoint that creates work items through the engine.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent_orchestrator.catalog.models import (
    CapabilityRegistration,
    InvocationMode,
    MemoryUsagePolicy,
    SecurityClassification,
)
from agent_orchestrator.catalog.registry import TeamRegistry
from agent_orchestrator.contracts.models import LifecycleState
from agent_orchestrator.core.event_bus import Event, EventType

logger = logging.getLogger(__name__)

catalog_router = APIRouter()


# ---- Request/Response Models ----


class RegisterCapabilityRequest(BaseModel):
    """Request body for registering a capability."""

    capability_id: str
    display_name: str
    description: str = ""
    owner: str = ""
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    profile_name: str
    deployment_mode: str = "lite"
    required_connectors: list[str] = Field(default_factory=list)
    security_classification: str = "internal"
    approval_requirements: list[str] = Field(default_factory=list)
    review_required_below: float = 0.5
    memory_usage_policy: str = "none"
    invocation_modes: list[str] = Field(default_factory=lambda: ["async"])
    status: str = "draft"
    metadata: dict = Field(default_factory=dict)


class UpdateCapabilityRequest(BaseModel):
    """Request body for updating a capability (partial update)."""

    display_name: str | None = None
    description: str | None = None
    owner: str | None = None
    version: str | None = None
    tags: list[str] | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    deployment_mode: str | None = None
    required_connectors: list[str] | None = None
    security_classification: str | None = None
    approval_requirements: list[str] | None = None
    review_required_below: float | None = None
    memory_usage_policy: str | None = None
    invocation_modes: list[str] | None = None
    status: str | None = None
    metadata: dict | None = None


class InvokeRequest(BaseModel):
    """Request body for invoking a capability."""

    input: dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    priority: int = 0
    app_id: str = ""


class InvokeResponse(BaseModel):
    """Response after invoking a capability."""

    work_id: str
    capability_id: str
    status: str


# ---- Helpers ----


def _get_team_registry(request: Request) -> TeamRegistry:
    """Extract TeamRegistry from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The TeamRegistry instance.

    Raises:
        HTTPException: 503 if engine or team_registry is not available.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    registry = getattr(engine, "team_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Team registry not initialized")
    return registry


def _serialize_registration(reg: CapabilityRegistration) -> dict[str, Any]:
    """Serialize a CapabilityRegistration to a JSON-compatible dict.

    Args:
        reg: The registration to serialize.

    Returns:
        Dictionary with all fields serialized for JSON output.
    """
    return {
        "capability_id": reg.capability_id,
        "display_name": reg.display_name,
        "description": reg.description,
        "owner": reg.owner,
        "version": reg.version,
        "tags": reg.tags,
        "input_schema": reg.input_schema,
        "output_schema": reg.output_schema,
        "profile_name": reg.profile_name,
        "deployment_mode": reg.deployment_mode,
        "required_connectors": reg.required_connectors,
        "security_classification": reg.security_classification.value,
        "approval_requirements": reg.approval_requirements,
        "review_required_below": reg.review_required_below,
        "memory_usage_policy": reg.memory_usage_policy.value,
        "invocation_modes": [m.value for m in reg.invocation_modes],
        "status": reg.status.value,
        "registered_at": reg.registered_at.isoformat(),
        "updated_at": reg.updated_at.isoformat(),
        "metadata": reg.metadata,
    }


def _parse_enum(value: str, enum_cls: type, field_name: str) -> Any:
    """Parse a string into an enum, raising 400 on failure.

    Args:
        value: The string to parse.
        enum_cls: The enum class.
        field_name: Field name for error messages.

    Returns:
        The parsed enum member.
    """
    try:
        return enum_cls(value.lower())
    except ValueError:
        valid = [e.value for e in enum_cls]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} '{value}'. Valid: {valid}",
        )


# ---- Routes ----


@catalog_router.get("/catalog/capabilities")
async def list_capabilities(
    request: Request,
    tags: str | None = None,
    status: str | None = None,
    profile_name: str | None = None,
) -> list[dict[str, Any]]:
    """List/discover capabilities with optional filters.

    Args:
        request: The incoming HTTP request.
        tags: Optional comma-separated tag filter.
        status: Optional lifecycle state filter.
        profile_name: Optional profile name filter.

    Returns:
        List of serialized capability registrations.
    """
    registry = _get_team_registry(request)

    parsed_tags: list[str] | None = None
    if tags is not None:
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

    parsed_status: LifecycleState | None = None
    if status is not None:
        parsed_status = _parse_enum(status, LifecycleState, "status")

    results = registry.find(
        tags=parsed_tags,
        status=parsed_status,
        profile_name=profile_name,
    )
    return [_serialize_registration(r) for r in results]


@catalog_router.get("/catalog/capabilities/{capability_id}")
async def get_capability(
    capability_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get a capability by ID.

    Args:
        capability_id: The unique capability identifier.
        request: The incoming HTTP request.

    Returns:
        Serialized capability registration.
    """
    registry = _get_team_registry(request)
    reg = registry.get(capability_id)
    if reg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Capability '{capability_id}' not found",
        )
    return _serialize_registration(reg)


@catalog_router.post("/catalog/capabilities", status_code=201)
async def register_capability(
    body: RegisterCapabilityRequest,
    request: Request,
) -> dict[str, Any]:
    """Register a new capability explicitly.

    Args:
        body: The capability registration data.
        request: The incoming HTTP request.

    Returns:
        Serialized capability registration.
    """
    registry = _get_team_registry(request)
    now = datetime.now(timezone.utc)

    registration = CapabilityRegistration(
        capability_id=body.capability_id,
        display_name=body.display_name,
        description=body.description,
        owner=body.owner,
        version=body.version,
        tags=body.tags,
        input_schema=body.input_schema,
        output_schema=body.output_schema,
        profile_name=body.profile_name,
        deployment_mode=body.deployment_mode,
        required_connectors=body.required_connectors,
        security_classification=_parse_enum(
            body.security_classification, SecurityClassification, "security_classification",
        ),
        approval_requirements=body.approval_requirements,
        review_required_below=body.review_required_below,
        memory_usage_policy=_parse_enum(
            body.memory_usage_policy, MemoryUsagePolicy, "memory_usage_policy",
        ),
        invocation_modes=[
            _parse_enum(m, InvocationMode, "invocation_mode")
            for m in body.invocation_modes
        ],
        status=_parse_enum(body.status, LifecycleState, "status"),
        registered_at=now,
        updated_at=now,
        metadata=body.metadata,
    )

    registry.register(registration)

    # Emit event
    engine = getattr(request.app.state, "engine", None)
    if engine is not None:
        await engine.event_bus.emit(Event(
            type=EventType.CAPABILITY_REGISTERED,
            data={"capability_id": registration.capability_id},
            source="catalog_api",
        ))

    logger.info("Registered capability via API: %s", registration.capability_id)
    return _serialize_registration(registration)


@catalog_router.put("/catalog/capabilities/{capability_id}")
async def update_capability(
    capability_id: str,
    body: UpdateCapabilityRequest,
    request: Request,
) -> dict[str, Any]:
    """Update an existing capability registration.

    Args:
        capability_id: The capability to update.
        body: Fields to update.
        request: The incoming HTTP request.

    Returns:
        Serialized updated capability registration.
    """
    registry = _get_team_registry(request)
    existing = registry.get(capability_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Capability '{capability_id}' not found",
        )

    # Build update dict from provided fields
    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}

    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.description is not None:
        updates["description"] = body.description
    if body.owner is not None:
        updates["owner"] = body.owner
    if body.version is not None:
        updates["version"] = body.version
    if body.tags is not None:
        updates["tags"] = body.tags
    if body.input_schema is not None:
        updates["input_schema"] = body.input_schema
    if body.output_schema is not None:
        updates["output_schema"] = body.output_schema
    if body.deployment_mode is not None:
        updates["deployment_mode"] = body.deployment_mode
    if body.required_connectors is not None:
        updates["required_connectors"] = body.required_connectors
    if body.security_classification is not None:
        updates["security_classification"] = _parse_enum(
            body.security_classification, SecurityClassification, "security_classification",
        )
    if body.approval_requirements is not None:
        updates["approval_requirements"] = body.approval_requirements
    if body.review_required_below is not None:
        updates["review_required_below"] = body.review_required_below
    if body.memory_usage_policy is not None:
        updates["memory_usage_policy"] = _parse_enum(
            body.memory_usage_policy, MemoryUsagePolicy, "memory_usage_policy",
        )
    if body.invocation_modes is not None:
        updates["invocation_modes"] = [
            _parse_enum(m, InvocationMode, "invocation_mode")
            for m in body.invocation_modes
        ]
    if body.status is not None:
        updates["status"] = _parse_enum(body.status, LifecycleState, "status")
    if body.metadata is not None:
        updates["metadata"] = body.metadata

    # Since the model is frozen, create a new instance with merged fields
    existing_data = existing.model_dump()
    existing_data.update(updates)
    updated = CapabilityRegistration(**existing_data)
    registry.register(updated)

    logger.info("Updated capability via API: %s", capability_id)
    return _serialize_registration(updated)


@catalog_router.delete("/catalog/capabilities/{capability_id}")
async def unregister_capability(
    capability_id: str,
    request: Request,
) -> dict[str, bool]:
    """Unregister a capability by ID.

    Args:
        capability_id: The capability to remove.
        request: The incoming HTTP request.

    Returns:
        Confirmation dict.
    """
    registry = _get_team_registry(request)
    removed = registry.unregister(capability_id)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Capability '{capability_id}' not found",
        )
    return {"deleted": True}


@catalog_router.get("/catalog/summary")
async def catalog_summary(request: Request) -> dict[str, Any]:
    """Return registry summary statistics.

    Args:
        request: The incoming HTTP request.

    Returns:
        Summary dict with counts and IDs.
    """
    registry = _get_team_registry(request)
    return registry.summary()


@catalog_router.post("/catalog/capabilities/{capability_id}/invoke")
async def invoke_capability(
    capability_id: str,
    body: InvokeRequest,
    request: Request,
) -> InvokeResponse:
    """Invoke a capability by creating a work item and submitting it.

    Args:
        capability_id: The capability to invoke.
        body: Invocation input data.
        request: The incoming HTTP request.

    Returns:
        Work ID and status.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    registry = _get_team_registry(request)
    reg = registry.get(capability_id)
    if reg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Capability '{capability_id}' not found",
        )

    # Warn-only input schema validation (log but don't block)
    if reg.input_schema and reg.input_schema.get("required"):
        missing = [
            f for f in reg.input_schema["required"]
            if f not in body.input
        ]
        if missing:
            logger.warning(
                "Invoke %s: missing recommended input fields: %s",
                capability_id, missing,
            )

    # Determine work item type from the profile's first work_item_type
    profile = engine.active_profile
    type_id = "default"
    if profile and profile.work_item_types:
        type_id = profile.work_item_types[0].id

    # Create and submit work item
    from agent_orchestrator.core.work_queue import WorkItem

    work_id = str(uuid.uuid4())
    title = body.title or f"Invocation of {capability_id}"
    work_item = WorkItem(
        id=work_id,
        type_id=type_id,
        title=title,
        data=body.input,
        priority=body.priority,
        app_id=body.app_id,
    )

    try:
        await engine.submit_work(work_item)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Emit invocation event
    await engine.event_bus.emit(Event(
        type=EventType.CAPABILITY_INVOKED,
        data={
            "capability_id": capability_id,
            "work_id": work_id,
        },
        source="catalog_api",
    ))

    logger.info("Invoked capability %s → work_id=%s", capability_id, work_id)
    return InvokeResponse(
        work_id=work_id,
        capability_id=capability_id,
        status="submitted",
    )
