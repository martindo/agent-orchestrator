"""REST API routes for the simulation sandbox.

Provides endpoints to create, run, query, and compare simulations
of workflows against historical work items.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

simulation_router = APIRouter()


# ---- Request Models ----


class CreateSimulationRequest(BaseModel):
    """Request body for creating a simulation."""

    name: str = ""
    description: str = ""
    profile_name: str = ""
    workflow_overrides: dict[str, Any] = Field(default_factory=dict)
    max_items: int = 100
    include_types: list[str] = Field(default_factory=list)
    dry_run: bool = True


class RunSimulationRequest(BaseModel):
    """Request body for running a simulation with inline data."""

    name: str = ""
    description: str = ""
    profile_name: str = ""
    max_items: int = 100
    include_types: list[str] = Field(default_factory=list)
    dry_run: bool = True
    historical_items: list[dict[str, Any]] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    """Request body for replaying historical work items from the store."""

    name: str = ""
    profile_name: str = ""
    status_filter: str = "completed"
    type_id_filter: str | None = None
    app_id_filter: str | None = None
    max_items: int = 100
    dry_run: bool = False


# ---- Helpers ----


def _get_sandbox(request: Request) -> Any:
    """Extract SimulationSandbox from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The SimulationSandbox instance.

    Raises:
        HTTPException: 503 if unavailable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    sandbox = getattr(engine, "simulation_sandbox", None)
    if sandbox is None:
        raise HTTPException(status_code=503, detail="Simulation sandbox not initialized")
    return sandbox


def _serialize_result(result: Any) -> dict[str, Any]:
    """Serialize a SimulationResult to a JSON-compatible dict.

    Args:
        result: The SimulationResult to serialize.

    Returns:
        Serialized simulation result.
    """
    return {
        "simulation_id": result.simulation_id,
        "name": result.config.name,
        "status": result.status.value,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "duration_seconds": result.duration_seconds,
        "total_items": result.total_items,
        "items_processed": result.items_processed,
        "items_improved": result.items_improved,
        "items_regressed": result.items_regressed,
        "items_same": result.items_same,
        "items_new_success": result.items_new_success,
        "items_new_failure": result.items_new_failure,
        "items_errored": result.items_errored,
        "avg_historical_confidence": result.avg_historical_confidence,
        "avg_simulated_confidence": result.avg_simulated_confidence,
        "confidence_improvement": result.confidence_improvement,
        "improvement_rate": result.improvement_rate,
        "regression_rate": result.regression_rate,
        "errors": result.errors,
    }


def _serialize_result_with_comparisons(result: Any) -> dict[str, Any]:
    """Serialize a SimulationResult including per-item comparisons.

    Args:
        result: The SimulationResult to serialize.

    Returns:
        Full serialized simulation result with comparisons.
    """
    data = _serialize_result(result)
    data["comparisons"] = [
        {
            "work_item_id": c.work_item_id,
            "outcome": c.outcome.value,
            "historical_status": c.historical_status,
            "historical_confidence": c.historical_confidence,
            "simulated_status": c.simulated_status,
            "simulated_confidence": c.simulated_confidence,
            "confidence_delta": c.confidence_delta,
            "phase_delta": c.phase_delta,
            "notes": c.notes,
        }
        for c in result.comparisons
    ]
    return data


# ---- Routes ----


@simulation_router.get("/simulations/summary")
async def simulation_summary(request: Request) -> dict[str, Any]:
    """Return summary statistics for all simulations.

    Returns:
        Summary with counts by status and recent IDs.
    """
    sandbox = _get_sandbox(request)
    return sandbox.summary()


@simulation_router.get("/simulations")
async def list_simulations(request: Request) -> list[dict[str, Any]]:
    """List all simulation results.

    Returns:
        All simulations (newest first), without per-item details.
    """
    sandbox = _get_sandbox(request)
    return [_serialize_result(s) for s in sandbox.list_simulations()]


