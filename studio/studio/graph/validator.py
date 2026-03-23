"""Workflow graph validation and analysis.

Provides Studio-side graph validation as a superset of what the runtime's
``validate_phase_graph()`` checks.  Returns richer error messages with
node/edge context suitable for the frontend graph editor.

Checks performed:
- Terminal phase existence
- All transitions reference valid phases
- Orphan phase detection (unreachable from any non-terminal phase)
- Cycle detection (phases forming infinite loops with no terminal escape)
- Terminal reachability (every non-terminal phase can reach a terminal)
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from studio.ir.models import WorkflowSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphNode:
    """A node in the workflow graph.

    Attributes:
        phase_id: The phase ID.
        name: Display name.
        is_terminal: Whether this is a terminal phase.
        order: Phase ordering value.
        agent_count: Number of agents in this phase.
    """

    phase_id: str
    name: str
    is_terminal: bool
    order: int
    agent_count: int


@dataclass(frozen=True)
class GraphEdge:
    """A directed edge in the workflow graph.

    Attributes:
        from_phase: Source phase ID.
        to_phase: Target phase ID.
        trigger: Edge trigger ('on_success' or 'on_failure').
    """

    from_phase: str
    to_phase: str
    trigger: str


@dataclass
class GraphValidationResult:
    """Result of workflow graph validation.

    Attributes:
        nodes: All nodes in the graph.
        edges: All edges in the graph.
        errors: Blocking issues.
        warnings: Non-blocking issues.
        orphan_phases: Phase IDs not reachable from the start.
        unreachable_terminals: Terminal phases that cannot be reached.
    """

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    orphan_phases: list[str] = field(default_factory=list)
    unreachable_terminals: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if there are no errors."""
        return len(self.errors) == 0


def _build_adjacency(workflow: WorkflowSpec) -> dict[str, list[str]]:
    """Build an adjacency list from phase transitions."""
    adj: dict[str, list[str]] = {p.id: [] for p in workflow.phases}
    for phase in workflow.phases:
        if phase.on_success and phase.on_success in adj:
            adj[phase.id].append(phase.on_success)
        if phase.on_failure and phase.on_failure in adj:
            if phase.on_failure not in adj[phase.id]:
                adj[phase.id].append(phase.on_failure)
    return adj


def _find_reachable(adj: dict[str, list[str]], start_nodes: set[str]) -> set[str]:
    """BFS to find all nodes reachable from start_nodes."""
    visited: set[str] = set()
    queue: deque[str] = deque(start_nodes)
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited


def _can_reach_terminal(
    phase_id: str,
    adj: dict[str, list[str]],
    terminal_ids: set[str],
    memo: dict[str, bool],
) -> bool:
    """Check if a phase can reach any terminal phase via BFS."""
    if phase_id in memo:
        return memo[phase_id]

    visited: set[str] = set()
    queue: deque[str] = deque([phase_id])
    while queue:
        node = queue.popleft()
        if node in terminal_ids:
            memo[phase_id] = True
            return True
        if node in visited:
            continue
        visited.add(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                queue.append(neighbor)

    memo[phase_id] = False
    return False


def validate_graph(workflow: WorkflowSpec) -> GraphValidationResult:
    """Validate the workflow phase graph.

    Args:
        workflow: The workflow specification to validate.

    Returns:
        GraphValidationResult with nodes, edges, errors, and warnings.
    """
    result = GraphValidationResult()
    phase_ids = {p.id for p in workflow.phases}
    terminal_ids = {p.id for p in workflow.phases if p.is_terminal}

    # Build nodes
    for phase in workflow.phases:
        result.nodes.append(
            GraphNode(
                phase_id=phase.id,
                name=phase.name,
                is_terminal=phase.is_terminal,
                order=phase.order,
                agent_count=len(phase.agents),
            )
        )

    # Build edges and check references
    for phase in workflow.phases:
        if phase.on_success:
            if phase.on_success not in phase_ids:
                result.errors.append(
                    f"Phase '{phase.id}' on_success references unknown phase '{phase.on_success}'"
                )
            else:
                result.edges.append(
                    GraphEdge(from_phase=phase.id, to_phase=phase.on_success, trigger="on_success")
                )
        if phase.on_failure:
            if phase.on_failure not in phase_ids:
                result.errors.append(
                    f"Phase '{phase.id}' on_failure references unknown phase '{phase.on_failure}'"
                )
            else:
                result.edges.append(
                    GraphEdge(from_phase=phase.id, to_phase=phase.on_failure, trigger="on_failure")
                )

    if not workflow.phases:
        result.warnings.append("Workflow has no phases")
        return result

    # Terminal phase existence
    if not terminal_ids:
        result.errors.append("No terminal phase defined — workflow cannot complete")
        return result

    # Find start phases (lowest order, non-terminal)
    non_terminal = [p for p in workflow.phases if not p.is_terminal]
    if not non_terminal:
        result.warnings.append("All phases are terminal")
        return result

    start_phases = {min(non_terminal, key=lambda p: p.order).id}

    # Orphan detection — phases not reachable from start
    adj = _build_adjacency(workflow)
    reachable = _find_reachable(adj, start_phases)
    for phase in workflow.phases:
        if phase.id not in reachable and phase.id not in start_phases:
            # Check if it's reachable as a target of any other phase
            is_targeted = any(
                phase.id in neighbors
                for neighbors in adj.values()
            )
            if not is_targeted and not phase.is_terminal:
                result.orphan_phases.append(phase.id)
                result.warnings.append(
                    f"Phase '{phase.id}' is not reachable from any other phase"
                )

    # Terminal reachability — every non-terminal phase should reach a terminal
    memo: dict[str, bool] = {}
    for phase in workflow.phases:
        if phase.is_terminal:
            continue
        if not _can_reach_terminal(phase.id, adj, terminal_ids, memo):
            result.errors.append(
                f"Phase '{phase.id}' cannot reach any terminal phase"
            )

    logger.info(
        "Graph validation: %d nodes, %d edges, %d errors, %d warnings",
        len(result.nodes),
        len(result.edges),
        len(result.errors),
        len(result.warnings),
    )
    return result
