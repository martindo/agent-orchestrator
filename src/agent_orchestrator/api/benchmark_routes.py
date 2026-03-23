"""REST API routes for benchmark suites and runs.

Provides endpoints to create, execute, query, and manage benchmark suites
that test workflows against expected outcomes for regression detection.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

benchmark_router = APIRouter()


# ---- Request Models ----


class BenchmarkCaseRequest(BaseModel):
    """A single benchmark case in a create-suite request."""

    case_id: str
    work_item_data: dict[str, Any] = Field(default_factory=dict)
    expected_status: str = "completed"
    expected_min_confidence: float = 0.0
    expected_output_keys: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CreateSuiteRequest(BaseModel):
    """Request body for creating a benchmark suite."""

    name: str
    description: str = ""
    profile_name: str = ""
    cases: list[BenchmarkCaseRequest] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CreateSuiteFromHistoryRequest(BaseModel):
    """Request body for creating a suite from historical work items."""

    suite_name: str
    min_confidence: float = 0.0
    items: list[dict[str, Any]] = Field(default_factory=list)


# ---- Helpers ----


def _get_benchmark_store(request: Request) -> Any:
    """Extract BenchmarkStore from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The BenchmarkStore instance.

    Raises:
        HTTPException: 503 if unavailable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    store = getattr(engine, "benchmark_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Benchmark store not initialized")
    return store


def _get_benchmark_runner(request: Request) -> Any:
    """Extract BenchmarkRunner from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The BenchmarkRunner instance.

    Raises:
        HTTPException: 503 if unavailable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    runner = getattr(engine, "benchmark_runner", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="Benchmark runner not initialized")
    return runner


def _serialize_suite(suite: Any) -> dict[str, Any]:
    """Serialize a BenchmarkSuiteConfig to a JSON-compatible dict.

    Args:
        suite: The suite config to serialize.

    Returns:
        Serialized suite dict.
    """
    return {
        "suite_id": suite.suite_id,
        "name": suite.name,
        "description": suite.description,
        "profile_name": suite.profile_name,
        "created_at": suite.created_at,
        "tags": suite.tags,
        "case_count": len(suite.cases),
        "cases": [asdict(c) for c in suite.cases],
    }


def _serialize_suite_summary(suite: Any) -> dict[str, Any]:
    """Serialize a suite without full case details.

    Args:
        suite: The suite config to serialize.

    Returns:
        Summary dict without individual case data.
    """
    return {
        "suite_id": suite.suite_id,
        "name": suite.name,
        "description": suite.description,
        "profile_name": suite.profile_name,
        "created_at": suite.created_at,
        "tags": suite.tags,
        "case_count": len(suite.cases),
    }


def _serialize_run(result: Any) -> dict[str, Any]:
    """Serialize a BenchmarkRunResult to a JSON-compatible dict.

    Args:
        result: The run result to serialize.

    Returns:
        Serialized run result dict.
    """
    return {
        "run_id": result.run_id,
        "suite_id": result.suite_id,
        "status": result.status,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "duration_seconds": result.duration_seconds,
        "total_cases": result.total_cases,
        "passed": result.passed,
        "failed": result.failed,
        "pass_rate": result.pass_rate,
        "case_results": [
            {
                "case_id": cr.case_id,
                "passed": cr.passed,
                "actual_status": cr.actual_status,
                "actual_confidence": cr.actual_confidence,
                "failure_reasons": cr.failure_reasons,
                "duration_seconds": cr.duration_seconds,
            }
            for cr in result.case_results
        ],
    }


# ---- Routes ----


@benchmark_router.get("/benchmarks/suites")
async def list_suites(request: Request) -> list[dict[str, Any]]:
    """List all benchmark suites.

    Returns:
        All suites (newest first), without full case details.
    """
    store = _get_benchmark_store(request)
    suites = store.list_suites()
    return [_serialize_suite_summary(s) for s in suites]


@benchmark_router.post("/benchmarks/suites", status_code=201)
async def create_suite(
    body: CreateSuiteRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a new benchmark suite.

    Args:
        body: Suite definition with cases.
        request: The incoming HTTP request.

    Returns:
        The created suite.
    """
    store = _get_benchmark_store(request)

    import uuid

    from agent_orchestrator.simulation.models import (
        BenchmarkCase,
        BenchmarkSuiteConfig,
    )

    suite = BenchmarkSuiteConfig(
        suite_id=f"suite-{uuid.uuid4().hex[:8]}",
        name=body.name,
        description=body.description,
        profile_name=body.profile_name,
        cases=[
            BenchmarkCase(
                case_id=c.case_id,
                work_item_data=c.work_item_data,
                expected_status=c.expected_status,
                expected_min_confidence=c.expected_min_confidence,
                expected_output_keys=c.expected_output_keys,
                tags=c.tags,
            )
            for c in body.cases
        ],
        tags=body.tags,
    )

    store.save_suite(suite)
    logger.info("Created benchmark suite %s with %d cases", suite.suite_id, len(suite.cases))
    return _serialize_suite(suite)


