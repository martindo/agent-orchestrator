"""Tests for agent_orchestrator.core.quality_gate."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_orchestrator.configuration.models import ConditionConfig, QualityGateConfig
from agent_orchestrator.core.agent_executor import ExecutionResult
from agent_orchestrator.core.quality_gate import (
    QualityGateResult,
    build_gate_context,
    evaluate_phase_quality_gates,
    evaluate_quality_gate,
)


def _make_gate(
    name: str = "test-gate",
    conditions: list[str] | None = None,
    on_failure: str = "block",
) -> QualityGateConfig:
    """Helper to create a QualityGateConfig with simple condition strings."""
    cond_objs = [ConditionConfig(expression=c) for c in (conditions or [])]
    return QualityGateConfig(name=name, conditions=cond_objs, on_failure=on_failure)


def _make_result(
    agent_id: str = "agent-1",
    success: bool = True,
    output: dict | None = None,
) -> ExecutionResult:
    """Helper to create an ExecutionResult."""
    return ExecutionResult(
        agent_id=agent_id,
        instance_id=f"{agent_id}-inst",
        work_id="work-1",
        phase_id="phase-1",
        success=success,
        output=output or {},
        timestamp=datetime.now(timezone.utc),
    )


# ---- evaluate_quality_gate ----


class TestEvaluateQualityGate:
    def test_all_conditions_pass(self) -> None:
        gate = _make_gate(conditions=["confidence >= 0.8", "agent_count > 0"])
        ctx = {"confidence": 0.9, "agent_count": 2}
        result = evaluate_quality_gate(gate, ctx)
        assert result.passed is True
        assert result.failures == []
        assert result.gate_name == "test-gate"

    def test_one_condition_fails(self) -> None:
        gate = _make_gate(conditions=["confidence >= 0.8", "agent_count > 5"])
        ctx = {"confidence": 0.9, "agent_count": 2}
        result = evaluate_quality_gate(gate, ctx)
        assert result.passed is False
        assert "agent_count > 5" in result.failures

    def test_all_conditions_fail(self) -> None:
        gate = _make_gate(conditions=["confidence >= 0.9", "agent_count > 10"])
        ctx = {"confidence": 0.5, "agent_count": 1}
        result = evaluate_quality_gate(gate, ctx)
        assert result.passed is False
        assert len(result.failures) == 2

    def test_no_conditions_passes(self) -> None:
        gate = _make_gate(conditions=[])
        result = evaluate_quality_gate(gate, {"confidence": 0.1})
        assert result.passed is True
        assert result.failures == []

    def test_on_failure_propagated(self) -> None:
        gate = _make_gate(conditions=["confidence >= 0.99"], on_failure="warn")
        result = evaluate_quality_gate(gate, {"confidence": 0.5})
        assert result.on_failure == "warn"


# ---- evaluate_phase_quality_gates ----


class TestEvaluatePhaseQualityGates:
    def test_empty_gates(self) -> None:
        results = evaluate_phase_quality_gates([], {})
        assert results == []

    def test_multiple_gates_mixed(self) -> None:
        gate_pass = _make_gate(name="pass-gate", conditions=["confidence >= 0.5"])
        gate_fail = _make_gate(name="fail-gate", conditions=["confidence >= 0.99"])
        ctx = {"confidence": 0.8}
        results = evaluate_phase_quality_gates([gate_pass, gate_fail], ctx)
        assert len(results) == 2
        assert results[0].passed is True
        assert results[0].gate_name == "pass-gate"
        assert results[1].passed is False
        assert results[1].gate_name == "fail-gate"

    def test_all_pass(self) -> None:
        gates = [
            _make_gate(name="g1", conditions=["confidence >= 0.5"]),
            _make_gate(name="g2", conditions=["agent_count > 0"]),
        ]
        ctx = {"confidence": 0.9, "agent_count": 3}
        results = evaluate_phase_quality_gates(gates, ctx)
        assert all(r.passed for r in results)


# ---- build_gate_context ----


class TestBuildGateContext:
    def test_single_agent_no_prefix(self) -> None:
        result = _make_result(agent_id="analyzer", output={"risk": "low", "label": "safe"})
        ctx = build_gate_context([result], 0.85)
        assert ctx["confidence"] == 0.85
        assert ctx["agent_count"] == 1
        assert ctx["all_succeeded"] is True
        assert ctx["failure_count"] == 0
        # Single agent: keys merged without prefix
        assert ctx["risk"] == "low"
        assert ctx["label"] == "safe"

    def test_multiple_agents_prefixed(self) -> None:
        r1 = _make_result(agent_id="a1", output={"score": 0.9})
        r2 = _make_result(agent_id="a2", output={"score": 0.7})
        ctx = build_gate_context([r1, r2], 0.8)
        assert ctx["agent_count"] == 2
        assert ctx["a1_score"] == 0.9
        assert ctx["a2_score"] == 0.7
        # Raw "score" should NOT be in context (prefixed instead)
        assert "score" not in ctx

    def test_failed_agent_excluded_from_output(self) -> None:
        r_ok = _make_result(agent_id="good", output={"val": 42})
        r_fail = _make_result(agent_id="bad", success=False, output={"val": -1})
        ctx = build_gate_context([r_ok, r_fail], 0.5)
        assert ctx["failure_count"] == 1
        assert ctx["all_succeeded"] is False
        # Only the successful agent's output is merged (single successful = no prefix)
        assert ctx["val"] == 42

    def test_no_results(self) -> None:
        ctx = build_gate_context([], 0.5)
        assert ctx["agent_count"] == 0
        assert ctx["all_succeeded"] is True
        assert ctx["failure_count"] == 0
        assert ctx["confidence"] == 0.5

    def test_empty_output_not_counted(self) -> None:
        """Agent with success=True but empty output is not counted as having output."""
        r1 = _make_result(agent_id="a1", output={})
        r2 = _make_result(agent_id="a2", output={"key": "val"})
        ctx = build_gate_context([r1, r2], 0.7)
        # Only r2 has output, so single-agent path (no prefix)
        assert ctx["key"] == "val"
