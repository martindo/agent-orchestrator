"""Routes for workflow graph validation and analysis.

POST /api/studio/graph/validate — validate the workflow graph
GET  /api/studio/graph          — get graph nodes and edges
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from studio.graph.validator import validate_graph, GraphValidationResult
from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/graph", tags=["graph"])


def _require_team(request: Request) -> TeamSpec:
    """Get the current team or raise 404."""
    state = request.app.state.studio_state  # type: ignore[attr-defined]
    team: TeamSpec | None = state.get("current_team")
    if team is None:
        raise HTTPException(status_code=404, detail="No team loaded")
    return team


def _result_to_dict(result: GraphValidationResult) -> dict[str, Any]:
    """Convert graph validation result to a JSON-serializable dict."""
    return {
        "is_valid": result.is_valid,
        "nodes": [
            {
                "phase_id": n.phase_id,
                "name": n.name,
                "is_terminal": n.is_terminal,
                "order": n.order,
                "agent_count": n.agent_count,
            }
            for n in result.nodes
        ],
        "edges": [
            {
                "from_phase": e.from_phase,
                "to_phase": e.to_phase,
                "trigger": e.trigger,
            }
            for e in result.edges
        ],
        "errors": result.errors,
        "warnings": result.warnings,
        "orphan_phases": result.orphan_phases,
    }


@router.get("", response_model=None)
def get_graph(request: Request) -> dict[str, Any]:
    """Get the workflow graph structure (nodes and edges)."""
    team = _require_team(request)
    result = validate_graph(team.workflow)
    return _result_to_dict(result)


@router.post("/validate", response_model=None)
def validate_workflow_graph(request: Request) -> dict[str, Any]:
    """Validate the workflow phase graph for structural issues."""
    team = _require_team(request)
    result = validate_graph(team.workflow)
    return _result_to_dict(result)
