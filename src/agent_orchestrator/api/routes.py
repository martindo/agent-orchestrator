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

from agent_orchestrator.configuration.models import PolicyConfig
from agent_orchestrator.configuration.validator import validate_profile
from agent_orchestrator.exceptions import AgentError, ConfigurationError, OrchestratorError
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


class WorkItemResponse(BaseModel):
    """Work item response."""
    id: str
    type_id: str
    title: str
    status: str = "pending"
    current_phase: str = ""


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

    work_item = WorkItem(
        id=body.id,
        type_id=body.type_id,
        title=body.title,
        data=body.data,
        priority=body.priority,
    )
    try:
        await engine.submit_work(work_item)
    except OrchestratorError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return WorkItemResponse(
        id=work_item.id,
        type_id=work_item.type_id,
        title=work_item.title,
        status=work_item.status.value,
        current_phase=work_item.current_phase,
    )


@workitems_router.get("/workitems/{work_id}", response_model=WorkItemResponse)
async def get_workitem(work_id: str, request: Request) -> WorkItemResponse:
    """Get work item details."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    item = engine.get_work_item(work_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Work item '{work_id}' not found")

    return WorkItemResponse(
        id=item.id,
        type_id=item.type_id,
        title=item.title,
        status=item.status.value,
        current_phase=item.current_phase,
    )


# ---- Governance Routes ----

governance_router = APIRouter()


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
