"""Tests for critic agent evaluation loop and phase re-execution."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    LLMConfig,
    QualityGateConfig,
    ConditionConfig,
    WorkflowPhaseConfig,
)
from agent_orchestrator.core.agent_executor import AgentExecutor, ExecutionResult
from agent_orchestrator.core.agent_pool import AgentPool
from agent_orchestrator.core.event_bus import EventBus
from agent_orchestrator.core.phase_executor import PhaseExecutor, PhaseExecutionResult
from agent_orchestrator.core.work_queue import WorkItem


def _make_agent_def(agent_id: str) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        name=agent_id,
        system_prompt="test",
        phases=["test-phase"],
        llm=LLMConfig(provider="openai", model="gpt-4o"),
    )


def _make_phase(
    agents: list[str],
    critic_agent: str | None = None,
    critic_rubric: str = "",
    max_retries: int = 1,
    quality_gates: list[QualityGateConfig] | None = None,
) -> WorkflowPhaseConfig:
    return WorkflowPhaseConfig(
        id="test-phase",
        name="Test Phase",
        order=1,
        agents=agents,
        critic_agent=critic_agent,
        critic_rubric=critic_rubric,
        max_phase_retries=max_retries,
        retry_backoff_seconds=0.0,
        quality_gates=quality_gates or [],
    )


def _make_work_item() -> WorkItem:
    return WorkItem(id="w1", type_id="task", title="Test Work Item")


class TestCriticAgentLoop:
    """Tests for critic agent invocation in PhaseExecutor."""

    @pytest.mark.asyncio
    async def test_critic_accepts_on_first_try(self) -> None:
        """Critic accepts agent output — phase succeeds with critic_decision='accept'."""
        call_count = 0

        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:  # Primary agent
                return {"response": "analysis", "confidence": 0.9}
            # Critic agent
            return {"decision": "accept", "feedback": "Good work"}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker"), _make_agent_def("critic")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        phase = _make_phase(agents=["worker"], critic_agent="critic")
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True
        assert result.critic_decision == "accept"
        assert result.retry_count == 0

    @pytest.mark.asyncio
    async def test_critic_rejects_then_accepts(self) -> None:
        """Critic rejects first attempt, accepts second — tests re-execution."""
        call_count = 0

        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count in (1, 3):  # Primary agent (attempt 1 and 2)
                return {"response": "analysis", "confidence": 0.8}
            if call_count == 2:  # Critic rejects first
                return {"decision": "reject", "feedback": "Needs more detail"}
            # Critic accepts second
            return {"decision": "accept", "feedback": "Better"}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker"), _make_agent_def("critic")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        phase = _make_phase(agents=["worker"], critic_agent="critic", max_retries=3)
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True
        assert result.critic_decision == "accept"
        assert result.retry_count == 1
        assert call_count == 4  # worker + critic + worker + critic

    @pytest.mark.asyncio
    async def test_critic_rejects_all_attempts(self) -> None:
        """Critic rejects all attempts — phase fails after max retries."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            user_prompt = kwargs.get("user_prompt", "")
            if "evaluation_rubric" in str(kwargs) or "agent_outputs" in str(kwargs):
                return {"decision": "reject", "feedback": "Still not good enough"}
            return {"response": "analysis", "confidence": 0.7}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker"), _make_agent_def("critic")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        phase = _make_phase(agents=["worker"], critic_agent="critic", max_retries=2)
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is False
        assert result.critic_decision == "reject"
        assert "rejected after 2 attempts" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_no_critic_skips_evaluation(self) -> None:
        """Without critic_agent configured, phase runs normally."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "done", "confidence": 0.95}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        phase = _make_phase(agents=["worker"])
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True
        assert result.critic_decision == ""
        assert result.aggregate_confidence == 0.95

    @pytest.mark.asyncio
    async def test_critic_feedback_injected_on_retry(self) -> None:
        """On retry, critic feedback is injected into phase context."""
        captured_contexts: list[str] = []

        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            user_prompt = kwargs.get("user_prompt", "")
            captured_contexts.append(user_prompt)
            if "evaluation_rubric" in user_prompt or "agent_outputs" in user_prompt:
                if len(captured_contexts) <= 3:  # First critic call
                    return {"decision": "reject", "feedback": "Add more citations"}
                return {"decision": "accept", "feedback": "Good"}
            return {"response": "analysis", "confidence": 0.8}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker"), _make_agent_def("critic")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        phase = _make_phase(
            agents=["worker"],
            critic_agent="critic",
            critic_rubric="Check for citations",
            max_retries=3,
        )
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True
        # The second worker call should have critic_feedback in context
        assert any("Add more citations" in ctx for ctx in captured_contexts)


class TestQualityGateIntegration:
    """Tests for quality gate evaluation within PhaseExecutor."""

    @pytest.mark.asyncio
    async def test_blocking_gate_fails_phase(self) -> None:
        """A quality gate with on_failure='block' that fails stops the phase."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "done", "confidence": 0.3}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        gate = QualityGateConfig(
            name="min-confidence",
            conditions=[ConditionConfig(expression="confidence >= 0.8")],
            on_failure="block",
        )
        phase = _make_phase(agents=["worker"], quality_gates=[gate])
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is False
        assert len(result.quality_gate_failures) > 0
        assert "min-confidence" in result.quality_gate_failures[0]

    @pytest.mark.asyncio
    async def test_warning_gate_allows_phase(self) -> None:
        """A quality gate with on_failure='warn' allows phase to succeed."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "done", "confidence": 0.3}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        gate = QualityGateConfig(
            name="high-confidence",
            conditions=[ConditionConfig(expression="confidence >= 0.8")],
            on_failure="warn",
        )
        phase = _make_phase(agents=["worker"], quality_gates=[gate])
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_passing_gate_no_failures(self) -> None:
        """A passing gate produces no failures."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "done", "confidence": 0.95}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        gate = QualityGateConfig(
            name="min-confidence",
            conditions=[ConditionConfig(expression="confidence >= 0.8")],
            on_failure="block",
        )
        phase = _make_phase(agents=["worker"], quality_gates=[gate])
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True
        # Only warn-level failures are kept on success
        blocking_failures = [f for f in result.quality_gate_failures if "min-confidence" in f]
        assert len(blocking_failures) == 0


