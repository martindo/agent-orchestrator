"""Connector permission evaluation — generic policy hook for connector calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from .models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorPermissionPolicy,
)

logger = logging.getLogger(__name__)


class PermissionOutcome(str, Enum):
    """Outcome of a permission evaluation."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRES_APPROVAL = "requires_approval"


@dataclass(frozen=True)
class PermissionEvaluationResult:
    """Detailed result of a permission evaluation."""
    outcome: PermissionOutcome
    matched_policy_id: str | None = None
    reason: str = ""


class ConnectorPermissionError(Exception):
    """Raised when a connector invocation is denied by policy."""


def evaluate_permission(
    request: ConnectorInvocationRequest,
    policies: list[ConnectorPermissionPolicy],
) -> bool:
    """Evaluate whether a connector invocation is permitted by the given policies.

    Policies are evaluated in order; the first applicable policy wins.
    If no policy applies, the invocation is permitted by default.

    Args:
        request: The connector invocation request to evaluate.
        policies: Ordered list of permission policies to check.

    Returns:
        True if the invocation is permitted, False if denied.
    """
    context = request.context
    module_name: str | None = context.get("module_name")
    agent_role: str | None = context.get("agent_role")

    for policy in policies:
        if not policy.enabled:
            continue
        if not _policy_applies(policy, module_name, agent_role):
            continue

        if _is_denied_by_capability(policy, request.capability_type):
            logger.warning(
                "Connector invocation denied by policy %s: capability=%s",
                policy.policy_id,
                request.capability_type.value,
            )
            return False

        if _is_denied_by_operation(policy, request.operation):
            logger.warning(
                "Connector invocation denied by policy %s: operation=%s",
                policy.policy_id,
                request.operation,
            )
            return False

        if not _is_allowed_by_capability(policy, request.capability_type):
            return False

        if not _is_allowed_by_operation(policy, request.operation):
            return False

        return True

    return True


def _policy_applies(
    policy: ConnectorPermissionPolicy,
    module_name: str | None,
    agent_role: str | None,
) -> bool:
    """Check whether a policy applies to the given module and agent role."""
    if policy.allowed_modules and module_name not in policy.allowed_modules:
        return False
    if policy.allowed_agent_roles and agent_role not in policy.allowed_agent_roles:
        return False
    return True


def _is_denied_by_capability(
    policy: ConnectorPermissionPolicy,
    capability_type: CapabilityType,
) -> bool:
    """Return True if the capability type is explicitly denied by the policy."""
    return capability_type in [
        CapabilityType(c) for c in policy.denied_capability_types
    ]


def _is_denied_by_operation(
    policy: ConnectorPermissionPolicy,
    operation: str,
) -> bool:
    """Return True if the operation is explicitly denied by the policy."""
    return operation in policy.denied_operations


def _is_allowed_by_capability(
    policy: ConnectorPermissionPolicy,
    capability_type: CapabilityType,
) -> bool:
    """Return True if capability passes the allowlist (or allowlist is empty)."""
    if not policy.allowed_capability_types:
        return True
    return capability_type in [
        CapabilityType(c) for c in policy.allowed_capability_types
    ]


def _is_allowed_by_operation(
    policy: ConnectorPermissionPolicy,
    operation: str,
) -> bool:
    """Return True if operation passes the allowlist (or allowlist is empty)."""
    if not policy.allowed_operations:
        return True
    return operation in policy.allowed_operations


def evaluate_permission_detailed(
    request: ConnectorInvocationRequest,
    policies: list[ConnectorPermissionPolicy],
) -> PermissionEvaluationResult:
    """Evaluate connector invocation permission with detailed outcome.

    Like evaluate_permission() but returns a PermissionEvaluationResult
    with outcome, matched policy, and reason. Supports REQUIRES_APPROVAL
    for policies that gate write operations on human approval.

    Policies are evaluated in order; first applicable policy wins.
    Default outcome if no policy matches: ALLOW.

    Args:
        request: The connector invocation request.
        policies: Ordered list of permission policies.

    Returns:
        PermissionEvaluationResult with outcome and policy context.
    """
    context = request.context
    module_name: str | None = context.get("module_name")
    agent_role: str | None = context.get("agent_role")

    for policy in policies:
        if not policy.enabled:
            continue
        if not _policy_applies(policy, module_name, agent_role):
            continue

        if _is_denied_by_capability(policy, request.capability_type):
            logger.warning(
                "Connector invocation denied by policy %s: capability=%s",
                policy.policy_id,
                request.capability_type.value,
            )
            return PermissionEvaluationResult(
                outcome=PermissionOutcome.DENY,
                matched_policy_id=policy.policy_id,
                reason=f"capability {request.capability_type.value} denied by policy",
            )

        if _is_denied_by_operation(policy, request.operation):
            logger.warning(
                "Connector invocation denied by policy %s: operation=%s",
                policy.policy_id,
                request.operation,
            )
            return PermissionEvaluationResult(
                outcome=PermissionOutcome.DENY,
                matched_policy_id=policy.policy_id,
                reason=f"operation {request.operation} denied by policy",
            )

        if not _is_allowed_by_capability(policy, request.capability_type):
            return PermissionEvaluationResult(
                outcome=PermissionOutcome.DENY,
                matched_policy_id=policy.policy_id,
                reason=f"capability {request.capability_type.value} not in allowlist",
            )

        if not _is_allowed_by_operation(policy, request.operation):
            return PermissionEvaluationResult(
                outcome=PermissionOutcome.DENY,
                matched_policy_id=policy.policy_id,
                reason=f"operation {request.operation} not in allowlist",
            )

        # Write-operation approval gating
        if _requires_write_approval(policy, request.operation):
            logger.info(
                "Connector invocation requires approval: policy=%s op=%s",
                policy.policy_id, request.operation,
            )
            return PermissionEvaluationResult(
                outcome=PermissionOutcome.REQUIRES_APPROVAL,
                matched_policy_id=policy.policy_id,
                reason=f"write operation {request.operation} requires approval",
            )

        return PermissionEvaluationResult(
            outcome=PermissionOutcome.ALLOW,
            matched_policy_id=policy.policy_id,
            reason="permitted by policy",
        )

    return PermissionEvaluationResult(outcome=PermissionOutcome.ALLOW, reason="no policy matched")


def _requires_write_approval(
    policy: ConnectorPermissionPolicy,
    operation: str,
) -> bool:
    """Return True if this operation requires approval under the given policy."""
    if not getattr(policy, "requires_approval", False):
        return False
    if policy.read_only:
        return False
    # Only non-read-only operations require approval
    read_prefixes = ("get", "list", "read", "fetch", "query", "search")
    return not any(operation.lower().startswith(p) for p in read_prefixes)