@benchmark_router.get("/benchmarks/suites/{suite_id}")
async def get_suite(
    suite_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get a benchmark suite with full case details.

    Args:
        suite_id: The suite identifier.
        request: The incoming HTTP request.

    Returns:
        Full suite with all cases.
    """
    store = _get_benchmark_store(request)
    suite = store.load_suite(suite_id)
    if suite is None:
        raise HTTPException(
            status_code=404,
            detail=f"Benchmark suite '{suite_id}' not found",
        )
    return _serialize_suite(suite)


@benchmark_router.delete("/benchmarks/suites/{suite_id}")
async def delete_suite(
    suite_id: str,
    request: Request,
) -> dict[str, Any]:
    """Delete a benchmark suite.

    Args:
        suite_id: The suite to delete.
        request: The incoming HTTP request.

    Returns:
        Deletion confirmation.
    """
    store = _get_benchmark_store(request)
    deleted = store.delete_suite(suite_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Benchmark suite '{suite_id}' not found",
        )
    logger.info("Deleted benchmark suite %s", suite_id)
    return {"suite_id": suite_id, "deleted": True}


@benchmark_router.post("/benchmarks/suites/{suite_id}/run", status_code=201)
async def run_suite(
    suite_id: str,
    request: Request,
) -> dict[str, Any]:
    """Execute a benchmark suite and store the run result.

    Args:
        suite_id: The suite to run.
        request: The incoming HTTP request.

    Returns:
        Full run result with per-case details.
    """
    store = _get_benchmark_store(request)
    runner = _get_benchmark_runner(request)

    suite = store.load_suite(suite_id)
    if suite is None:
        raise HTTPException(
            status_code=404,
            detail=f"Benchmark suite '{suite_id}' not found",
        )

    result = await runner.run_suite(suite)
    store.save_run(result)

    logger.info(
        "Benchmark suite %s run %s: %d/%d passed (%.1f%%)",
        suite_id,
        result.run_id,
        result.passed,
        result.total_cases,
        result.pass_rate * 100,
    )
    return _serialize_run(result)


@benchmark_router.post("/benchmarks/suites/from-history", status_code=201)
async def create_suite_from_history(
    body: CreateSuiteFromHistoryRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a benchmark suite from completed work items.

    Uses historical outcomes as expected results so future workflow
    changes can be tested for regressions.

    Args:
        body: History items and suite configuration.
        request: The incoming HTTP request.

    Returns:
        The created suite.
    """
    store = _get_benchmark_store(request)

    from agent_orchestrator.simulation.benchmark import BenchmarkRunner

    items = body.items
    if not items:
        # Try to collect from engine
        engine = getattr(request.app.state, "engine", None)
        items = _collect_completed_items(engine)

    suite = BenchmarkRunner.create_suite_from_history(
        items=items,
        suite_name=body.suite_name,
        min_confidence=body.min_confidence,
    )

    store.save_suite(suite)
    logger.info(
        "Created benchmark suite %s from history with %d cases",
        suite.suite_id, len(suite.cases),
    )
    return _serialize_suite(suite)


@benchmark_router.get("/benchmarks/suites/{suite_id}/runs")
async def list_runs(
    suite_id: str,
    request: Request,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List run results for a benchmark suite.

    Args:
        suite_id: The suite to list runs for.
        request: The incoming HTTP request.
        limit: Maximum number of runs to return.

    Returns:
        Run results for the suite, newest first.
    """
    store = _get_benchmark_store(request)
    runs = store.get_runs(suite_id, limit=limit)
    return [_serialize_run(r) for r in runs]


@benchmark_router.get("/benchmarks/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get a detailed benchmark run result.

    Args:
        run_id: The run identifier.
        request: The incoming HTTP request.

    Returns:
        Full run result with per-case details.
    """
    store = _get_benchmark_store(request)
    result = store.get_run(run_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Benchmark run '{run_id}' not found",
        )
    return _serialize_run(result)


def _collect_completed_items(engine: Any) -> list[dict[str, Any]]:
    """Collect completed work items from the engine if available.

    Args:
        engine: The OrchestrationEngine instance.

    Returns:
        List of completed work item dicts.
    """
    if engine is None:
        return []

    try:
        items = engine.list_work_items()
        completed: list[dict[str, Any]] = []
        for item in items:
            if item.get("status") in ("completed", "COMPLETED"):
                completed.append({
                    "id": item.get("id", ""),
                    "data": item.get("data", {}),
                    "status": item.get("status", ""),
                    "results": item.get("results", {}),
                    "confidence": item.get("confidence", 0.0),
                })
        return completed
    except Exception as exc:
        logger.warning("Failed to collect completed items: %s", exc)
        return []
