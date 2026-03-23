"""REST API routes for the cryptographic decision ledger.

Provides query, verification, and summary endpoints for the
tamper-evident decision chain.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

ledger_router = APIRouter()


# ---- Helpers ----


def _get_decision_ledger(request: Request) -> Any:
    """Extract DecisionLedger from engine, raising 503 if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        The DecisionLedger instance.

    Raises:
        HTTPException: 503 if unavailable.
    """
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    ledger = getattr(engine, "decision_ledger", None)
    if ledger is None:
        raise HTTPException(status_code=503, detail="Decision ledger not initialized")
    return ledger


# ---- Routes ----


@ledger_router.get("/ledger/decisions")
async def query_decisions(
    request: Request,
    work_item_id: str | None = None,
    agent_id: str | None = None,
    decision_type: str | None = None,
    outcome: str | None = None,
    phase_id: str | None = None,
    run_id: str | None = None,
    app_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query decision records with optional filters.

    Args:
        request: The incoming HTTP request.
        work_item_id: Filter by work item.
        agent_id: Filter by agent.
        decision_type: Filter by decision type.
        outcome: Filter by outcome.
        phase_id: Filter by phase.
        run_id: Filter by run.
        app_id: Filter by application.
        limit: Maximum records to return.

    Returns:
        Matching decision records (newest first).
    """
    ledger = _get_decision_ledger(request)

    from agent_orchestrator.governance.decision_ledger import (
        DecisionOutcome,
        DecisionType,
    )

    parsed_type = None
    if decision_type:
        try:
            parsed_type = DecisionType(decision_type)
        except ValueError:
            valid = [t.value for t in DecisionType]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid decision_type '{decision_type}'. Valid: {valid}",
            )

    parsed_outcome = None
    if outcome:
        try:
            parsed_outcome = DecisionOutcome(outcome)
        except ValueError:
            valid = [o.value for o in DecisionOutcome]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid outcome '{outcome}'. Valid: {valid}",
            )

    return ledger.query(
        work_item_id=work_item_id,
        agent_id=agent_id,
        decision_type=parsed_type,
        outcome=parsed_outcome,
        phase_id=phase_id,
        run_id=run_id,
        app_id=app_id,
        limit=limit,
    )


@ledger_router.get("/ledger/decisions/chain/{work_item_id}")
async def get_decision_chain(
    work_item_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    """Get the complete decision chain for a work item.

    Returns all decisions in chronological order, forming a complete
    forensic audit trail from submission to completion.

    Args:
        work_item_id: The work item to trace.
        request: The incoming HTTP request.

    Returns:
        Ordered list of decision records.
    """
    ledger = _get_decision_ledger(request)
    chain = ledger.get_decision_chain(work_item_id)
    if not chain:
        raise HTTPException(
            status_code=404,
            detail=f"No decisions found for work item '{work_item_id}'",
        )
    return chain


@ledger_router.get("/ledger/decisions/agent/{agent_id}")
async def get_agent_decisions(
    agent_id: str,
    request: Request,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get recent decisions made by a specific agent.

    Args:
        agent_id: The agent identifier.
        request: The incoming HTTP request.
        limit: Maximum records to return.

    Returns:
        Agent's decisions (newest first).
    """
    ledger = _get_decision_ledger(request)
    return ledger.get_agent_decisions(agent_id, limit=limit)


@ledger_router.get("/ledger/verify")
async def verify_chain(request: Request) -> dict[str, Any]:
    """Verify the integrity of the decision chain.

    Recomputes every hash and checks chain linkage. Any tampering
    or corruption is detected and reported.

    Returns:
        Verification result with integrity status and record count.
    """
    ledger = _get_decision_ledger(request)
    is_valid, records_verified = ledger.verify_chain()
    return {
        "chain_valid": is_valid,
        "records_verified": records_verified,
        "status": "intact" if is_valid else "tampered",
    }


@ledger_router.get("/ledger/summary")
async def ledger_summary(request: Request) -> dict[str, Any]:
    """Return summary statistics for the decision ledger.

    Returns:
        Summary with counts by type, outcome, and chain metadata.
    """
    ledger = _get_decision_ledger(request)
    return ledger.summary()
