"""Workflow branching logic for conditional phase transitions.

Evaluates branch conditions against execution context and resolves
which phase should execute next based on success/failure/confidence.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def evaluate_branch_condition(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a branch condition expression against execution context.

    Supports: >=, <=, ==, !=, >, <, in, not in, and, or.
    Context values are substituted before evaluation.

    Args:
        condition: Expression string with context keys as placeholders.
        context: Key-value pairs to substitute into the expression.

    Returns:
        True if the condition evaluates to truthy, False otherwise.
    """
    try:
        expr = condition
        for key, value in context.items():
            if isinstance(value, str):
                expr = expr.replace(key, f"'{value}'")
            else:
                expr = expr.replace(key, str(value))

        # Safe evaluation — only allow comparisons and boolean logic
        allowed = re.compile(r'^[\d\s\.\'\"\[\],>=<!andorint\(\)]+$')
        if not allowed.match(expr):
            logger.warning("Unsafe branch condition blocked: %s", condition)
            return False

        return bool(eval(expr))  # noqa: S307 — validated above
    except Exception as exc:
        logger.warning("Failed to evaluate branch condition '%s': %s", condition, exc)
        return False


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
