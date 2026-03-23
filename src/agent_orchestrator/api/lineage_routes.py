"""REST API routes for work-item lineage tracing.

Provides endpoints to query the unified lineage of a work item
across all data sources (history, decisions, artifacts, audit).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

lineage_router = APIRouter()


def _get_lineage_builder(request: Request) -> Any:
    """Get or create a LineageBuilder from the engine's stores.

    Args:
        request: The incoming HTTP request.

    Returns:
        A LineageBuilder instance.

    Raises:
        HTTPException: 503 if engine or stores not available.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    from agent_orchestrator.persistence.lineage import LineageBuilder

    work_item_store = getattr(engine, "work_item_store", None)
    decision_ledger = getattr(engine, "decision_ledger", None)
    artifact_store = getattr(engine, "artifact_store", None)
    audit_logger = getattr(engine, "audit_logger", None)

    return LineageBuilder(
        work_item_store=work_item_store,
        decision_ledger=decision_ledger,
        artifact_store=artifact_store,
        audit_logger=audit_logger,
    )


@lineage_router.get("/work-items/{work_item_id}/lineage")
async def get_lineage(
    work_item_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get full chronological lineage for a work item.

    Joins events from WorkItem history, DecisionLedger, ArtifactStore,
    and AuditLogger into a single timeline.

    Args:
        work_item_id: The work item identifier.
        request: The incoming HTTP request.

    Returns:
        Complete lineage with events from all sources.
    """
    builder = _get_lineage_builder(request)
    lineage = builder.build_lineage(work_item_id)

    return {
        "work_item_id": lineage.work_item_id,
        "total_events": lineage.total_events,
        "decision_chain_valid": lineage.decision_chain_valid,
        "artifact_count": lineage.artifact_count,
        "events": [asdict(e) for e in lineage.events],
    }


@lineage_router.get("/work-items/{work_item_id}/decisions")
async def get_decisions(
    work_item_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get the decision chain for a work item.

    Returns only decisions from the DecisionLedger in chronological order.

    Args:
        work_item_id: The work item identifier.
        request: The incoming HTTP request.

    Returns:
        Decision chain with chain integrity status.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    ledger = getattr(engine, "decision_ledger", None)
    if ledger is None:
        return {"work_item_id": work_item_id, "decisions": [], "chain_valid": True}

    chain = ledger.get_decision_chain(work_item_id)
    valid, _count = ledger.verify_chain()

    return {
        "work_item_id": work_item_id,
        "decisions": chain,
        "chain_valid": valid,
        "total": len(chain),
    }


@lineage_router.get("/work-items/{work_item_id}/artifacts")
async def get_artifacts(
    work_item_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get all artifacts for a work item in chronological order.

    Args:
        work_item_id: The work item identifier.
        request: The incoming HTTP request.

    Returns:
        Artifact chain for the work item.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    store = getattr(engine, "artifact_store", None)
    if store is None:
        return {"work_item_id": work_item_id, "artifacts": [], "total": 0}

    artifacts = store.get_chain(work_item_id)
    serialized = []
    for a in artifacts:
        ts = a.timestamp
        timestamp_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        serialized.append({
            "artifact_id": a.artifact_id,
            "phase_id": a.phase_id,
            "agent_id": a.agent_id,
            "artifact_type": a.artifact_type,
            "content_hash": a.content_hash,
            "version": a.version,
            "timestamp": timestamp_str,
        })

    return {
        "work_item_id": work_item_id,
        "artifacts": serialized,
        "total": len(serialized),
    }
