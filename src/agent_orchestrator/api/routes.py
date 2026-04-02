"""API route groups for agent-orchestrator.

Each route group maps to a functional area:
- health: Health checks
- agents: Agent management (full CRUD)
- workflow: Workflow definition
- workitems: Work item operations
- governance: Policy management
- execution: Orchestration control
- metrics: Performance analytics
- audit: Audit trail
- config: Configuration management
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from agent_orchestrator.configuration.loader import save_settings
from agent_orchestrator.configuration.models import PolicyConfig
from agent_orchestrator.configuration.validator import validate_profile
from agent_orchestrator.exceptions import AgentError, ConfigurationError, OrchestratorError, ProfileError
from agent_orchestrator.core.event_bus import Event, EventType
from agent_orchestrator.governance.audit_logger import RecordType

logger = logging.getLogger(__name__)


# ---- Request/Response Models ----


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "0.1.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentResponse(BaseModel):
    """Agent definition response."""
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    phases: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    concurrency: int = 1
    system_prompt: str = ""


class AgentCreateRequest(BaseModel):
    """Request body for creating an agent."""
    id: str
    name: str
    description: str = ""
    system_prompt: str
    skills: list[str] = Field(default_factory=list)
    phases: list[str]
    llm: dict[str, Any] = Field(description="LLM configuration (provider, model, etc.)")
    concurrency: int = 1
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AgentUpdateRequest(BaseModel):
    """Request body for updating an agent (all fields optional)."""
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    skills: list[str] | None = None
    phases: list[str] | None = None
    llm: dict[str, Any] | None = None
    concurrency: int | None = None
    retry_policy: dict[str, Any] | None = None
    enabled: bool | None = None


class WorkItemRequest(BaseModel):
    """Work item submission request."""
    id: str
    type_id: str
    title: str
    data: dict[str, Any] = Field(default_factory=dict)
    priority: int = 5
    app_id: str = "default"
    deadline: str | None = None
    urgency: str = ""
    routing_tags: list[str] = Field(default_factory=list)


class WorkItemHistoryResponse(BaseModel):
    """Single history entry for a work item status transition."""
    timestamp: str
    from_status: str | None
    to_status: str
    phase_id: str = ""
    agent_id: str = ""
    reason: str = ""


class WorkItemResponse(BaseModel):
    """Work item response — full governed state."""
    id: str
    type_id: str
    title: str
    status: str = "pending"
    current_phase: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    app_id: str = "default"
    run_id: str = ""
    priority: int = 5
    submitted_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    attempt_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    history: list[WorkItemHistoryResponse] = Field(default_factory=list)
    deadline: str | None = None
    urgency: str = ""
    routing_tags: list[str] = Field(default_factory=list)


class ExecutionContextResponse(BaseModel):
    """Current execution context response."""
    app_id: str = "default"
    run_id: str = ""
    tenant_id: str = "default"
    environment: str = "development"
    deployment_mode: str = "lite"
    profile_name: str = ""


class ExecutionStatusResponse(BaseModel):
    """Execution engine status response."""
    state: str
    queue: dict[str, Any] = Field(default_factory=dict)
    pipeline: dict[str, Any] = Field(default_factory=dict)
    agents: dict[str, Any] = Field(default_factory=dict)


class PolicyResponse(BaseModel):
    """Governance policy response."""
    id: str
    name: str
    action: str
    priority: int = 0
    enabled: bool = True


class ConfigValidationResponse(BaseModel):
    """Configuration validation response."""
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SettingsResponse(BaseModel):
    """Orchestrator settings response (API keys masked)."""
    api_keys: dict[str, str] = Field(default_factory=dict)
    llm_endpoints: dict[str, str] = Field(default_factory=dict)
    active_profile: str = ""
    available_providers: list[str] = Field(default_factory=list)


class UpdateSettingsRequest(BaseModel):
    """Request body for updating orchestrator settings."""
    api_keys: dict[str, str] | None = None
    llm_endpoints: dict[str, str] | None = None


class ProfileListResponse(BaseModel):
    """Profile list response."""
    profiles: list[str]
    active: str = ""


class ReviewItemResponse(BaseModel):
    """Review queue item response."""
    id: str
    work_id: str
    phase_id: str
    reason: str
    reviewed: bool = False
    reviewed_by: str | None = None
    created_at: str = ""


class ReviewDecisionRequest(BaseModel):
    """Request body for completing a review."""
    reviewer: str
    notes: str = ""


class ReviewItemDetailResponse(BaseModel):
    """Detailed review item response with decision."""
    id: str
    work_id: str
    phase_id: str
    reason: str
    reviewed: bool = False
    reviewed_by: str | None = None
    decision: str = ""
    review_notes: str = ""
    created_at: str = ""
    reviewed_at: str | None = None


class WorkflowPhaseResponse(BaseModel):
    """Workflow phase response."""
    id: str
    name: str
    description: str = ""
    order: int = 0
    agents: list[str] = Field(default_factory=list)
    parallel: bool = False
    on_success: str = ""
    on_failure: str = ""
    is_terminal: bool = False
    requires_human: bool = False
    skippable: bool = False


class PolicyCreateRequest(BaseModel):
    """Request body for creating a governance policy."""
    id: str
    name: str
    description: str = ""
    scope: str = ""
    action: str = "review"
    conditions: list[str] = Field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


# ---- Helper: get engine from request ----


def _get_engine(request: Request):
    """Get the OrchestrationEngine from request state.

    Returns the engine or None (does NOT raise).
    """
    return getattr(request.app.state, "engine", None)


# ---- Helper: convert WorkItem to response ----


def _safe_isoformat(val: Any) -> str | None:
    """Convert a datetime to ISO format string, or None if not a datetime."""
    if isinstance(val, datetime):
        return val.isoformat()
    return None


def _work_item_to_response(item: Any) -> WorkItemResponse:
    """Convert a WorkItem dataclass to a WorkItemResponse."""
    from agent_orchestrator.core.work_queue import WorkItem as WI
    history_entries: list[WorkItemHistoryResponse] = []
    if isinstance(item, WI) and hasattr(item, "history"):
        for h in item.history:
            history_entries.append(WorkItemHistoryResponse(
                timestamp=h.timestamp.isoformat(),
                from_status=h.from_status.value if h.from_status else None,
                to_status=h.to_status.value,
                phase_id=h.phase_id,
                agent_id=h.agent_id,
                reason=h.reason,
            ))

    error = item.error if isinstance(item.error, (str, type(None))) else None
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    attempt_count = item.attempt_count if isinstance(item.attempt_count, int) else 0
    priority = item.priority if isinstance(item.priority, int) else 5

    return WorkItemResponse(
        id=item.id,
        type_id=item.type_id,
        title=item.title,
        status=item.status.value if hasattr(item.status, "value") else str(item.status),
        current_phase=item.current_phase,
        data=item.data if isinstance(item.data, dict) else {},
        results=item.results if isinstance(item.results, dict) else {},
        app_id=item.app_id,
        run_id=item.run_id,
        priority=priority,
        submitted_at=_safe_isoformat(item.submitted_at),
        started_at=_safe_isoformat(item.started_at),
        completed_at=_safe_isoformat(item.completed_at),
        error=error,
        attempt_count=attempt_count,
        metadata=metadata,
        history=history_entries,
        deadline=_safe_isoformat(getattr(item, "deadline", None)) if hasattr(item, "deadline") else None,
        urgency=item.urgency if isinstance(getattr(item, "urgency", None), str) else "",
        routing_tags=item.routing_tags if isinstance(getattr(item, "routing_tags", None), list) else [],
    )


# ---- Helper: convert AgentDefinition to response ----


def _agent_to_response(agent: Any) -> AgentResponse:
    """Convert an AgentDefinition to an AgentResponse.

    Args:
        agent: AgentDefinition instance.

    Returns:
        AgentResponse with flattened LLM fields.
    """
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        enabled=agent.enabled,
        phases=agent.phases,
        provider=agent.llm.provider,
        model=agent.llm.model,
        concurrency=agent.concurrency,
        system_prompt=agent.system_prompt,
    )


# ---- Health Routes ----

health_router = APIRouter()


@health_router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse()


@health_router.get("/health/ready", response_model=HealthResponse)
async def readiness_check() -> HealthResponse:
    """Readiness check — indicates if the service can accept requests."""
    return HealthResponse(status="ready")


@health_router.get("/health/live", response_model=HealthResponse)
async def liveness_check() -> HealthResponse:
    """Liveness check — indicates if the service is alive."""
    return HealthResponse(status="alive")


# ---- Context Route ----


@health_router.get("/context", response_model=ExecutionContextResponse)
async def get_context(request: Request) -> ExecutionContextResponse:
    """Return current execution context."""
    ctx = getattr(request.app.state, "execution_context", None)
    if ctx is None:
        return ExecutionContextResponse()
    return ExecutionContextResponse(
        app_id=ctx.app_id,
        run_id=ctx.run_id,
        tenant_id=ctx.tenant_id,
        environment=ctx.environment,
        deployment_mode=ctx.deployment_mode.value,
        profile_name=ctx.profile_name,
    )


# ---- Agent Routes ----

agents_router = APIRouter()


@agents_router.get("/agents", response_model=list[AgentResponse])
async def list_agents(request: Request) -> list[AgentResponse]:
    """List all configured agents."""
    agent_manager = getattr(request.app.state, "agent_manager", None)
    if agent_manager is None:
        return []
    agents = agent_manager.list_agents()
    return [_agent_to_response(a) for a in agents]


# Static paths MUST come before parameterized /{agent_id} to avoid conflicts
@agents_router.get("/agents/export")
async def export_agents(
    request: Request, fmt: str = "yaml",
) -> dict[str, Any]:
    """Export all agent definitions as JSON."""
    agent_manager = getattr(request.app.state, "agent_manager", None)
    if agent_manager is None:
        return {"agents": []}

    agents = agent_manager.list_agents()
    return {"agents": [a.model_dump() for a in agents]}


@agents_router.post("/agents/import", response_model=list[AgentResponse])
async def import_agents(file: UploadFile, request: Request) -> list[AgentResponse]:
    """Import agents from an uploaded JSON or YAML file."""
    import tempfile
    from pathlib import Path

    agent_manager = getattr(request.app.state, "agent_manager", None)
    if agent_manager is None:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    # Determine extension from filename
    filename = file.filename or "upload.yaml"
    ext = Path(filename).suffix.lower()
    if ext not in {".json", ".yaml", ".yml"}:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{ext}'. Use .json, .yaml, or .yml",
        )

    # Write to temp file and import
    content = await file.read()
    with tempfile.NamedTemporaryFile(
        suffix=ext, delete=False, mode="wb",
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        agents = agent_manager.import_agents(tmp_path)
    except ConfigurationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)

    return [_agent_to_response(a) for a in agents]


@agents_router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, request: Request) -> AgentResponse:
    """Get agent details by ID."""
    agent_manager = getattr(request.app.state, "agent_manager", None)
    if agent_manager is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    agent = agent_manager.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return _agent_to_response(agent)


@agents_router.post("/agents", response_model=AgentResponse, status_code=201)
async def create_agent(body: AgentCreateRequest, request: Request) -> AgentResponse:
    """Create a new agent definition."""
    agent_manager = getattr(request.app.state, "agent_manager", None)
    if agent_manager is None:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    try:
        agent = agent_manager.create_agent(body.model_dump())
    except AgentError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ConfigurationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _agent_to_response(agent)


@agents_router.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str, body: AgentUpdateRequest, request: Request,
) -> AgentResponse:
    """Update an existing agent definition."""
    agent_manager = getattr(request.app.state, "agent_manager", None)
    if agent_manager is None:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    # Build updates dict from non-None fields
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No update fields provided")

    try:
        agent = agent_manager.update_agent(agent_id, updates)
    except AgentError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ConfigurationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _agent_to_response(agent)


@agents_router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, request: Request) -> dict[str, str]:
    """Delete an agent definition."""
    agent_manager = getattr(request.app.state, "agent_manager", None)
    if agent_manager is None:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    deleted = agent_manager.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return {"status": "deleted", "agent_id": agent_id}


@agents_router.post("/agents/{agent_id}/scale")
async def scale_agent(agent_id: str, request: Request, concurrency: int = 1) -> dict[str, str]:
    """Scale agent concurrency."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    try:
        engine.scale_agent(agent_id, concurrency)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "scaled", "agent_id": agent_id, "concurrency": str(concurrency)}


