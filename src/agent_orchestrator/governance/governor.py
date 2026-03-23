"""Governor — Evaluates governance policies at phase transitions.

NON-BLOCKING: Always returns immediately with a decision.
Items may be queued for review, but processing continues.

Thread-safe: All public methods use internal lock for policy management.
"""

from __future__ import annotations

import ast
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from agent_orchestrator.configuration.models import (
    DelegatedAuthorityConfig,
    GovernanceConfig,
    PolicyConfig,
)
from agent_orchestrator.exceptions import GovernanceError

logger = logging.getLogger(__name__)


class Resolution(str, Enum):
    """Governance decision outcome — matches decision_os pattern."""

    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    QUEUE_FOR_REVIEW = "queue_for_review"
    ABORT = "abort"


@dataclass(frozen=True)
class GovernanceDecision:
    """Immutable result of a governance policy evaluation."""

    resolution: Resolution
    confidence: float
    policy_id: str | None = None
    policy_name: str | None = None
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Governor:
    """Non-blocking governance policy evaluator.

    Evaluates policies at phase transitions and returns immediate decisions.
    NEVER blocks for human input — items are queued for later review.

    Thread-safe: Policy management uses internal lock.

    Usage:
        governor = Governor(governance_config)
        decision = governor.evaluate({"confidence": 0.75, "work_type": "review"})
    """

    def __init__(self, config: GovernanceConfig | None = None) -> None:
        self._policies: list[PolicyConfig] = []
        self._authority = DelegatedAuthorityConfig()
        self._lock = threading.Lock()

        if config is not None:
            self.load_config(config)

    def load_config(self, config: GovernanceConfig) -> None:
        """Load governance configuration.

        Args:
            config: Governance configuration with policies and thresholds.
        """
        with self._lock:
            self._authority = config.delegated_authority
            self._policies = sorted(
                [p for p in config.policies if p.enabled],
                key=lambda p: p.priority,
                reverse=True,
            )
            logger.info("Loaded %d governance policies", len(self._policies))

    def evaluate(
        self,
        context: dict[str, Any],
        work_type: str | None = None,
    ) -> GovernanceDecision:
        """Evaluate governance policies against context. NEVER BLOCKS.

        Args:
            context: Evaluation context (confidence, work_type, etc.).
            work_type: Optional work type for threshold overrides.

        Returns:
            GovernanceDecision with resolution.
        """
        with self._lock:
            policies = list(self._policies)
            authority = self._authority

        confidence = float(context.get("confidence", 0.5))
        warnings: list[str] = []

        # Check policies in priority order
        for policy in policies:
            if self._matches_policy(policy, context):
                resolution = self._resolve_action(policy.action)
                logger.debug(
                    "Policy '%s' matched: action=%s", policy.id, policy.action,
                )
                return GovernanceDecision(
                    resolution=resolution,
                    confidence=confidence,
                    policy_id=policy.id,
                    policy_name=policy.name,
                    reason=f"Matched policy: {policy.name}",
                )

        # Fall through to delegated authority thresholds
        thresholds = self._get_thresholds(authority, work_type)
        auto_approve = thresholds.get("auto_approve_threshold", 0.8)
        review = thresholds.get("review_threshold", 0.5)
        abort = thresholds.get("abort_threshold", 0.2)

        if confidence >= auto_approve:
            return GovernanceDecision(
                resolution=Resolution.ALLOW,
                confidence=confidence,
                reason=f"Confidence {confidence:.2f} >= auto_approve {auto_approve}",
            )
        elif confidence >= review:
            return GovernanceDecision(
                resolution=Resolution.ALLOW_WITH_WARNING,
                confidence=confidence,
                reason=f"Confidence {confidence:.2f} between review and auto_approve",
                warnings=[f"Confidence below auto_approve threshold ({auto_approve})"],
            )
        elif confidence >= abort:
            return GovernanceDecision(
                resolution=Resolution.QUEUE_FOR_REVIEW,
                confidence=confidence,
                reason=f"Confidence {confidence:.2f} below review threshold ({review})",
            )
        else:
            return GovernanceDecision(
                resolution=Resolution.ABORT,
                confidence=confidence,
                reason=f"Confidence {confidence:.2f} below abort threshold ({abort})",
            )

    def _matches_policy(self, policy: PolicyConfig, context: dict[str, Any]) -> bool:
        """Check if all policy conditions match the context."""
        if not policy.conditions:
            return False  # Empty conditions = catch-all audit, don't match

        for condition_str in policy.conditions:
            if not _evaluate_condition(condition_str, context):
                return False
        return True

    def _resolve_action(self, action: str) -> Resolution:
        """Map policy action string to Resolution."""
        mapping = {
            "allow": Resolution.ALLOW,
            "deny": Resolution.ABORT,
            "review": Resolution.QUEUE_FOR_REVIEW,
            "warn": Resolution.ALLOW_WITH_WARNING,
            "escalate": Resolution.QUEUE_FOR_REVIEW,
        }
        return mapping.get(action, Resolution.QUEUE_FOR_REVIEW)

    def _get_thresholds(
        self,
        authority: DelegatedAuthorityConfig,
        work_type: str | None,
    ) -> dict[str, float]:
        """Get thresholds, applying work_type overrides if present."""
        base = {
            "auto_approve_threshold": authority.auto_approve_threshold,
            "review_threshold": authority.review_threshold,
            "abort_threshold": authority.abort_threshold,
        }
        if work_type and work_type in authority.work_type_overrides:
            base.update(authority.work_type_overrides[work_type])
        return base

    def add_policy(self, policy: PolicyConfig) -> None:
        """Add a policy at runtime."""
        with self._lock:
            self._policies.append(policy)
            self._policies.sort(key=lambda p: p.priority, reverse=True)

    def remove_policy(self, policy_id: str) -> bool:
        """Remove a policy by ID."""
        with self._lock:
            original_len = len(self._policies)
            self._policies = [p for p in self._policies if p.id != policy_id]
            return len(self._policies) < original_len

    def list_policies(self) -> list[PolicyConfig]:
        """Get all active policies."""
        with self._lock:
            return list(self._policies)


def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """Safely evaluate a condition string against context.

    Supports: ==, !=, >=, <=, >, <, in operators.
    Only allows access to context keys (no arbitrary code execution).

    Args:
        condition: Condition expression (e.g., "confidence >= 0.8").
        context: Variable bindings.

    Returns:
        True if condition is satisfied.
    """
    condition = condition.strip()

    # Handle 'in' operator
    if " in " in condition:
        parts = condition.split(" in ", 1)
        if len(parts) == 2:
            key = parts[0].strip()
            value = context.get(key)
            try:
                target = ast.literal_eval(parts[1].strip())
                return value in target
            except (ValueError, SyntaxError):
                return False

    # Handle comparison operators
    for op in (">=", "<=", "!=", "==", ">", "<"):
        if op in condition:
            parts = condition.split(op, 1)
            if len(parts) == 2:
                key = parts[0].strip()
                raw_value = parts[1].strip()
                ctx_value = context.get(key)
                if ctx_value is None:
                    return False
                try:
                    target = ast.literal_eval(raw_value)
                    if op == ">=":
                        return ctx_value >= target
                    elif op == "<=":
                        return ctx_value <= target
                    elif op == "!=":
                        return ctx_value != target
                    elif op == "==":
                        return ctx_value == target
                    elif op == ">":
                        return ctx_value > target
                    elif op == "<":
                        return ctx_value < target
                except (ValueError, SyntaxError):
                    return False
    return False
