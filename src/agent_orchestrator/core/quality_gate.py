"""Evaluate quality gates against phase execution results."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_orchestrator.configuration.models import QualityGateConfig
from agent_orchestrator.core.agent_executor import ExecutionResult
from agent_orchestrator.governance.governor import _evaluate_condition

logger = logging.getLogger(__name__)


@dataclass
class QualityGateResult:
    """Outcome of evaluating a single quality gate."""

    gate_name: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    on_failure: str = "block"


def evaluate_quality_gate(
    gate: QualityGateConfig,
    context: dict[str, Any],
) -> QualityGateResult:
    """Evaluate a single quality gate against a context dict.

    A gate passes when **all** of its conditions evaluate to ``True``.
    If the gate has no conditions it passes by default.

    Args:
        gate: Quality gate configuration.
        context: Variable bindings for condition evaluation.

    Returns:
        A :class:`QualityGateResult` describing whether the gate passed.
    """
    failures: list[str] = []

    for condition in gate.conditions:
        if not _evaluate_condition(condition.expression, context):
            failures.append(condition.expression)

    passed = len(failures) == 0
    if not passed:
        logger.info("Quality gate '%s' failed on conditions: %s", gate.name, failures)
    else:
        logger.debug("Quality gate '%s' passed", gate.name)

    return QualityGateResult(
        gate_name=gate.name,
        passed=passed,
        failures=failures,
        on_failure=gate.on_failure,
    )


def evaluate_phase_quality_gates(
    gates: list[QualityGateConfig],
    context: dict[str, Any],
) -> list[QualityGateResult]:
    """Evaluate all quality gates for a phase.

    Args:
        gates: List of quality gate configurations.
        context: Variable bindings for condition evaluation.

    Returns:
        List of :class:`QualityGateResult`, one per gate.
    """
    results: list[QualityGateResult] = []
    for gate in gates:
        results.append(evaluate_quality_gate(gate, context))
    return results


def build_gate_context(
    agent_results: list[ExecutionResult],
    aggregate_confidence: float,
) -> dict[str, Any]:
    """Build a context dict suitable for quality-gate evaluation.

    Args:
        agent_results: Execution results from the phase's agents.
        aggregate_confidence: Pre-computed aggregate confidence score.

    Returns:
        A dict with standard keys (``confidence``, ``agent_count``,
        ``all_succeeded``, ``failure_count``) plus merged agent outputs.
    """
    succeeded = [r for r in agent_results if r.success]
    failure_count = len(agent_results) - len(succeeded)

    context: dict[str, Any] = {
        "confidence": aggregate_confidence,
        "agent_count": len(agent_results),
        "all_succeeded": failure_count == 0,
        "failure_count": failure_count,
    }

    results_with_output = [r for r in succeeded if r.output]

    if len(results_with_output) == 1:
        # Single agent: merge output keys directly into context.
        context.update(results_with_output[0].output)
    else:
        # Multiple agents: prefix each output key with agent_id.
        for result in results_with_output:
            for key, value in result.output.items():
                context[f"{result.agent_id}_{key}"] = value

    logger.debug("Built gate context with %d keys from %d agent results", len(context), len(agent_results))
    return context