# ---- Workflow Routes ----

workflow_router = APIRouter()


@workflow_router.get("/workflow/phases", response_model=list[WorkflowPhaseResponse])
async def list_phases(request: Request) -> list[WorkflowPhaseResponse]:
    """List workflow phases."""
    engine = _get_engine(request)
    if engine is not None:
        phases = engine.get_workflow_phases()
    else:
        # Fallback to config_manager
        config_mgr = getattr(request.app.state, "config_manager", None)
        if config_mgr is not None:
            try:
                profile = config_mgr.get_profile()
                phases = list(profile.workflow.phases)
            except Exception:
                phases = []
        else:
            phases = []

    return [
        WorkflowPhaseResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            order=p.order,
            agents=p.agents,
            parallel=p.parallel,
            on_success=p.on_success,
            on_failure=p.on_failure,
            is_terminal=p.is_terminal,
            requires_human=p.requires_human,
            skippable=p.skippable,
        )
        for p in phases
    ]


@workflow_router.get("/workflow/phases/{phase_id}", response_model=WorkflowPhaseResponse)
async def get_phase(phase_id: str, request: Request) -> WorkflowPhaseResponse:
    """Get phase details."""
    engine = _get_engine(request)
    phase = None
    if engine is not None:
        phase = engine.get_workflow_phase(phase_id)
    else:
        config_mgr = getattr(request.app.state, "config_manager", None)
        if config_mgr is not None:
            try:
                profile = config_mgr.get_profile()
                phase = next((p for p in profile.workflow.phases if p.id == phase_id), None)
            except Exception:
                pass

    if phase is None:
        raise HTTPException(status_code=404, detail=f"Phase '{phase_id}' not found")

    return WorkflowPhaseResponse(
        id=phase.id,
        name=phase.name,
        description=phase.description,
        order=phase.order,
        agents=phase.agents,
        parallel=phase.parallel,
        on_success=phase.on_success,
        on_failure=phase.on_failure,
        is_terminal=phase.is_terminal,
        requires_human=phase.requires_human,
        skippable=phase.skippable,
    )


# ---- Work Item Routes ----

workitems_router = APIRouter()


@workitems_router.get("/workitems", response_model=list[WorkItemResponse])
async def list_workitems(request: Request) -> list[WorkItemResponse]:
    """List work items."""
    engine = _get_engine(request)
    if engine is None:
        return []
    items = engine.list_work_items()
    return [
        WorkItemResponse(
            id=item["id"],
            type_id=item["type_id"],
            title=item["title"],
            status=item["status"],
            current_phase=item.get("current_phase", ""),
            priority=item.get("priority", 5),
            submitted_at=item.get("submitted_at"),
            started_at=item.get("started_at"),
            completed_at=item.get("completed_at"),
            error=item.get("error"),
            attempt_count=item.get("attempt_count", 0),
        )
        for item in items
    ]


@workitems_router.post("/workitems", response_model=WorkItemResponse)
async def create_workitem(body: WorkItemRequest, request: Request) -> WorkItemResponse:
    """Submit a new work item."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    from agent_orchestrator.core.work_queue import WorkItem

    deadline = None
    if body.deadline:
        deadline = datetime.fromisoformat(body.deadline)

    work_item = WorkItem(
        id=body.id,
        type_id=body.type_id,
        title=body.title,
        data=body.data,
        priority=body.priority,
        app_id=body.app_id,
        deadline=deadline,
        urgency=body.urgency,
        routing_tags=body.routing_tags,
    )
    try:
        await engine.submit_work(work_item)
    except OrchestratorError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return _work_item_to_response(work_item)


@workitems_router.get("/workitems/{work_id}", response_model=WorkItemResponse)
async def get_workitem(work_id: str, request: Request) -> WorkItemResponse:
    """Get work item details."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    item = engine.get_work_item(work_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Work item '{work_id}' not found")

    return _work_item_to_response(item)


