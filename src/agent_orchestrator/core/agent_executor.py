"""AgentExecutor — Invokes a single agent: builds prompt, calls LLM, validates.

Responsibilities:
- Build system prompt from agent definition
- Build user prompt from work item context + phase context
- Call LLM (placeholder — real LLM calls via adapters in Phase 5)
- Validate output
- Handle retries based on agent's retry_policy
- Record execution metrics

Thread-safe: Stateless — each execution is independent.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent_orchestrator.configuration.models import AgentDefinition, RetryPolicy
from agent_orchestrator.core.agent_pool import AgentInstance
from agent_orchestrator.core.work_queue import WorkItem
from agent_orchestrator.exceptions import AgentError

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a single agent execution."""

    agent_id: str
    instance_id: str
    work_id: str
    phase_id: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0
    attempt: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentExecutor:
    """Executes a single agent against a work item.

    The executor is stateless — it receives all context needed for execution
    via method parameters. LLM calls are handled by the llm_call_fn callback,
    which is injected by the adapters layer.

    Thread-safe: Stateless design — no shared mutable state.
    """

    def __init__(
        self,
        llm_call_fn: LLMCallFn | None = None,
    ) -> None:
        self._llm_call_fn = llm_call_fn or _default_llm_call

    async def execute(
        self,
        instance: AgentInstance,
        work_item: WorkItem,
        phase_id: str,
        phase_context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an agent against a work item with retry logic.

        Args:
            instance: The agent instance to use.
            work_item: The work item to process.
            phase_id: Current workflow phase ID.
            phase_context: Additional context for the phase.

        Returns:
            ExecutionResult with output or error details.
        """
        definition = instance.definition
        retry_policy = definition.retry_policy
        last_error: str | None = None

        for attempt in range(1, retry_policy.max_retries + 1):
            try:
                result = await self._execute_once(
                    instance, work_item, phase_id, phase_context or {}, attempt,
                )
                if result.success:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Agent '%s' attempt %d/%d failed: %s",
                    definition.id, attempt, retry_policy.max_retries, e,
                    exc_info=True,
                )

            # Wait before retry (if not last attempt)
            if attempt < retry_policy.max_retries:
                delay = _compute_retry_delay(retry_policy, attempt)
                logger.debug("Retrying agent '%s' in %.1fs", definition.id, delay)
                await asyncio.sleep(delay)

        return ExecutionResult(
            agent_id=definition.id,
            instance_id=instance.instance_id,
            work_id=work_item.id,
            phase_id=phase_id,
            success=False,
            error=f"All {retry_policy.max_retries} attempts failed. Last: {last_error}",
            attempt=retry_policy.max_retries,
        )

    async def _execute_once(
        self,
        instance: AgentInstance,
        work_item: WorkItem,
        phase_id: str,
        phase_context: dict[str, Any],
        attempt: int,
    ) -> ExecutionResult:
        """Execute a single attempt."""
        definition = instance.definition
        start_time = time.monotonic()

        system_prompt = definition.system_prompt
        user_prompt = _build_user_prompt(work_item, phase_id, phase_context)

        logger.debug(
            "Executing agent '%s' (instance=%s) on work '%s' phase='%s' attempt=%d",
            definition.id, instance.instance_id, work_item.id, phase_id, attempt,
        )

        try:
            response = await self._llm_call_fn(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                llm_config=definition.llm,
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            msg = f"LLM call failed for agent '{definition.id}': {e}"
            raise AgentError(msg) from e

        duration = time.monotonic() - start_time

        return ExecutionResult(
            agent_id=definition.id,
            instance_id=instance.instance_id,
            work_id=work_item.id,
            phase_id=phase_id,
            success=True,
            output=response,
            duration_seconds=duration,
            attempt=attempt,
        )


# ---- Type Aliases ----

from typing import Callable, Coroutine

from agent_orchestrator.configuration.models import LLMConfig

LLMCallFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


# ---- Helper Functions ----


def _build_user_prompt(
    work_item: WorkItem,
    phase_id: str,
    phase_context: dict[str, Any],
) -> str:
    """Build user prompt from work item and phase context."""
    parts = [
        f"## Work Item: {work_item.title}",
        f"Type: {work_item.type_id}",
        f"Phase: {phase_id}",
    ]
    if work_item.data:
        parts.append(f"\n## Data\n{_format_dict(work_item.data)}")
    if phase_context:
        parts.append(f"\n## Phase Context\n{_format_dict(phase_context)}")
    if work_item.results:
        parts.append(f"\n## Previous Results\n{_format_dict(work_item.results)}")
    return "\n".join(parts)


def _format_dict(d: dict[str, Any]) -> str:
    """Format a dict for inclusion in a prompt."""
    lines = []
    for key, value in d.items():
        if isinstance(value, dict):
            lines.append(f"### {key}")
            lines.append(_format_dict(value))
        else:
            lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)


def _compute_retry_delay(policy: RetryPolicy, attempt: int) -> float:
    """Compute retry delay with exponential backoff."""
    return policy.delay_seconds * (policy.backoff_multiplier ** (attempt - 1))


async def _default_llm_call(
    system_prompt: str,
    user_prompt: str,
    llm_config: Any,
) -> dict[str, Any]:
    """Default LLM call stub — returns mock response.

    This is replaced by real LLM adapters in Phase 5.
    """
    logger.debug("Default LLM call (stub) — returning mock response")
    return {
        "response": "Mock response from default LLM stub",
        "confidence": 0.85,
        "model": getattr(llm_config, "model", "mock"),
    }
