"""Workflow branching logic for conditional phase transitions.

Evaluates branch conditions against execution context and resolves
which phase should execute next based on success/failure/confidence.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agent_orchestrator.governance.governor import _evaluate_condition

logger = logging.getLogger(__name__)


def evaluate_branch_condition(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a branch condition expression against execution context.

    Uses the same ``ast.literal_eval``-based evaluator as governor/quality_gate
    — there is **no** ``eval()`` and no string substitution, so conditions can't
    execute arbitrary code (audit 4.2; the old implementation substituted
    context values into a string and ``eval``'d it behind a permissive regex).

    Supported grammar:
      * atomic comparison ``<key> <op> <literal>`` for op in ``== != >= <= > <``
      * membership ``<key> in <literal>`` and ``<key> not in <literal>``
      * flat boolean combination with ``and`` / ``or`` (no parentheses/nesting)

    Anything else — including keys not present in the context — evaluates to
    ``False`` (fail-closed).

    Args:
        condition: Condition expression (e.g. ``"confidence >= 0.8"``).
        context: Variable bindings (the completed phase's result).

    Returns:
        True if the condition is satisfied, else False.
    """
    if not condition or not condition.strip():
        return False
    try:
        return _eval_or(condition, context)
    except Exception as exc:
        logger.warning("Failed to evaluate branch condition '%s': %s", condition, exc)
        return False


def _eval_or(expr: str, context: dict[str, Any]) -> bool:
    return any(_eval_and(part, context) for part in expr.split(" or "))


def _eval_and(expr: str, context: dict[str, Any]) -> bool:
    return all(_eval_atom(part, context) for part in expr.split(" and "))


def _eval_atom(expr: str, context: dict[str, Any]) -> bool:
    expr = expr.strip()
    if " not in " in expr:
        key, _, rhs = expr.partition(" not in ")
        return not _evaluate_condition(f"{key.strip()} in {rhs.strip()}", context)
    return _evaluate_condition(expr, context)


def resolve_next_phase(
    phase_config: dict[str, Any],
    execution_result: dict[str, Any],
) -> Optional[str]:
    """Determine the next phase based on branching rules.

    Supports:
    - Conditional: ``branches`` array with condition expressions.
    - Simple: ``on_success`` / ``on_failure`` fallback keys.
    - Default: falls back to None when no rule matches.

    Args:
        phase_config: Phase definition containing branching rules.
        execution_result: Result data from the completed phase.

    Returns:
        The name/ID of the next phase, or None if unresolved.
    """
    # Check conditional branches first
    branches: list[dict[str, Any]] = phase_config.get("branches", [])
    for branch in branches:
        condition = branch.get("condition", "")
        if condition and evaluate_branch_condition(condition, execution_result):
            target = branch.get("target")
            logger.info("Branch condition matched: %s -> %s", condition, target)
            return target

    # Fall back to simple on_success / on_failure
    success = execution_result.get("success", True)
    confidence = execution_result.get("confidence", 0.5)

    if success and confidence >= phase_config.get("confidence_threshold", 0.0):
        return phase_config.get("on_success")
    return phase_config.get("on_failure")