# ---- Governance Routes ----

governance_router = APIRouter()


@workitems_router.get("/workitems/{work_id}/history", response_model=list[WorkItemHistoryResponse])
async def get_workitem_history(work_id: str, request: Request) -> list[WorkItemHistoryResponse]:
    """Get the status transition history for a work item."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    item = engine.get_work_item(work_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Work item '{work_id}' not found")

    return [
        WorkItemHistoryResponse(
            timestamp=h.timestamp.isoformat(),
            from_status=h.from_status.value if h.from_status else None,
            to_status=h.to_status.value,
            phase_id=h.phase_id,
            agent_id=h.agent_id,
            reason=h.reason,
        )
        for h in item.history
    ]


@workitems_router.get("/workitems/{work_id}/sla")
async def get_workitem_sla(work_id: str, request: Request) -> dict[str, Any]:
    """Get SLA status for a work item.

    Returns remaining time, breach status, and deadline information.

    Args:
        work_id: The work item identifier.
        request: The incoming HTTP request.

    Returns:
        SLA status dict with remaining time and breach info.
    """
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    item = engine.get_work_item(work_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Work item '{work_id}' not found")

    deadline = getattr(item, "deadline", None)
    if deadline is None:
        return {
            "work_item_id": work_id,
            "has_deadline": False,
            "deadline": None,
            "remaining_seconds": None,
            "breached": False,
            "urgency": getattr(item, "urgency", ""),
        }

    now = datetime.now(timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    remaining = (deadline - now).total_seconds()

    return {
        "work_item_id": work_id,
        "has_deadline": True,
        "deadline": deadline.isoformat(),
        "remaining_seconds": remaining,
        "breached": remaining <= 0,
        "urgency": getattr(item, "urgency", ""),
    }


class WorkItemSummaryResponse(BaseModel):
    """Work item summary with counts."""
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)


@workitems_router.get("/workitems-summary", response_model=WorkItemSummaryResponse)
async def get_workitems_summary(request: Request) -> WorkItemSummaryResponse:
    """Get summary counts of work items by status and type."""
    engine = _get_engine(request)
    if engine is None:
        return WorkItemSummaryResponse()

    items = engine.list_work_items()
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for item in items:
        s = item.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        t = item.get("type_id", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    return WorkItemSummaryResponse(
        total=len(items),
        by_status=by_status,
        by_type=by_type,
    )


@governance_router.get("/governance/policies", response_model=list[PolicyResponse])
async def list_policies(request: Request) -> list[PolicyResponse]:
    """List governance policies."""
    engine = _get_engine(request)
    if engine is None or engine.governor is None:
        return []
    policies = engine.governor.list_policies()
    return [
        PolicyResponse(
            id=p.id,
            name=p.name,
            action=p.action,
            priority=p.priority,
            enabled=p.enabled,
        )
        for p in policies
    ]


@governance_router.post("/governance/policies", response_model=PolicyResponse, status_code=201)
async def create_policy(body: PolicyCreateRequest, request: Request) -> PolicyResponse:
    """Create a governance policy."""
    engine = _get_engine(request)
    if engine is None or engine.governor is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    policy = PolicyConfig(
        id=body.id,
        name=body.name,
        description=body.description,
        scope=body.scope,
        action=body.action,
        conditions=body.conditions,
        priority=body.priority,
        enabled=body.enabled,
        tags=body.tags,
    )
    engine.governor.add_policy(policy)

    return PolicyResponse(
        id=policy.id,
        name=policy.name,
        action=policy.action,
        priority=policy.priority,
        enabled=policy.enabled,
    )


@governance_router.get("/governance/reviews", response_model=list[ReviewItemResponse])
async def list_reviews(request: Request) -> list[ReviewItemResponse]:
    """List review items."""
    engine = _get_engine(request)
    if engine is None or engine.review_queue is None:
        return []
    items = engine.review_queue.get_all()
    return [
        ReviewItemResponse(
            id=item.id,
            work_id=item.work_id,
            phase_id=item.phase_id,
            reason=item.reason,
            reviewed=item.reviewed,
            reviewed_by=item.reviewed_by,
            created_at=item.created_at.isoformat(),
        )
        for item in items
    ]


@governance_router.get("/governance/reviews/{review_id}", response_model=ReviewItemDetailResponse)
async def get_review(review_id: str, request: Request) -> ReviewItemDetailResponse:
    """Get a specific review item."""
    engine = _get_engine(request)
    if engine is None or engine.review_queue is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    item = engine.review_queue.get_item(review_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found")
    return ReviewItemDetailResponse(
        id=item.id,
        work_id=item.work_id,
        phase_id=item.phase_id,
        reason=item.reason,
        reviewed=item.reviewed,
        reviewed_by=item.reviewed_by,
        decision=item.decision,
        review_notes=item.review_notes,
        created_at=item.created_at.isoformat(),
        reviewed_at=item.reviewed_at.isoformat() if item.reviewed_at else None,
    )


@governance_router.post("/governance/reviews/{review_id}/approve", response_model=ReviewItemDetailResponse)
async def approve_review(review_id: str, body: ReviewDecisionRequest, request: Request) -> ReviewItemDetailResponse:
    """Approve a review item."""
    engine = _get_engine(request)
    if engine is None or engine.review_queue is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    success = engine.review_queue.complete_review(
        review_id=review_id,
        reviewed_by=body.reviewer,
        notes=body.notes,
        decision="approved",
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found")

    # Audit log
    if engine.audit_logger is not None:
        engine.audit_logger.append(
            RecordType.DECISION,
            "governance.review_approved",
            f"Review {review_id} approved by {body.reviewer}",
            data={"review_id": review_id, "reviewer": body.reviewer, "notes": body.notes},
        )

    # Emit event
    await engine.event_bus.emit(Event(
        type=EventType.GOVERNANCE_REVIEW_COMPLETED,
        data={"review_id": review_id, "decision": "approved", "reviewer": body.reviewer},
        source="api",
    ))

    item = engine.review_queue.get_item(review_id)
    return ReviewItemDetailResponse(
        id=item.id,
        work_id=item.work_id,
        phase_id=item.phase_id,
        reason=item.reason,
        reviewed=item.reviewed,
        reviewed_by=item.reviewed_by,
        decision=item.decision,
        review_notes=item.review_notes,
        created_at=item.created_at.isoformat(),
        reviewed_at=item.reviewed_at.isoformat() if item.reviewed_at else None,
    )


@governance_router.post("/governance/reviews/{review_id}/reject", response_model=ReviewItemDetailResponse)
async def reject_review(review_id: str, body: ReviewDecisionRequest, request: Request) -> ReviewItemDetailResponse:
    """Reject a review item."""
    engine = _get_engine(request)
    if engine is None or engine.review_queue is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    success = engine.review_queue.complete_review(
        review_id=review_id,
        reviewed_by=body.reviewer,
        notes=body.notes,
        decision="rejected",
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found")

    if engine.audit_logger is not None:
        engine.audit_logger.append(
            RecordType.DECISION,
            "governance.review_rejected",
            f"Review {review_id} rejected by {body.reviewer}",
            data={"review_id": review_id, "reviewer": body.reviewer, "notes": body.notes},
        )

    await engine.event_bus.emit(Event(
        type=EventType.GOVERNANCE_REVIEW_COMPLETED,
        data={"review_id": review_id, "decision": "rejected", "reviewer": body.reviewer},
        source="api",
    ))

    item = engine.review_queue.get_item(review_id)
    return ReviewItemDetailResponse(
        id=item.id,
        work_id=item.work_id,
        phase_id=item.phase_id,
        reason=item.reason,
        reviewed=item.reviewed,
        reviewed_by=item.reviewed_by,
        decision=item.decision,
        review_notes=item.review_notes,
        created_at=item.created_at.isoformat(),
        reviewed_at=item.reviewed_at.isoformat() if item.reviewed_at else None,
    )


# ---- Execution Routes ----

execution_router = APIRouter()


@execution_router.get("/execution/status")
async def get_execution_status(request: Request) -> dict[str, Any]:
    """Get orchestration engine status."""
    engine = _get_engine(request)
    if engine is None:
        return {"state": "idle"}
    return engine.get_status()


@execution_router.post("/execution/start")
async def start_execution(request: Request) -> dict[str, str]:
    """Start the orchestration engine."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    try:
        await engine.start()
    except OrchestratorError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"status": "started"}


