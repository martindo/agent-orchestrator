"""PhaseExecutor — Runs all agents assigned to a phase.

Gets agent list from phase config, acquires instances from pool,
executes each via AgentExecutor (parallel or sequential),
and reports results back.

Thread-safe: Stateless — receives all dependencies via constructor.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agent_orchestrator.configuration.models import WorkflowPhaseConfig
from agent_orchestrator.core.agent_executor import AgentExecutor, ExecutionResult
from agent_orchestrator.core.agent_pool import AgentPool
from agent_orchestrator.core.event_bus import Event, EventBus, EventType
from agent_orchestrator.core.work_queue import WorkItem
from agent_orchestrator.exceptions import WorkflowError

logger = logging.getLogger(__name__)

ACQUIRE_RETRY_DELAY_SECONDS = 0.5
MAX_ACQUIRE_RETRIES = 20


@dataclass
class PhaseExecutionResult:
    """Result of executing all agents in a phase."""

    phase_id: str
    work_id: str
    success: bool
    agent_results: list[ExecutionResult] = field(default_factory=list)
    error: str | None = None


class PhaseExecutor:
    """Executes all agents in a workflow phase.

    Thread-safe: Stateless — all state passed via method parameters.
    """

    def __init__(
        self,
        agent_pool: AgentPool,
        agent_executor: AgentExecutor,
        event_bus: EventBus,
    ) -> None:
        self._pool = agent_pool
        self._executor = agent_executor
        self._event_bus = event_bus

    async def execute_phase(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        phase_context: dict[str, Any] | None = None,
    ) -> PhaseExecutionResult:
        """Execute all agents assigned to a phase.

        If phase.parallel is True, agents run concurrently.
        Otherwise, they run sequentially.

        Args:
            phase: Phase configuration.
            work_item: Work item being processed.
            phase_context: Additional context for agents.

        Returns:
            PhaseExecutionResult with per-agent results.
        """
        logger.info(
            "Executing phase '%s' for work item '%s' (%d agents, parallel=%s)",
            phase.id, work_item.id, len(phase.agents), phase.parallel,
        )

        await self._event_bus.emit(Event(
            type=EventType.WORK_PHASE_ENTERED,
            data={"work_id": work_item.id, "phase_id": phase.id},
            source="phase_executor",
        ))

        if not phase.agents:
            result = PhaseExecutionResult(
                phase_id=phase.id,
                work_id=work_item.id,
                success=True,
            )
            await self._emit_phase_exit(phase, work_item, result)
            return result

        if phase.parallel:
            agent_results = await self._execute_parallel(
                phase, work_item, phase_context or {},
            )
        else:
            agent_results = await self._execute_sequential(
                phase, work_item, phase_context or {},
            )

        success = all(r.success for r in agent_results)
        errors = [r.error for r in agent_results if r.error]

        result = PhaseExecutionResult(
            phase_id=phase.id,
            work_id=work_item.id,
            success=success,
            agent_results=agent_results,
            error="; ".join(errors) if errors else None,
        )

        # Merge agent outputs into work item results
        for ar in agent_results:
            if ar.success and ar.output:
                work_item.results[ar.agent_id] = ar.output

        await self._emit_phase_exit(phase, work_item, result)
        return result

    async def _execute_parallel(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        phase_context: dict[str, Any],
    ) -> list[ExecutionResult]:
        """Execute agents concurrently."""
        tasks = [
            self._execute_single_agent(agent_id, phase, work_item, phase_context)
            for agent_id in phase.agents
        ]
        return await asyncio.gather(*tasks)

    async def _execute_sequential(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        phase_context: dict[str, Any],
    ) -> list[ExecutionResult]:
        """Execute agents one at a time."""
        results: list[ExecutionResult] = []
        for agent_id in phase.agents:
            result = await self._execute_single_agent(
                agent_id, phase, work_item, phase_context,
            )
            results.append(result)
            # Stop on failure for sequential execution
            if not result.success:
                logger.warning(
                    "Agent '%s' failed in sequential phase '%s', stopping",
                    agent_id, phase.id,
                )
                break
        return results

    async def _execute_single_agent(
        self,
        agent_id: str,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        phase_context: dict[str, Any],
    ) -> ExecutionResult:
        """Acquire an agent instance and execute it."""
        # Try to acquire agent instance with retry
        instance = None
        for attempt in range(MAX_ACQUIRE_RETRIES):
            instance = self._pool.acquire(agent_id, work_item.id)
            if instance is not None:
                break
            await asyncio.sleep(ACQUIRE_RETRY_DELAY_SECONDS)

        if instance is None:
            error_msg = f"Could not acquire agent '{agent_id}' after {MAX_ACQUIRE_RETRIES} retries"
            logger.error(error_msg)
            return ExecutionResult(
                agent_id=agent_id,
                instance_id="",
                work_id=work_item.id,
                phase_id=phase.id,
                success=False,
                error=error_msg,
            )

        await self._event_bus.emit(Event(
            type=EventType.AGENT_STARTED,
            data={
                "agent_id": agent_id,
                "instance_id": instance.instance_id,
                "work_id": work_item.id,
                "phase_id": phase.id,
            },
            source="phase_executor",
        ))

        try:
            result = await self._executor.execute(
                instance, work_item, phase.id, phase_context,
            )
            self._pool.release(instance.instance_id, success=result.success)

            event_type = EventType.AGENT_COMPLETED if result.success else EventType.AGENT_ERROR
            await self._event_bus.emit(Event(
                type=event_type,
                data={
                    "agent_id": agent_id,
                    "instance_id": instance.instance_id,
                    "work_id": work_item.id,
                    "success": result.success,
                    "duration": result.duration_seconds,
                },
                source="phase_executor",
            ))
            return result
        except Exception as e:
            self._pool.release(instance.instance_id, success=False)
            logger.error(
                "Unexpected error executing agent '%s': %s", agent_id, e, exc_info=True,
            )
            return ExecutionResult(
                agent_id=agent_id,
                instance_id=instance.instance_id,
                work_id=work_item.id,
                phase_id=phase.id,
                success=False,
                error=str(e),
            )

    async def _emit_phase_exit(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        result: PhaseExecutionResult,
    ) -> None:
        """Emit phase exit event."""
        await self._event_bus.emit(Event(
            type=EventType.WORK_PHASE_EXITED,
            data={
                "work_id": work_item.id,
                "phase_id": phase.id,
                "success": result.success,
            },
            source="phase_executor",
        ))
