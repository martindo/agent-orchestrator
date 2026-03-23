"""Simulation Executor — wraps PhaseExecutor for sandbox-compatible execution.

Adapts the engine's PhaseExecutor into an ``execute_fn`` that
SimulationSandbox.run_simulation() can call.  Creates ephemeral WorkItems
from historical data dicts and runs them through the configured workflow
phases, returning a result dict with status, confidence, results, and
phases_completed.

Thread-safe: Delegates to PhaseExecutor which is stateless.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus
from agent_orchestrator.simulation.models import SimulationConfig

if TYPE_CHECKING:
    from agent_orchestrator.core.engine import OrchestrationEngine

logger = logging.getLogger(__name__)

# Type alias for the execute_fn signature expected by SimulationSandbox
ExecuteFn = Callable[
    [dict[str, Any], SimulationConfig],
    Coroutine[Any, Any, dict[str, Any]],
]


def _build_ephemeral_work_item(work_data: dict[str, Any]) -> WorkItem:
    """Create a throwaway WorkItem from simulation input data.

    Args:
        work_data: Raw input data dict from a historical work item.

    Returns:
        A fresh WorkItem with a unique ID and the supplied data.
    """
    return WorkItem(
        id=f"sim-{uuid.uuid4().hex[:12]}",
        type_id=work_data.get("type_id", "simulation"),
        title=work_data.get("title", "Simulated work item"),
        data=work_data,
    )


def create_simulation_executor(engine: OrchestrationEngine) -> ExecuteFn:
    """Build an execute_fn compatible with SimulationSandbox.run_simulation().

    The returned coroutine runs a single work item through all workflow
    phases using the engine's PhaseExecutor.

    Args:
        engine: A fully initialised OrchestrationEngine (must be started).

    Returns:
        An async callable ``(work_data, config) -> result_dict``.
    """

    async def execute_fn(
        work_data: dict[str, Any],
        config: SimulationConfig,
    ) -> dict[str, Any]:
        """Execute a single work item through the engine's workflow phases.

        Args:
            work_data: Input data for the work item.
            config: Simulation configuration (used for profile selection).

        Returns:
            Dict with keys: status, confidence, results, phases_completed.
        """
        return await _run_through_phases(engine, work_data, config)

    return execute_fn


async def _run_through_phases(
    engine: OrchestrationEngine,
    work_data: dict[str, Any],
    config: SimulationConfig,
) -> dict[str, Any]:
    """Run work_data through all configured workflow phases.

    Args:
        engine: The orchestration engine providing phase executor and config.
        work_data: Raw input data for the work item.
        config: Simulation config (profile_name selects workflow phases).

    Returns:
        Dict with status, confidence, results, and phases_completed.
    """
    work_item = _build_ephemeral_work_item(work_data)
    phases = _resolve_phases(engine, config)

    if not phases:
        logger.warning(
            "No workflow phases found for simulation %s", config.simulation_id,
        )
        return _failure_result("No workflow phases configured")

    phase_executor = engine._phase_executor  # noqa: SLF001
    if phase_executor is None:
        logger.error("Engine phase executor not initialised — is the engine started?")
        return _failure_result("Engine not started")

    phases_completed = 0
    all_results: dict[str, Any] = {}
    overall_confidence = 0.0

    try:
        for phase in phases:
            phase_result = await phase_executor.execute_phase(
                phase=phase,
                work_item=work_item,
                phase_context=None,
                context=engine.context,
            )

            phases_completed += 1
            overall_confidence = phase_result.aggregate_confidence

            # Merge per-agent outputs into cumulative results
            for agent_result in phase_result.agent_results:
                if agent_result.success and agent_result.output:
                    all_results[agent_result.agent_id] = agent_result.output

            if not phase_result.success:
                return {
                    "status": WorkItemStatus.FAILED.value,
                    "confidence": overall_confidence,
                    "results": all_results,
                    "phases_completed": phases_completed,
                }
    except Exception as exc:
        logger.error(
            "Simulation execution failed at phase %d for work item %s: %s",
            phases_completed + 1,
            work_item.id,
            exc,
            exc_info=True,
        )
        return _failure_result(str(exc), all_results, phases_completed)

    return {
        "status": WorkItemStatus.COMPLETED.value,
        "confidence": overall_confidence,
        "results": all_results,
        "phases_completed": phases_completed,
    }


def _resolve_phases(
    engine: OrchestrationEngine,
    config: SimulationConfig,
) -> list[Any]:
    """Resolve the workflow phases to execute from the engine or config.

    Uses the engine's current profile phases. If the simulation config
    specifies a different profile_name, attempts to load that profile's
    phases instead.

    Args:
        engine: The orchestration engine.
        config: Simulation configuration.

    Returns:
        List of WorkflowPhaseConfig objects.
    """
    if config.profile_name:
        active = engine.active_profile
        if active is not None and active.name != config.profile_name:
            logger.warning(
                "Simulation targets profile '%s' but engine has '%s' active; "
                "using active profile phases",
                config.profile_name,
                active.name,
            )

    return engine.get_workflow_phases()


def _failure_result(
    error: str,
    results: dict[str, Any] | None = None,
    phases_completed: int = 0,
) -> dict[str, Any]:
    """Build a standardised failure result dict.

    Args:
        error: Error description.
        results: Any partial agent results collected before failure.
        phases_completed: Number of phases completed before failure.

    Returns:
        Dict with failed status and error details.
    """
    return {
        "status": WorkItemStatus.FAILED.value,
        "confidence": 0.0,
        "results": results or {},
        "phases_completed": phases_completed,
    }