@execution_router.post("/execution/stop")
async def stop_execution(request: Request) -> dict[str, str]:
    """Stop the orchestration engine."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    await engine.stop()
    return {"status": "stopped"}


@execution_router.post("/execution/pause")
async def pause_execution(request: Request) -> dict[str, str]:
    """Pause processing."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    await engine.pause()
    return {"status": "paused"}


@execution_router.post("/execution/resume")
async def resume_execution(request: Request) -> dict[str, str]:
    """Resume processing."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    await engine.resume()
    return {"status": "resumed"}


# ---- Metrics Routes ----

metrics_router = APIRouter()


@metrics_router.get("/metrics")
async def get_metrics(request: Request) -> dict[str, Any]:
    """Get aggregated metrics."""
    engine = _get_engine(request)
    if engine is None or engine.metrics is None:
        return {"total_entries": 0, "counters": {}}
    return engine.metrics.get_summary()


@metrics_router.get("/metrics/agents/{agent_id}")
async def get_agent_metrics(agent_id: str, request: Request) -> dict[str, Any]:
    """Get per-agent metrics."""
    engine = _get_engine(request)
    if engine is None:
        return {"agent_id": agent_id, "metrics": {}}
    status = engine.get_status()
    agents = status.get("agents", {})
    agent_stats = agents.get(agent_id, {})
    return {"agent_id": agent_id, "metrics": agent_stats}


# ---- Audit Routes ----

audit_router = APIRouter()


@audit_router.get("/audit")
async def query_audit(
    request: Request,
    work_id: str | None = None,
    record_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query audit trail."""
    engine = _get_engine(request)
    if engine is None or engine.audit_logger is None:
        return []

    rt = None
    if record_type is not None:
        try:
            rt = RecordType(record_type)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid record_type '{record_type}'. "
                       f"Valid: {[t.value for t in RecordType]}",
            )

    return engine.audit_logger.query(work_id=work_id, record_type=rt, limit=limit)


# ---- Config Routes ----

config_router = APIRouter()


@config_router.get("/config/profile/export")
async def export_profile_component(
    request: Request,
    component: str = "all",
) -> dict[str, Any]:
    """Export a profile component from the active profile.

    Use this to get agents, workflow, governance, or workitems config
    as JSON for reuse as a template when creating a new domain.

    Args:
        component: One of 'agents', 'workflow', 'governance', 'workitems', 'all'.
    """
    config_manager = getattr(request.app.state, "config_manager", None)
    if config_manager is None:
        raise HTTPException(status_code=503, detail="Configuration manager not initialized")

    try:
        return config_manager.get_profile_component(component)
    except ConfigurationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class SwitchProfileRequest(BaseModel):
    """Request body for switching the active profile."""
    profile_name: str


@config_router.put("/config/profile", response_model=ProfileListResponse)
async def switch_profile(body: SwitchProfileRequest, request: Request) -> ProfileListResponse:
    """Switch the active profile and reload configuration.

    Called by AO Studio deployer after writing profile files to disk.
    """
    config_mgr = getattr(request.app.state, "config_manager", None)
    if config_mgr is None:
        raise HTTPException(status_code=503, detail="Configuration manager not initialized")

    try:
        config_mgr.switch_profile(body.profile_name)
    except ProfileError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ConfigurationError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    engine = getattr(request.app.state, "engine", None)
    if engine is not None and hasattr(engine, "reload_config"):
        try:
            engine.reload_config()
            logger.info("Engine reloaded after profile switch to '%s'", body.profile_name)
        except Exception:
            logger.warning("Engine reload failed after profile switch", exc_info=True)

    profiles = config_mgr.list_profiles()
    active = config_mgr.get_settings().active_profile
    return ProfileListResponse(profiles=profiles, active=active)


@config_router.get("/config/profiles", response_model=ProfileListResponse)
async def list_config_profiles(request: Request) -> ProfileListResponse:
    """List available profiles."""
    config_mgr = getattr(request.app.state, "config_manager", None)
    if config_mgr is None:
        return ProfileListResponse(profiles=[])
    try:
        profiles = config_mgr.list_profiles()
        active = config_mgr.get_settings().active_profile
        return ProfileListResponse(profiles=profiles, active=active)
    except Exception:
        return ProfileListResponse(profiles=[])


@config_router.post("/config/validate", response_model=ConfigValidationResponse)
async def validate_config(request: Request) -> ConfigValidationResponse:
    """Validate current configuration."""
    config_mgr = getattr(request.app.state, "config_manager", None)
    if config_mgr is None:
        return ConfigValidationResponse(is_valid=True)
    try:
        profile = config_mgr.get_profile()
        settings = config_mgr.get_settings()
        result = validate_profile(profile, settings)
        return ConfigValidationResponse(
            is_valid=result.is_valid,
            errors=result.errors,
            warnings=result.warnings,
        )
    except Exception as e:
        return ConfigValidationResponse(is_valid=False, errors=[str(e)])


@config_router.get("/config/history")
async def get_config_history() -> list[dict[str, str]]:
    """Get configuration change history."""
    return []


_AVAILABLE_PROVIDERS = ["anthropic", "openai", "google", "grok", "ollama"]


def _build_settings_response(settings: Any) -> SettingsResponse:
    """Build a SettingsResponse with masked API keys."""
    masked = {k: "***" for k in settings.api_keys} if settings.api_keys else {}
    return SettingsResponse(
        api_keys=masked,
        llm_endpoints=dict(settings.llm_endpoints) if settings.llm_endpoints else {},
        active_profile=settings.active_profile,
        available_providers=_AVAILABLE_PROVIDERS,
    )


@config_router.get("/config/settings", response_model=SettingsResponse)
async def get_settings(request: Request) -> SettingsResponse:
    """Get orchestrator settings (API keys masked)."""
    config_mgr = getattr(request.app.state, "config_manager", None)
    if config_mgr is None:
        return SettingsResponse(available_providers=_AVAILABLE_PROVIDERS)
    try:
        settings = config_mgr.get_settings()
        return _build_settings_response(settings)
    except ConfigurationError:
        return SettingsResponse(available_providers=_AVAILABLE_PROVIDERS)


@config_router.put("/config/settings", response_model=SettingsResponse)
async def update_settings(
    body: UpdateSettingsRequest, request: Request,
) -> SettingsResponse:
    """Update orchestrator settings (API keys, LLM endpoints)."""
    config_mgr = getattr(request.app.state, "config_manager", None)
    if config_mgr is None:
        raise HTTPException(status_code=503, detail="Configuration manager not initialized")

    try:
        current = config_mgr.get_settings()
    except ConfigurationError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    updates: dict[str, Any] = {}
    if body.api_keys is not None:
        merged_keys = dict(current.api_keys)
        merged_keys.update(body.api_keys)
        updates["api_keys"] = merged_keys
    if body.llm_endpoints is not None:
        merged_endpoints = dict(current.llm_endpoints)
        merged_endpoints.update(body.llm_endpoints)
        updates["llm_endpoints"] = merged_endpoints

    if not updates:
        raise HTTPException(status_code=422, detail="No update fields provided")

    new_settings = current.model_copy(update=updates)
    save_settings(config_mgr.workspace_dir, new_settings)
    config_mgr.reload()

    updated = config_mgr.get_settings()
    return _build_settings_response(updated)


class ModelInfo(BaseModel):
    """Available model from a provider."""
    id: str
    name: str