class TestConfidenceAggregation:
    """Tests for confidence score aggregation in PhaseExecutionResult."""

    @pytest.mark.asyncio
    async def test_confidence_from_single_agent(self) -> None:
        """Single agent's confidence is surfaced."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "done", "confidence": 0.92}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        phase = _make_phase(agents=["worker"])
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True
        assert result.aggregate_confidence == 0.92

    @pytest.mark.asyncio
    async def test_confidence_averaged_multiple_agents(self) -> None:
        """Multiple agents' confidences are averaged."""
        call_count = 0

        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            conf = 0.8 if call_count == 1 else 0.6
            return {"response": "done", "confidence": conf}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("agent-a"), _make_agent_def("agent-b")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        phase = _make_phase(agents=["agent-a", "agent-b"])
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True
        assert abs(result.aggregate_confidence - 0.7) < 0.01

    @pytest.mark.asyncio
    async def test_default_confidence_when_no_score(self) -> None:
        """Agents without confidence key get default 0.5."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "done"}

        pool = AgentPool()
        pool.register_definitions([_make_agent_def("worker")])
        executor = AgentExecutor(llm_call_fn=mock_llm)
        bus = EventBus()
        phase_exec = PhaseExecutor(pool, executor, bus)

        phase = _make_phase(agents=["worker"])
        work_item = _make_work_item()
        result = await phase_exec.execute_phase(phase, work_item)

        assert result.success is True
        assert result.aggregate_confidence == 0.5
