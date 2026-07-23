"""Tests for workflow branch-condition evaluation (audit 4.2).

The old evaluator substituted context values into a string and ran eval()
behind a permissive regex. These tests cover the safe replacement and lock in
that arbitrary code can no longer execute.
"""

from __future__ import annotations

import pytest

from agent_orchestrator.core.workflow_branching import (
    evaluate_branch_condition,
    resolve_next_phase,
)


# ---- Atomic comparisons -----------------------------------------------------


@pytest.mark.parametrize(
    "condition,context,expected",
    [
        ("confidence >= 0.8", {"confidence": 0.9}, True),
        ("confidence >= 0.8", {"confidence": 0.7}, False),
        ("confidence < 0.5", {"confidence": 0.3}, True),
        ("status == 'done'", {"status": "done"}, True),
        ("status == 'done'", {"status": "pending"}, False),
        ("status != 'done'", {"status": "pending"}, True),
        ("count > 3", {"count": 5}, True),
        ("count <= 3", {"count": 3}, True),
    ],
)
def test_atomic_comparisons(condition, context, expected):
    assert evaluate_branch_condition(condition, context) is expected


def test_missing_key_is_false():
    assert evaluate_branch_condition("confidence >= 0.8", {}) is False


# ---- Membership -------------------------------------------------------------


def test_in_operator():
    assert evaluate_branch_condition("status in ['a', 'b']", {"status": "a"}) is True
    assert evaluate_branch_condition("status in ['a', 'b']", {"status": "c"}) is False


def test_not_in_operator():
    assert evaluate_branch_condition("status not in ['a', 'b']", {"status": "c"}) is True
    assert evaluate_branch_condition("status not in ['a', 'b']", {"status": "a"}) is False


# ---- Boolean combination ----------------------------------------------------


def test_and():
    ctx = {"confidence": 0.9, "status": "done"}
    assert evaluate_branch_condition("confidence >= 0.8 and status == 'done'", ctx) is True
    assert evaluate_branch_condition("confidence >= 0.95 and status == 'done'", ctx) is False


def test_or():
    ctx = {"confidence": 0.4, "status": "done"}
    assert evaluate_branch_condition("confidence >= 0.8 or status == 'done'", ctx) is True
    assert evaluate_branch_condition("confidence >= 0.8 or status == 'failed'", ctx) is False


# ---- Security: no arbitrary code execution ----------------------------------


@pytest.mark.parametrize(
    "malicious",
    [
        "__import__('os').system('echo pwned')",
        "__import__('os').getcwd() == '/'",
        "().__class__.__bases__[0].__subclasses__()",
        "open('/etc/passwd').read() == 'x'",
        "True or True",          # bare eval truthiness must NOT apply
        "1 == 1",                # no key on the left → fail-closed, not True
        "exec('x=1')",
    ],
)
def test_malicious_conditions_are_inert(malicious):
    # None of these may execute code or evaluate truthy; they fail closed.
    assert evaluate_branch_condition(malicious, {"x": 1}) is False


def test_context_value_cannot_inject():
    # A hostile context value must never be interpolated into evaluated code.
    ctx = {"status": "'; __import__('os').system('x'); '"}
    assert evaluate_branch_condition("status == 'done'", ctx) is False


# ---- resolve_next_phase -----------------------------------------------------


def test_resolve_matches_branch():
    phase = {
        "branches": [
            {"condition": "confidence >= 0.8", "target": "high"},
            {"condition": "confidence < 0.8", "target": "low"},
        ],
    }
    assert resolve_next_phase(phase, {"confidence": 0.9}) == "high"
    assert resolve_next_phase(phase, {"confidence": 0.5}) == "low"


def test_resolve_falls_back_to_on_success():
    phase = {"on_success": "next", "on_failure": "retry", "confidence_threshold": 0.5}
    assert resolve_next_phase(phase, {"success": True, "confidence": 0.9}) == "next"
    assert resolve_next_phase(phase, {"success": False, "confidence": 0.9}) == "retry"
    # succeeded but below the confidence threshold → failure path
    assert resolve_next_phase(phase, {"success": True, "confidence": 0.3}) == "retry"