@config_router.get("/config/models/{provider}", response_model=list[ModelInfo])
async def list_provider_models(provider: str, request: Request) -> list[ModelInfo]:
    """List available models for a given LLM provider."""
    if provider not in _AVAILABLE_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    adapter = engine.llm_adapter
    if adapter is None:
        raise HTTPException(status_code=503, detail="LLM adapter not available")

    models = await adapter.list_models(provider)
    return [ModelInfo(id=m["id"], name=m["name"]) for m in models]


# ---- Connector Routes ----

connectors_router = APIRouter()


@connectors_router.get("/connectors/capabilities", tags=["connectors"])
async def list_capabilities(request: Request) -> dict[str, Any]:
    """List all registered connector capability types."""
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        return {"capabilities": []}
    caps = engine.connector_service.list_available_capabilities()
    return {"capabilities": [c.value for c in caps]}


@connectors_router.get("/connectors/providers", tags=["connectors"])
async def list_connector_providers(request: Request) -> dict[str, Any]:
    """List all registered connector providers."""
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        return {"providers": []}
    providers = engine.connector_service.list_providers()
    return {"providers": [p.model_dump() for p in providers]}


@connectors_router.get("/connectors/providers/{provider_id}", tags=["connectors"])
async def get_connector_provider(provider_id: str, request: Request) -> dict[str, Any]:
    """Get details for a specific connector provider."""
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        raise HTTPException(status_code=503, detail="Connector service not initialized")
    provider = engine.connector_service._registry.get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return provider.get_descriptor().model_dump()


@connectors_router.get(
    "/connectors/capabilities/{capability_type}/providers", tags=["connectors"]
)
async def list_providers_for_capability(
    capability_type: str, request: Request
) -> dict[str, Any]:
    """List providers that support a specific capability type."""
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        return {"capability_type": capability_type, "providers": []}
    from agent_orchestrator.connectors import CapabilityType
    try:
        cap = CapabilityType(capability_type)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"Unknown capability_type: {capability_type!r}"
        )
    providers = engine.connector_service._registry.find_providers_for_capability(cap)
    return {
        "capability_type": capability_type,
        "providers": [p.get_descriptor().model_dump() for p in providers],
    }


@connectors_router.get("/connectors/configs", tags=["connectors"])
async def list_connector_configs(request: Request) -> dict[str, Any]:
    """List registered connector configurations."""
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        return {"configs": []}
    configs = engine.connector_service.get_configs()
    return {"configs": [c.model_dump() for c in configs]}


