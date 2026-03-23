"""PhaseExecutor — Runs all agents assigned to a phase.

Gets agent list from phase config, acquires instances from pool,
executes each via AgentExecutor (parallel or sequential),
evaluates quality gates and optional critic agent, and reports results.

Thread-safe: Stateless — receives all dependencies via constructor.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_orchestrator.configuration.models import ExecutionContext
    from agent_orchestrator.persistence.artifact_store import ArtifactStore

from agent_orchestrator.configuration.models import WorkflowPhaseConfig
from agent_orchestrator.core.agent_executor import AgentExecutor, ExecutionResult
from agent_orchestrator.core.agent_pool import AgentPool
from agent_orchestrator.core.event_bus import Event, EventBus, EventType
from agent_orchestrator.core.output_parser import aggregate_confidence, extract_confidence
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
    aggregate_confidence: float = 0.5
    quality_gate_failures: list[str] = field(default_factory=list)
    critic_decision: str = ""
    retry_count: int = 0


class PhaseExecutor:
    """Executes all agents in a workflow phase.

    Supports quality gates, critic agents, and artifact capture.
    Thread-safe: Stateless — all state passed via method parameters.
    """

    def __init__(
        self,
        agent_pool: AgentPool,
        agent_executor: AgentExecutor,
        event_bus: EventBus,
        artifact_store: "ArtifactStore | None" = None,
    ) -> None:
        self._pool = agent_pool
        self._executor = agent_executor
        self._event_bus = event_bus
        self._artifact_store = artifact_store

    async def execute_phase(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        phase_context: dict[str, Any] | None = None,
        context: "ExecutionContext | None" = None,
    ) -> PhaseExecutionResult:
        """Execute all agents assigned to a phase.

        After primary agent execution, evaluates quality gates and
        optionally invokes a critic agent. Supports bounded re-execution
        on critic rejection.

        Args:
            phase: Phase configuration.
            work_item: Work item being processed.
            phase_context: Additional context for agents.
            context: Execution context for tracing.

        Returns:
            PhaseExecutionResult with per-agent results and confidence.
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

        if phase.timeout_seconds > 0:
            try:
                return await asyncio.wait_for(
                    self._execute_phase_inner(phase, work_item, phase_context, context),
                    timeout=phase.timeout_seconds,
                )
            except asyncio.TimeoutError:
                error_msg = f"Phase timed out after {phase.timeout_seconds}s"
                logger.warning(
                    "Phase '%s' timed out for work '%s' after %ss",
                    phase.id, work_item.id, phase.timeout_seconds,
                )
                result = PhaseExecutionResult(
                    phase_id=phase.id,
                    work_id=work_item.id,
                    success=False,
                    error=error_msg,
                )
                await self._emit_phase_exit(phase, work_item, result)
                return result

        return await self._execute_phase_inner(phase, work_item, phase_context, context)

    async def _execute_phase_inner(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        phase_context: dict[str, Any] | None = None,
        context: "ExecutionContext | None" = None,
    ) -> PhaseExecutionResult:
        """Inner phase execution logic with retry support."""
        current_context = dict(phase_context or {})
        retry_count = 0
        max_retries = max(phase.max_phase_retries, 1)

        for attempt in range(max_retries):
            if attempt > 0:
                retry_count = attempt
                logger.info(
                    "Re-executing phase '%s' attempt %d/%d for work '%s'",
                    phase.id, attempt + 1, max_retries, work_item.id,
                )
                await asyncio.sleep(phase.retry_backoff_seconds * attempt)

            # Execute primary agents
            if phase.parallel:
                agent_results = await self._execute_parallel(
                    phase, work_item, current_context, context=context,
                )
            else:
                agent_results = await self._execute_sequential(
                    phase, work_item, current_context, context=context,
                )

            # Capture artifacts for agent inputs/outputs
            self._store_agent_artifacts(agent_results, phase, work_item)

            success = all(r.success for r in agent_results)
            errors = [r.error for r in agent_results if r.error]

            # Compute aggregate confidence from agent outputs
            confidence_scores = [
                extract_confidence(r.output) for r in agent_results if r.success and r.output
            ]
            agg_confidence = aggregate_confidence(confidence_scores)

            if not success:
                result = PhaseExecutionResult(
                    phase_id=phase.id,
                    work_id=work_item.id,
                    success=False,
                    agent_results=agent_results,
                    error="; ".join(errors) if errors else None,
                    aggregate_confidence=agg_confidence,
                    retry_count=retry_count,
                )
                for ar in agent_results:
                    if ar.success and ar.output:
                        work_item.results[ar.agent_id] = ar.output
                await self._emit_phase_exit(phase, work_item, result)
                return result

            # Evaluate quality gates
            gate_failures = self._evaluate_gates(phase, agent_results, agg_confidence)
            blocking_failures = [f for f in gate_failures if f.startswith("[block]")]
            if blocking_failures:
                result = PhaseExecutionResult(
                    phase_id=phase.id,
                    work_id=work_item.id,
                    success=False,
                    agent_results=agent_results,
                    error="Quality gate failures: " + "; ".join(blocking_failures),
                    aggregate_confidence=agg_confidence,
                    quality_gate_failures=[f.replace("[block] ", "") for f in blocking_failures],
                    retry_count=retry_count,
                )
                await self._emit_phase_exit(phase, work_item, result)
                return result

            # Invoke critic agent if configured
            if phase.critic_agent:
                critic_result = await self._invoke_critic(
                    phase, work_item, agent_results, current_context, context,
                )
                if critic_result is not None:
                    critic_decision = critic_result.output.get("decision", "accept")
                    critic_feedback = critic_result.output.get("feedback", "")

                    self._store_critic_artifact(critic_result, phase, work_item)

                    if critic_decision == "reject" and attempt < max_retries - 1:
                        logger.info(
                            "Critic rejected phase '%s' output (attempt %d): %s",
                            phase.id, attempt + 1, critic_feedback,
                        )
                        current_context["critic_feedback"] = critic_feedback
                        current_context["critic_attempt"] = attempt + 1
                        continue  # retry

                    if critic_decision == "reject":
                        result = PhaseExecutionResult(
                            phase_id=phase.id,
                            work_id=work_item.id,
                            success=False,
                            agent_results=agent_results,
                            error=f"Critic rejected after {max_retries} attempts: {critic_feedback}",
                            aggregate_confidence=agg_confidence,
                            critic_decision="reject",
                            retry_count=retry_count,
                        )
                        await self._emit_phase_exit(phase, work_item, result)
                        return result

            # Success — merge outputs and return
            for ar in agent_results:
                if ar.success and ar.output:
                    work_item.results[ar.agent_id] = ar.output

            result = PhaseExecutionResult(
                phase_id=phase.id,
                work_id=work_item.id,
                success=True,
                agent_results=agent_results,
                aggregate_confidence=agg_confidence,
                critic_decision="accept" if phase.critic_agent else "",
                quality_gate_failures=[f for f in gate_failures if f.startswith("[warn]")],
                retry_count=retry_count,
            )
            await self._emit_phase_exit(phase, work_item, result)
            return result

        # Should not reach here, but safety fallback
        return PhaseExecutionResult(
            phase_id=phase.id,
            work_id=work_item.id,
            success=False,
            error="Max retries exhausted",
            retry_count=retry_count,
        )

    async def _execute_parallel(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        phase_context: dict[str, Any],
        context: "ExecutionContext | None" = None,
    ) -> list[ExecutionResult]:
        """Execute agents concurrently."""
        tasks = [
            self._execute_single_agent(agent_id, phase, work_item, phase_context, context=context)
            for agent_id in phase.agents
        ]
        return await asyncio.gather(*tasks)

    async def _execute_sequential(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        phase_context: dict[str, Any],
        context: "ExecutionContext | None" = None,
    ) -> list[ExecutionResult]:
        """Execute agents one at a time."""
        results: list[ExecutionResult] = []
        for agent_id in phase.agents:
            result = await self._execute_single_agent(
                agent_id, phase, work_item, phase_context, context=context,
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
        context: "ExecutionContext | None" = None,
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

    def _evaluate_gates(
        self,
        phase: WorkflowPhaseConfig,
        agent_results: list[ExecutionResult],
        agg_confidence: float,
    ) -> list[str]:
        """Evaluate quality gates and return failure descriptions.

        Returns strings prefixed with [block] or [warn] to indicate severity.
        """
        if not phase.quality_gates:
            return []

        try:
            from agent_orchestrator.core.quality_gate import (
                build_gate_context,
                evaluate_phase_quality_gates,
            )
        except ImportError:
            logger.debug("quality_gate module not available — skipping gate evaluation")
            return []

        gate_ctx = build_gate_context(agent_results, agg_confidence)
        gate_results = evaluate_phase_quality_gates(phase.quality_gates, gate_ctx)
        failures: list[str] = []
        for gr in gate_results:
            if not gr.passed:
                prefix = f"[{gr.on_failure}]"
                for f in gr.failures:
                    failures.append(f"{prefix} {gr.gate_name}: {f}")
        return failures

    async def _invoke_critic(
        self,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
        agent_results: list[ExecutionResult],
        phase_context: dict[str, Any],
        context: "ExecutionContext | None" = None,
    ) -> ExecutionResult | None:
        """Invoke the critic agent to evaluate phase output.

        Returns the critic's ExecutionResult, or None if critic cannot run.
        """
        if not phase.critic_agent:
            return None

        # Build critic context with agent outputs and rubric
        critic_context = dict(phase_context)
        critic_context["agent_outputs"] = {
            r.agent_id: r.output for r in agent_results if r.success and r.output
        }
        if phase.critic_rubric:
            critic_context["evaluation_rubric"] = phase.critic_rubric

        logger.info(
            "Invoking critic agent '%s' for phase '%s' work '%s'",
            phase.critic_agent, phase.id, work_item.id,
        )

        critic_result = await self._execute_single_agent(
            phase.critic_agent, phase, work_item, critic_context, context=context,
        )

        if not critic_result.success:
            logger.warning(
                "Critic agent '%s' failed: %s — treating as accept",
                phase.critic_agent, critic_result.error,
            )
            return None

        return critic_result

    def _store_agent_artifacts(
        self,
        agent_results: list[ExecutionResult],
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
    ) -> None:
        """Store agent outputs as artifacts if artifact store is available."""
        if self._artifact_store is None:
            return
        try:
            from agent_orchestrator.persistence.artifact_store import create_artifact
            for ar in agent_results:
                if ar.success and ar.output:
                    artifact = create_artifact(
                        work_id=work_item.id,
                        phase_id=phase.id,
                        agent_id=ar.agent_id,
                        artifact_type="output",
                        content=ar.output,
                        run_id=getattr(work_item, "run_id", ""),
                        app_id=getattr(work_item, "app_id", ""),
                    )
                    self._artifact_store.store(artifact)
        except Exception:
            logger.debug("Failed to store agent artifacts", exc_info=True)

    def _store_critic_artifact(
        self,
        critic_result: ExecutionResult,
        phase: WorkflowPhaseConfig,
        work_item: WorkItem,
    ) -> None:
        """Store critic feedback as an artifact."""
        if self._artifact_store is None or not critic_result.output:
            return
        try:
            from agent_orchestrator.persistence.artifact_store import create_artifact
            artifact = create_artifact(
                work_id=work_item.id,
                phase_id=phase.id,
                agent_id=critic_result.agent_id,
                artifact_type="critic_feedback",
                content=critic_result.output,
                run_id=getattr(work_item, "run_id", ""),
                app_id=getattr(work_item, "app_id", ""),
            )
            self._artifact_store.store(artifact)
        except Exception:
            logger.debug("Failed to store critic artifact", exc_info=True)

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