@simulation_router.get("/simulations/{simulation_id}")
async def get_simulation(
    simulation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get a simulation result with full per-item comparisons.

    Args:
        simulation_id: The simulation identifier.
        request: The incoming HTTP request.

    Returns:
        Full simulation result with comparisons.
    """
    sandbox = _get_sandbox(request)
    result = sandbox.get_simulation(simulation_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Simulation '{simulation_id}' not found",
        )
    return _serialize_result_with_comparisons(result)


@simulation_router.post("/simulations", status_code=201)
async def run_simulation(
    body: RunSimulationRequest,
    request: Request,
) -> dict[str, Any]:
    """Run a simulation with inline historical data.

    Creates and immediately executes a simulation against the provided
    historical work items. In dry_run mode (default), no LLM calls
    are made — results mirror historical outcomes for baseline comparison.

    Args:
        body: Simulation configuration and data.
        request: The incoming HTTP request.

    Returns:
        Full simulation result with comparisons.
    """
    sandbox = _get_sandbox(request)

    from agent_orchestrator.simulation.models import SimulationConfig

    config = SimulationConfig(
        simulation_id=f"sim-{uuid.uuid4().hex[:8]}",
        name=body.name or "API simulation",
        description=body.description,
        profile_name=body.profile_name,
        max_items=body.max_items,
        include_types=body.include_types,
        dry_run=body.dry_run,
    )

    if not body.historical_items:
        # Try to get items from the engine's work queue history
        engine = getattr(request.app.state, "engine", None)
        items = _collect_historical_items(engine, config.max_items)
    else:
        items = body.historical_items

    result = await sandbox.run_simulation(
        config=config,
        historical_items=items,
    )

    logger.info(
        "Simulation %s completed: %d items, improvement=%.1f%%",
        config.simulation_id,
        result.items_processed,
        result.improvement_rate * 100,
    )
    return _serialize_result_with_comparisons(result)


@simulation_router.post("/simulations/{simulation_id}/cancel")
async def cancel_simulation(
    simulation_id: str,
    request: Request,
) -> dict[str, Any]:
    """Cancel a running simulation.

    Args:
        simulation_id: The simulation to cancel.
        request: The incoming HTTP request.

    Returns:
        Cancellation status.
    """
    sandbox = _get_sandbox(request)
    cancelled = sandbox.cancel_simulation(simulation_id)
    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail=f"Simulation '{simulation_id}' not found or not running",
        )
    return {"simulation_id": simulation_id, "status": "cancelled"}


@simulation_router.post("/simulations/replay", status_code=201)
async def replay_simulation(
    body: ReplayRequest,
    request: Request,
) -> dict[str, Any]:
    """Replay historical work items from the persistent store.

    Queries the WorkItemStore for completed items and runs them through
    the SimulationSandbox with the real engine execute_fn.

    Args:
        body: Replay configuration.
        request: The incoming HTTP request.

    Returns:
        Simulation result with comparisons.
    """
    sandbox = _get_sandbox(request)
    engine = getattr(request.app.state, "engine", None)

    from agent_orchestrator.simulation.models import SimulationConfig

    config = SimulationConfig(
        simulation_id=f"replay-{uuid.uuid4().hex[:8]}",
        name=body.name or "Store replay",
        profile_name=body.profile_name,
        max_items=body.max_items,
        dry_run=body.dry_run,
    )

    items = _collect_historical_items(
        engine,
        body.max_items,
        status_filter=body.status_filter,
        type_id_filter=body.type_id_filter,
        app_id_filter=body.app_id_filter,
    )

    # Get execute_fn from simulation executor if not dry_run
    execute_fn = None
    if not body.dry_run and engine is not None:
        try:
            from agent_orchestrator.simulation.executor import (
                create_simulation_executor,
            )
            execute_fn = create_simulation_executor(engine)
        except Exception as exc:
            logger.warning("Could not create simulation executor: %s", exc)

    result = await sandbox.run_simulation(
        config=config,
        historical_items=items,
        execute_fn=execute_fn,
    )

    logger.info(
        "Replay %s completed: %d items, improvement=%.1f%%",
        config.simulation_id,
        result.items_processed,
        result.improvement_rate * 100,
    )
    return _serialize_result_with_comparisons(result)


def _collect_historical_items(
    engine: Any,
    max_items: int,
    status_filter: str = "completed",
    type_id_filter: str | None = None,
    app_id_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Collect historical work items from the WorkItemStore.

    Falls back to engine.list_work_items() if store is unavailable.

    Args:
        engine: The OrchestrationEngine instance.
        max_items: Maximum items to collect.
        status_filter: Status to filter by (default: completed).
        type_id_filter: Optional type_id filter.
        app_id_filter: Optional app_id filter.

    Returns:
        List of historical work item dicts.
    """
    if engine is None:
        return []

    # Prefer WorkItemStore for completed/historical items
    store = getattr(engine, "work_item_store", None)
    if store is not None:
        try:
            from agent_orchestrator.core.work_queue import WorkItemStatus
            status_enum = WorkItemStatus(status_filter) if status_filter else None
            items = store.query(
                status=status_enum,
                type_id=type_id_filter,
                app_id=app_id_filter,
                limit=max_items,
            )
            return [
                {
                    "id": item.id,
                    "type_id": item.type_id,
                    "data": item.data,
                    "status": item.status.value,
                    "results": item.results,
                    "confidence": _extract_item_confidence(item),
                    "phases_completed": len(item.results),
                }
                for item in items
            ]
        except Exception as exc:
            logger.warning("Failed to query work item store: %s", exc)

    # Fallback to in-flight pipeline items
    try:
        items = engine.list_work_items()
        return [
            {
                "id": item.get("id", ""),
                "type_id": item.get("type_id", ""),
                "data": item.get("data", {}),
                "status": item.get("status", ""),
                "results": item.get("results", {}),
                "confidence": item.get("confidence", 0.0),
                "phases_completed": item.get("phases_completed", 0),
            }
            for item in items[:max_items]
        ]
    except Exception as exc:
        logger.warning("Failed to collect historical items: %s", exc)
        return []


def _extract_item_confidence(item: Any) -> float:
    """Extract aggregate confidence from a work item's results."""
    try:
        from agent_orchestrator.core.output_parser import (
            aggregate_confidence,
            extract_confidence,
        )
        scores: list[float] = []
        for output in item.results.values():
            if isinstance(output, dict):
                scores.append(extract_confidence(output))
        return aggregate_confidence(scores)
    except Exception:
        return 0.0