@connectors_router.get("/connectors/traces", tags=["connectors"])
async def get_connector_traces(
    request: Request,
    run_id: str | None = None,
    connector_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Query connector execution traces."""
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        return {"traces": []}
    traces = engine.connector_service.get_traces(
        run_id=run_id, connector_id=connector_id, limit=limit
    )
    return {"traces": [t.model_dump() for t in traces]}


@connectors_router.get("/connectors/traces/summary", tags=["connectors"])
async def get_connector_trace_summary(request: Request) -> dict[str, Any]:
    """Get aggregated summary of connector execution traces."""
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        return {"total_traces": 0, "by_status": {}, "by_capability": {}}
    return engine.connector_service.get_trace_summary()


# ---- Connector Execute Route ----


class ConnectorExecuteRequest(BaseModel):
    """Request body for executing a connector capability operation."""

    capability_type: str
    operation: str
    parameters: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    preferred_provider: str | None = None
    timeout_seconds: float | None = None


@connectors_router.post("/connectors/execute", tags=["connectors"])
async def execute_connector(
    body: ConnectorExecuteRequest, request: Request
) -> dict[str, Any]:
    """Execute a connector capability operation.

    Resolves the appropriate provider for the given capability_type and operation,
    enforces permission policies, applies retry logic, and returns the result.

    Returns a serialized ConnectorInvocationResult with status, payload, cost_info,
    and duration_ms. Callers should check ``status`` before consuming ``payload``.
    """
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        raise HTTPException(status_code=503, detail="Connector service not initialized")

    from agent_orchestrator.connectors import CapabilityType

    try:
        cap = CapabilityType(body.capability_type)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"Unknown capability_type: {body.capability_type!r}"
        )

    result = await engine.connector_service.execute(
        capability_type=cap,
        operation=body.operation,
        parameters=body.parameters,
        context=body.context or None,
        preferred_provider=body.preferred_provider,
        timeout_seconds=body.timeout_seconds,
    )
    return result.model_dump()


# ---- Connector Governance Routes ----

class ConnectorEnablementRequest(BaseModel):
    """Request body for registering a connector config."""
    connector_id: str
    provider_id: str
    capability_type: str
    display_name: str = ""
    enabled: bool = True
    scoped_modules: list[str] = Field(default_factory=list)
    scoped_agent_roles: list[str] = Field(default_factory=list)


class ConnectorScopingRequest(BaseModel):
    """Request body for updating connector scoping."""
    scoped_modules: list[str] | None = None
    scoped_agent_roles: list[str] | None = None


class ConnectorPolicyRequest(BaseModel):
    """Request body for adding a permission policy to a connector."""
    policy_id: str
    requires_approval: bool = False
    allowed_modules: list[str] = Field(default_factory=list)
    allowed_agent_roles: list[str] = Field(default_factory=list)
    denied_operations: list[str] = Field(default_factory=list)


def _get_governance(request: Request):
    """Return the connector governance service or raise 503."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return engine.connector_governance_service


@connectors_router.get("/connectors/configs/{connector_id}", tags=["connectors"])
async def get_connector_config(connector_id: str, request: Request) -> dict[str, Any]:
    """Get a specific connector configuration."""
    engine = _get_engine(request)
    if engine is None or engine.connector_service is None:
        raise HTTPException(status_code=503, detail="Connector service not initialized")
    from agent_orchestrator.connectors import ConnectorRegistry
    config = engine.connector_service._registry.get_config(connector_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Connector config '{connector_id}' not found")
    return config.model_dump()


@connectors_router.post("/connectors/configs", tags=["connectors"])
async def register_connector_config(
    body: ConnectorEnablementRequest, request: Request
) -> dict[str, Any]:
    """Register a new connector configuration."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    from agent_orchestrator.connectors import CapabilityType, ConnectorConfig
    try:
        cap = CapabilityType(body.capability_type)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"Unknown capability_type: {body.capability_type!r}"
        )
    config = ConnectorConfig(
        connector_id=body.connector_id,
        provider_id=body.provider_id,
        capability_type=cap,
        display_name=body.display_name,
        enabled=body.enabled,
        scoped_modules=body.scoped_modules,
        scoped_agent_roles=body.scoped_agent_roles,
    )
    engine.connector_governance_service._registry.register_config(config)
    return config.model_dump()


@connectors_router.post("/connectors/configs/{connector_id}/enable", tags=["connectors"])
async def enable_connector(connector_id: str, request: Request) -> dict[str, Any]:
    """Enable a connector at runtime."""
    from agent_orchestrator.connectors.governance_service import ConnectorGovernanceError
    try:
        updated = _get_governance(request).enable_connector(connector_id)
    except ConnectorGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return updated.model_dump()


@connectors_router.post("/connectors/configs/{connector_id}/disable", tags=["connectors"])
async def disable_connector(connector_id: str, request: Request) -> dict[str, Any]:
    """Disable a connector at runtime."""
    from agent_orchestrator.connectors.governance_service import ConnectorGovernanceError
    try:
        updated = _get_governance(request).disable_connector(connector_id)
    except ConnectorGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return updated.model_dump()


@connectors_router.put("/connectors/configs/{connector_id}/scoping", tags=["connectors"])
async def update_connector_scoping(
    connector_id: str, body: ConnectorScopingRequest, request: Request
) -> dict[str, Any]:
    """Update module and/or agent-role scoping for a connector."""
    from agent_orchestrator.connectors.governance_service import ConnectorGovernanceError
    try:
        updated = _get_governance(request).update_scoping(
            connector_id,
            scoped_modules=body.scoped_modules,
            scoped_agent_roles=body.scoped_agent_roles,
        )
    except ConnectorGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return updated.model_dump()


@connectors_router.post("/connectors/configs/{connector_id}/policies", tags=["connectors"])
async def add_connector_policy(
    connector_id: str, body: ConnectorPolicyRequest, request: Request
) -> dict[str, Any]:
    """Add a permission policy to a connector configuration."""
    from agent_orchestrator.connectors import ConnectorPermissionPolicy
    from agent_orchestrator.connectors.governance_service import ConnectorGovernanceError
    policy = ConnectorPermissionPolicy(
        policy_id=body.policy_id,
        requires_approval=body.requires_approval,
        allowed_modules=body.allowed_modules,
        allowed_agent_roles=body.allowed_agent_roles,
        denied_operations=body.denied_operations,
    )
    try:
        updated = _get_governance(request).add_policy(connector_id, policy)
    except ConnectorGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return updated.model_dump()


@connectors_router.delete(
    "/connectors/configs/{connector_id}/policies/{policy_id}", tags=["connectors"]
)
async def remove_connector_policy(
    connector_id: str, policy_id: str, request: Request
) -> dict[str, Any]:
    """Remove a permission policy from a connector configuration."""
    from agent_orchestrator.connectors.governance_service import ConnectorGovernanceError
    try:
        updated = _get_governance(request).remove_policy(connector_id, policy_id)
    except ConnectorGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return updated.model_dump()


@connectors_router.get("/connectors/discovery", tags=["connectors"])
async def discover_connectors(
    request: Request,
    module_name: str | None = None,
    agent_role: str | None = None,
) -> dict[str, Any]:
    """Discover connectors accessible in a given execution context."""
    governance = _get_governance(request)
    items = governance.discover(module_name=module_name, agent_role=agent_role)
    return {"connectors": [item.as_dict() for item in items]}


@connectors_router.get("/connectors/discovery/status", tags=["connectors"])
async def get_discovery_status(request: Request) -> dict[str, Any]:
    """Return the result of the most recent provider auto-discovery pass."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    result = engine.last_discovery_result
    if result is None:
        return {"registered": [], "skipped": [], "errors": [], "summary": "no discovery run yet"}
    return {**result.as_dict(), "summary": result.summary()}


@connectors_router.post("/connectors/discovery/refresh", tags=["connectors"])
async def refresh_provider_discovery(
    request: Request,
    plugin_directory: str | None = None,
) -> dict[str, Any]:
    """Trigger a new provider discovery pass.

    Args:
        plugin_directory: Optional filesystem path to scan for external providers.
    """
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    from pathlib import Path
    plugin_path = Path(plugin_directory) if plugin_directory else None
    result = engine.rediscover_providers(plugin_directory=plugin_path)
    return {**result.as_dict(), "summary": result.summary()}


@connectors_router.get("/connectors/configs/{connector_id}/permissions", tags=["connectors"])
async def get_effective_permissions(
    connector_id: str,
    request: Request,
    module_name: str | None = None,
    agent_role: str | None = None,
) -> dict[str, Any]:
    """Get effective permissions for a connector in a given execution context."""
    from agent_orchestrator.connectors.governance_service import ConnectorGovernanceError
    try:
        perms = _get_governance(request).get_effective_permissions(
            connector_id, module_name=module_name, agent_role=agent_role
        )
    except ConnectorGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return perms.as_dict()


# ---- Contract Routes ----


class CapabilityContractCreateRequest(BaseModel):
    """Request body for registering a capability contract."""

    contract_id: str
    capability_type: str
    operation_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    read_write_classification: str = "read_only"
    permission_requirements: list[str] = Field(default_factory=list)
    audit_requirements: str = "invocation"
    cost_reporting_required: bool = False
    failure_semantics: str = "warn_only"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactContractCreateRequest(BaseModel):
    """Request body for registering an artifact contract."""

    contract_id: str
    artifact_type: str
    description: str = ""
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    validation_rules: list[dict[str, Any]] = Field(default_factory=list)
    provenance_requirements: list[str] = Field(default_factory=list)
    lifecycle_state_model: list[str] = Field(default_factory=list)
    producer_constraints: list[str] = Field(default_factory=list)
    consumer_constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidatePayloadRequest(BaseModel):
    """Request body for on-demand contract validation."""

    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)


def _get_contract_registry(request: Request):
    """Return the ContractRegistry from app state, or None."""
    return getattr(request.app.state, "contract_registry", None)


contracts_router = APIRouter()


@contracts_router.get("/contracts/summary", tags=["contracts"])
async def get_contracts_summary(request: Request) -> dict[str, Any]:
    """Return a summary of all registered contracts."""
    registry = _get_contract_registry(request)
    if registry is None:
        return {"capability_contracts": 0, "artifact_contracts": 0}
    return registry.summary()


# ---- Capability Contracts ----


@contracts_router.get("/contracts/capability", tags=["contracts"])
async def list_capability_contracts(
    request: Request,
    capability_type: str | None = None,
    operation_name: str | None = None,
) -> list[dict[str, Any]]:
    """List registered capability contracts, optionally filtered by type/operation."""
    registry = _get_contract_registry(request)
    if registry is None:
        return []
    if capability_type and operation_name:
        contracts = registry.find_capability_contracts(capability_type, operation_name)
    else:
        contracts = registry.list_capability_contracts()
        if capability_type:
            contracts = [c for c in contracts if c.capability_type == capability_type]
    return [c.model_dump() for c in contracts]


@contracts_router.post("/contracts/capability", status_code=201, tags=["contracts"])
async def register_capability_contract(
    body: CapabilityContractCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Register a new capability contract."""
    from agent_orchestrator.contracts import (
        AuditRequirement,
        CapabilityContract,
        FailureSemantic,
        ReadWriteClassification,
    )

    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")

    try:
        contract = CapabilityContract(
            contract_id=body.contract_id,
            capability_type=body.capability_type,
            operation_name=body.operation_name,
            description=body.description,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
            read_write_classification=ReadWriteClassification(body.read_write_classification),
            permission_requirements=body.permission_requirements,
            audit_requirements=AuditRequirement(body.audit_requirements),
            cost_reporting_required=body.cost_reporting_required,
            failure_semantics=FailureSemantic(body.failure_semantics),
            metadata=body.metadata,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    registry.register_capability_contract(contract)
    return contract.model_dump()


@contracts_router.get("/contracts/capability/{contract_id}", tags=["contracts"])
async def get_capability_contract(
    contract_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get a registered capability contract by ID."""
    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")
    contract = registry.get_capability_contract(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Capability contract '{contract_id}' not found")
    return contract.model_dump()


@contracts_router.delete("/contracts/capability/{contract_id}", tags=["contracts"])
async def unregister_capability_contract(
    contract_id: str,
    request: Request,
) -> dict[str, Any]:
    """Unregister a capability contract by ID."""
    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")
    removed = registry.unregister_capability_contract(contract_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Capability contract '{contract_id}' not found")
    return {"removed": True, "contract_id": contract_id}


@contracts_router.post(
    "/contracts/capability/{contract_id}/validate-input",
    tags=["contracts"],
)
async def validate_capability_input(
    contract_id: str,
    body: ValidatePayloadRequest,
    request: Request,
) -> dict[str, Any]:
    """Validate a payload against a capability contract's input schema."""
    from agent_orchestrator.contracts import ContractValidator

    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")
    contract = registry.get_capability_contract(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Capability contract '{contract_id}' not found")

    validator = ContractValidator(registry)
    result = validator.validate_capability_input(
        contract.capability_type,
        contract.operation_name,
        body.payload,
        body.context,
    )
    return result.model_dump() if result is not None else {"is_valid": True, "contract_id": contract_id, "violations": []}


@contracts_router.post(
    "/contracts/capability/{contract_id}/validate-output",
    tags=["contracts"],
)
async def validate_capability_output(
    contract_id: str,
    body: ValidatePayloadRequest,
    request: Request,
) -> dict[str, Any]:
    """Validate a payload against a capability contract's output schema."""
    from agent_orchestrator.contracts import ContractValidator

    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")
    contract = registry.get_capability_contract(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Capability contract '{contract_id}' not found")

    validator = ContractValidator(registry)
    result = validator.validate_capability_output(
        contract.capability_type,
        contract.operation_name,
        body.payload,
        body.context,
    )
    return result.model_dump() if result is not None else {"is_valid": True, "contract_id": contract_id, "violations": []}


# ---- Artifact Contracts ----


@contracts_router.get("/contracts/artifact", tags=["contracts"])
async def list_artifact_contracts(
    request: Request,
    artifact_type: str | None = None,
) -> list[dict[str, Any]]:
    """List registered artifact contracts, optionally filtered by artifact_type."""
    registry = _get_contract_registry(request)
    if registry is None:
        return []
    if artifact_type:
        contracts = registry.find_artifact_contracts(artifact_type)
    else:
        contracts = registry.list_artifact_contracts()
    return [c.model_dump() for c in contracts]


@contracts_router.post("/contracts/artifact", status_code=201, tags=["contracts"])
async def register_artifact_contract(
    body: ArtifactContractCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Register a new artifact contract."""
    from agent_orchestrator.contracts import ArtifactContract, ArtifactValidationRule, LifecycleState

    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")

    try:
        rules = [ArtifactValidationRule(**r) for r in body.validation_rules]
        lifecycle = [LifecycleState(s) for s in body.lifecycle_state_model]
        contract = ArtifactContract(
            contract_id=body.contract_id,
            artifact_type=body.artifact_type,
            description=body.description,
            required_fields=body.required_fields,
            optional_fields=body.optional_fields,
            validation_rules=rules,
            provenance_requirements=body.provenance_requirements,
            lifecycle_state_model=lifecycle,
            producer_constraints=body.producer_constraints,
            consumer_constraints=body.consumer_constraints,
            metadata=body.metadata,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    registry.register_artifact_contract(contract)
    return contract.model_dump()


@contracts_router.get("/contracts/artifact/{contract_id}", tags=["contracts"])
async def get_artifact_contract(
    contract_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get a registered artifact contract by ID."""
    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")
    contract = registry.get_artifact_contract(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Artifact contract '{contract_id}' not found")
    return contract.model_dump()


@contracts_router.delete("/contracts/artifact/{contract_id}", tags=["contracts"])
async def unregister_artifact_contract(
    contract_id: str,
    request: Request,
) -> dict[str, Any]:
    """Unregister an artifact contract by ID."""
    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")
    removed = registry.unregister_artifact_contract(contract_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Artifact contract '{contract_id}' not found")
    return {"removed": True, "contract_id": contract_id}


@contracts_router.post(
    "/contracts/artifact/{contract_id}/validate",
    tags=["contracts"],
)
async def validate_artifact_payload(
    contract_id: str,
    body: ValidatePayloadRequest,
    request: Request,
) -> dict[str, Any]:
    """Validate a payload against a registered artifact contract."""
    from agent_orchestrator.contracts import ContractValidator

    registry = _get_contract_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Contract registry not available")
    contract = registry.get_artifact_contract(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Artifact contract '{contract_id}' not found")

    validator = ContractValidator(registry)
    result = validator.validate_artifact(
        contract.artifact_type,
        body.payload,
        body.context,
    )
    return result.model_dump() if result is not None else {"is_valid": True, "contract_id": contract_id, "violations": []}


# ---- Artifact Routes ----

artifacts_router = APIRouter()


@artifacts_router.get("/artifacts")
async def query_artifacts(
    request: Request,
    work_id: str | None = None,
    phase_id: str | None = None,
    agent_id: str | None = None,
    artifact_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query artifacts with optional filters."""
    engine = _get_engine(request)
    if engine is None:
        return []
    store = getattr(engine, '_artifact_store', None)
    if store is None:
        return []
    artifacts = store.query(
        work_id=work_id, phase_id=phase_id,
        agent_id=agent_id, artifact_type=artifact_type,
        limit=limit,
    )
    return [
        {
            "artifact_id": a.artifact_id,
            "work_id": a.work_id,
            "phase_id": a.phase_id,
            "agent_id": a.agent_id,
            "artifact_type": a.artifact_type,
            "content_hash": a.content_hash,
            "version": a.version,
            "timestamp": a.timestamp.isoformat(),
            "run_id": a.run_id,
            "app_id": a.app_id,
        }
        for a in artifacts
    ]


@artifacts_router.get("/artifacts/chain/{work_id}")
async def get_artifact_chain(work_id: str, request: Request) -> list[dict[str, Any]]:
    """Get the full evidence chain for a work item."""
    engine = _get_engine(request)
    if engine is None:
        return []
    store = getattr(engine, '_artifact_store', None)
    if store is None:
        return []
    artifacts = store.get_chain(work_id)
    return [
        {
            "artifact_id": a.artifact_id,
            "work_id": a.work_id,
            "phase_id": a.phase_id,
            "agent_id": a.agent_id,
            "artifact_type": a.artifact_type,
            "content_hash": a.content_hash,
            "content": a.content,
            "version": a.version,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in artifacts
    ]


@artifacts_router.get("/artifacts/{content_hash}")
async def get_artifact_by_hash(content_hash: str, request: Request) -> dict[str, Any]:
    """Retrieve an artifact by its content hash."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    store = getattr(engine, '_artifact_store', None)
    if store is None:
        raise HTTPException(status_code=503, detail="Artifact store not initialized")
    artifact = store.get_by_hash(content_hash)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact '{content_hash}' not found")
    return {
        "artifact_id": artifact.artifact_id,
        "work_id": artifact.work_id,
        "phase_id": artifact.phase_id,
        "agent_id": artifact.agent_id,
        "artifact_type": artifact.artifact_type,
        "content_hash": artifact.content_hash,
        "content": artifact.content,
        "version": artifact.version,
        "timestamp": artifact.timestamp.isoformat(),
        "run_id": artifact.run_id,
        "app_id": artifact.app_id,
    }


# ---- Gap Detection & Agent Synthesis Routes ----


class GapResponse(BaseModel):
    """Capability gap response."""
    id: str
    phase_id: str
    agent_id: str | None = None
    gap_source: str
    severity: str
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_capabilities: list[str] = Field(default_factory=list)
    detected_at: str = ""
    run_id: str = ""


class GapSummaryResponse(BaseModel):
    """Aggregated gap statistics."""
    total_gaps: int = 0
    by_phase: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)


class SynthesisRequest(BaseModel):
    """Request to generate a synthesis proposal for a gap."""
    gap_id: str


class SynthesisProposalResponse(BaseModel):
    """Synthesis proposal response."""
    id: str
    gap_id: str
    agent_spec: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    confidence: float = 0.0
    requires_approval: bool = True
    status: str = "pending"
    created_at: str = ""
    feedback: str = ""


class SynthesisTestResponse(BaseModel):
    """Result of pre-deployment validation and testing."""
    passed: bool
    proposal_id: str
    checks: dict[str, str] = Field(default_factory=dict)


class SynthesisRejectRequest(BaseModel):
    """Request body for rejecting a synthesis proposal."""
    feedback: str = ""


def _gap_to_response(gap: Any) -> GapResponse:
    """Convert a CapabilityGap to a GapResponse."""
    return GapResponse(
        id=gap.id,
        phase_id=gap.phase_id,
        agent_id=gap.agent_id,
        gap_source=gap.gap_source.value if hasattr(gap.gap_source, "value") else str(gap.gap_source),
        severity=gap.severity.value if hasattr(gap.severity, "value") else str(gap.severity),
        description=gap.description,
        evidence=gap.evidence,
        suggested_capabilities=list(gap.suggested_capabilities),
        detected_at=gap.detected_at.isoformat() if hasattr(gap.detected_at, "isoformat") else str(gap.detected_at),
        run_id=gap.run_id,
    )


def _proposal_to_response(proposal: Any) -> SynthesisProposalResponse:
    """Convert a SynthesisProposal to a response."""
    return SynthesisProposalResponse(
        id=proposal.id,
        gap_id=proposal.gap_id,
        agent_spec=proposal.agent_spec,
        rationale=proposal.rationale,
        confidence=proposal.confidence,
        requires_approval=proposal.requires_approval,
        status=proposal.status,
        created_at=proposal.created_at.isoformat() if hasattr(proposal.created_at, "isoformat") else str(proposal.created_at),
        feedback=proposal.feedback,
    )


gaps_router = APIRouter()


@gaps_router.get("/gaps", response_model=list[GapResponse])
async def list_gaps(request: Request) -> list[GapResponse]:
    """List all detected capability gaps (static + runtime)."""
    engine = _get_engine(request)
    if engine is None:
        return []
    gaps = getattr(engine, "detected_gaps", [])
    return [_gap_to_response(g) for g in gaps]


@gaps_router.get("/gaps/summary", response_model=GapSummaryResponse)
async def get_gap_summary(request: Request) -> GapSummaryResponse:
    """Get aggregated gap statistics by phase, severity, and source."""
    engine = _get_engine(request)
    if engine is None:
        return GapSummaryResponse()
    gaps = getattr(engine, "detected_gaps", [])
    by_phase: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for g in gaps:
        by_phase[g.phase_id] = by_phase.get(g.phase_id, 0) + 1
        sev = g.severity.value if hasattr(g.severity, "value") else str(g.severity)
        by_severity[sev] = by_severity.get(sev, 0) + 1
        src = g.gap_source.value if hasattr(g.gap_source, "value") else str(g.gap_source)
        by_source[src] = by_source.get(src, 0) + 1
    return GapSummaryResponse(
        total_gaps=len(gaps),
        by_phase=by_phase,
        by_severity=by_severity,
        by_source=by_source,
    )


@gaps_router.get("/gaps/{gap_id}", response_model=GapResponse)
async def get_gap(gap_id: str, request: Request) -> GapResponse:
    """Get details of a specific capability gap."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    gaps = getattr(engine, "detected_gaps", [])
    for g in gaps:
        if g.id == gap_id:
            return _gap_to_response(g)
    raise HTTPException(status_code=404, detail=f"Gap '{gap_id}' not found")


@gaps_router.post("/synthesis/propose", response_model=SynthesisProposalResponse)
async def propose_synthesis(body: SynthesisRequest, request: Request) -> SynthesisProposalResponse:
    """Generate a synthesis proposal to fill a detected capability gap."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    synthesizer = getattr(engine, "_synthesizer", None)
    if synthesizer is None:
        raise HTTPException(status_code=503, detail="Agent synthesizer not initialized")

    # Find the gap
    gaps = getattr(engine, "detected_gaps", [])
    gap = None
    for g in gaps:
        if g.id == body.gap_id:
            gap = g
            break
    if gap is None:
        raise HTTPException(status_code=404, detail=f"Gap '{body.gap_id}' not found")

    # Get current profile for context
    config_mgr = getattr(request.app.state, "config_manager", None) or getattr(engine, "_config", None)
    if config_mgr is None:
        raise HTTPException(status_code=503, detail="Configuration manager not available")
    try:
        profile = config_mgr.get_profile()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load profile: {exc}") from exc

    proposal = await synthesizer.propose(gap, profile)

    # Audit log
    if engine.audit_logger is not None:
        engine.audit_logger.append(
            RecordType.DECISION,
            "synthesis.proposed",
            f"Synthesis proposal '{proposal.id}' for gap '{gap.id}'",
            data={"proposal_id": proposal.id, "gap_id": gap.id, "confidence": proposal.confidence},
        )

    return _proposal_to_response(proposal)


@gaps_router.get("/synthesis/proposals", response_model=list[SynthesisProposalResponse])
async def list_proposals(
    request: Request, status: str | None = None,
) -> list[SynthesisProposalResponse]:
    """List synthesis proposals, optionally filtered by status."""
    engine = _get_engine(request)
    if engine is None:
        return []
    synthesizer = getattr(engine, "_synthesizer", None)
    if synthesizer is None:
        return []
    proposals = synthesizer.list_proposals(status=status)
    return [_proposal_to_response(p) for p in proposals]


@gaps_router.post(
    "/synthesis/proposals/{proposal_id}/test",
    response_model=SynthesisTestResponse,
)
async def test_proposal(proposal_id: str, request: Request) -> SynthesisTestResponse:
    """Run pre-deployment validation and dry-run test on a proposal.

    Checks schema validity, phase compatibility, and fires a probe
    LLM call to verify the synthesized agent can respond.
    """
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    synthesizer = getattr(engine, "_synthesizer", None)
    if synthesizer is None:
        raise HTTPException(status_code=503, detail="Agent synthesizer not initialized")

    profile = engine.active_profile
    if profile is None:
        raise HTTPException(status_code=503, detail="No active profile loaded")

    result = await synthesizer.validate_and_test(proposal_id, profile)
    return SynthesisTestResponse(
        passed=result.passed,
        proposal_id=result.proposal_id,
        checks=dict(result.checks),
    )


@gaps_router.post(
    "/synthesis/proposals/{proposal_id}/approve",
    response_model=SynthesisProposalResponse,
)
async def approve_proposal(proposal_id: str, request: Request) -> SynthesisProposalResponse:
    """Approve a synthesis proposal — validates, tests, then deploys.

    Runs pre-deployment validation before deploying. If validation
    fails, the proposal is not approved and a 422 is returned with
    the failing checks.
    """
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    synthesizer = getattr(engine, "_synthesizer", None)
    if synthesizer is None:
        raise HTTPException(status_code=503, detail="Agent synthesizer not initialized")

    # Pre-deployment validation and test
    profile = engine.active_profile
    if profile is None:
        raise HTTPException(status_code=503, detail="No active profile loaded")

    test_result = await synthesizer.validate_and_test(proposal_id, profile)
    if not test_result.passed:
        failed = {k: v for k, v in test_result.checks.items() if v.startswith("fail")}
        raise HTTPException(
            status_code=422,
            detail=f"Pre-deployment test failed: {failed}",
        )

    proposal = synthesizer.approve_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found")

    # Deploy the agent via engine
    try:
        agent_spec = dict(proposal.agent_spec)
        agent_spec["enabled"] = True
        await engine.register_agent(agent_spec)
        synthesizer.mark_deployed(proposal_id)
    except (AgentError, OrchestratorError) as exc:
        raise HTTPException(status_code=422, detail=f"Failed to deploy agent: {exc}") from exc

    # Audit log
    if engine.audit_logger is not None:
        engine.audit_logger.append(
            RecordType.DECISION,
            "synthesis.approved",
            f"Proposal '{proposal_id}' approved and agent deployed",
            data={
                "proposal_id": proposal_id,
                "agent_id": proposal.agent_spec.get("id", ""),
                "test_checks": dict(test_result.checks),
            },
        )

    # Emit event
    await engine.event_bus.emit(Event(
        type=EventType.AGENT_CREATED,
        data={
            "agent_id": proposal.agent_spec.get("id", ""),
            "source": "synthesis",
            "proposal_id": proposal_id,
        },
        source="synthesis",
    ))

    updated = synthesizer.get_proposal(proposal_id)
    return _proposal_to_response(updated or proposal)


@gaps_router.post(
    "/synthesis/proposals/{proposal_id}/reject",
    response_model=SynthesisProposalResponse,
)
async def reject_proposal(
    proposal_id: str, body: SynthesisRejectRequest, request: Request,
) -> SynthesisProposalResponse:
    """Reject a synthesis proposal with optional feedback."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    synthesizer = getattr(engine, "_synthesizer", None)
    if synthesizer is None:
        raise HTTPException(status_code=503, detail="Agent synthesizer not initialized")

    proposal = synthesizer.reject_proposal(proposal_id, feedback=body.feedback)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found")

    if engine.audit_logger is not None:
        engine.audit_logger.append(
            RecordType.DECISION,
            "synthesis.rejected",
            f"Proposal '{proposal_id}' rejected",
            data={"proposal_id": proposal_id, "feedback": body.feedback},
        )

    return _proposal_to_response(proposal)
