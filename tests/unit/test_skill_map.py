"""Tests for SkillMap — organizational skill registry and coverage analysis."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_orchestrator.catalog.skill_map import SkillMap
from agent_orchestrator.catalog.skill_models import (
    SkillCoverage,
    SkillMaturity,
    SkillMetrics,
    SkillRecord,
)


@pytest.fixture()
def skill_map(tmp_path: Path) -> SkillMap:
    """Create a SkillMap with persistence."""
    return SkillMap(tmp_path / "skills")


@pytest.fixture()
def memory_skill_map() -> SkillMap:
    """Create an in-memory SkillMap (no persistence)."""
    return SkillMap()


def _make_skill(
    skill_id: str = "analysis",
    *,
    name: str = "Analysis",
    agent_ids: list[str] | None = None,
    tags: list[str] | None = None,
) -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id,
        name=name,
        agent_ids=agent_ids or [],
        tags=tags or [skill_id],
    )


class TestSkillMetrics:
    """Test SkillMetrics calculations."""

    def test_initial_state(self) -> None:
        m = SkillMetrics()
        assert m.success_rate == 0.0
        assert m.average_confidence == 0.0
        assert m.average_duration == 0.0
        assert m.maturity == SkillMaturity.NASCENT

    def test_record_execution(self) -> None:
        m = SkillMetrics()
        m.record_execution(success=True, confidence=0.9, duration_seconds=5.0)
        m.record_execution(success=False, confidence=0.3, duration_seconds=10.0)
        assert m.total_executions == 2
        assert m.successful_executions == 1
        assert m.failed_executions == 1
        assert m.success_rate == 0.5
        assert m.average_confidence == pytest.approx(0.6)
        assert m.average_duration == pytest.approx(7.5)

    def test_maturity_nascent(self) -> None:
        m = SkillMetrics(total_executions=5, successful_executions=5)
        assert m.maturity == SkillMaturity.NASCENT

    def test_maturity_developing(self) -> None:
        m = SkillMetrics(total_executions=15, successful_executions=10)
        assert m.maturity == SkillMaturity.DEVELOPING

    def test_maturity_established(self) -> None:
        m = SkillMetrics(total_executions=100, successful_executions=90)
        assert m.maturity == SkillMaturity.ESTABLISHED

    def test_maturity_expert(self) -> None:
        m = SkillMetrics(total_executions=250, successful_executions=230)
        assert m.maturity == SkillMaturity.EXPERT


class TestSkillMapCRUD:
    """Test basic CRUD operations."""

    def test_register_and_get(self, memory_skill_map: SkillMap) -> None:
        skill = _make_skill("coding")
        memory_skill_map.register_skill(skill)
        result = memory_skill_map.get_skill("coding")
        assert result is not None
        assert result.skill_id == "coding"

    def test_get_nonexistent(self, memory_skill_map: SkillMap) -> None:
        assert memory_skill_map.get_skill("missing") is None

    def test_list_all(self, memory_skill_map: SkillMap) -> None:
        memory_skill_map.register_skill(_make_skill("a"))
        memory_skill_map.register_skill(_make_skill("b"))
        assert len(memory_skill_map.list_all()) == 2

    def test_unregister(self, memory_skill_map: SkillMap) -> None:
        memory_skill_map.register_skill(_make_skill("test"))
        assert memory_skill_map.unregister_skill("test") is True
        assert memory_skill_map.get_skill("test") is None

    def test_unregister_nonexistent(self, memory_skill_map: SkillMap) -> None:
        assert memory_skill_map.unregister_skill("missing") is False


class TestSkillMapFind:
    """Test find with filters."""

    def setup_method(self) -> None:
        self.sm = SkillMap()
        self.sm.register_skill(_make_skill("analysis", agent_ids=["a1"], tags=["ml", "analysis"]))
        self.sm.register_skill(_make_skill("coding", agent_ids=["a2"], tags=["dev", "coding"]))
        self.sm.register_skill(_make_skill("review", agent_ids=["a1", "a2"], tags=["qa", "review"]))

    def test_find_by_tags(self) -> None:
        results = self.sm.find_skills(tags=["ml"])
        assert len(results) == 1
        assert results[0].skill_id == "analysis"

    def test_find_by_agent(self) -> None:
        results = self.sm.find_skills(agent_id="a1")
        assert len(results) == 2

    def test_find_no_filters(self) -> None:
        results = self.sm.find_skills()
        assert len(results) == 3


class TestRecordExecution:
    """Test execution recording and metric updates."""

    def test_record_updates_metrics(self, memory_skill_map: SkillMap) -> None:
        memory_skill_map.register_skill(_make_skill("test", agent_ids=["agent-1"]))
        memory_skill_map.record_execution(
            "test", "agent-1", success=True, confidence=0.9, duration_seconds=5.0,
        )
        skill = memory_skill_map.get_skill("test")
        assert skill is not None
        assert skill.metrics.total_executions == 1
        assert skill.metrics.success_rate == 1.0
        assert skill.agent_metrics["agent-1"].total_executions == 1

    def test_record_nonexistent_skill(self, memory_skill_map: SkillMap) -> None:
        assert memory_skill_map.record_execution(
            "missing", "agent-1", success=True, confidence=0.5, duration_seconds=1.0,
        ) is False

    def test_record_new_agent(self, memory_skill_map: SkillMap) -> None:
        memory_skill_map.register_skill(_make_skill("test"))
        memory_skill_map.record_execution(
            "test", "new-agent", success=True, confidence=0.8, duration_seconds=3.0,
        )
        skill = memory_skill_map.get_skill("test")
        assert skill is not None
        assert "new-agent" in skill.agent_ids


class TestAutoRegister:
    """Test auto-registration from profile data."""

    def test_auto_register(self, memory_skill_map: SkillMap) -> None:
        # Mock agent definitions
        class MockAgent:
            def __init__(self, agent_id: str, skills: list[str]) -> None:
                self.id = agent_id
                self.skills = skills

        class MockPhase:
            def __init__(self, phase_id: str, agents: list[str]) -> None:
                self.id = phase_id
                self.agents = agents

        agents = [
            MockAgent("researcher", ["research", "analysis"]),
            MockAgent("writer", ["writing", "analysis"]),
        ]
        phases = [
            MockPhase("research_phase", ["researcher"]),
            MockPhase("writing_phase", ["writer"]),
        ]

        count = memory_skill_map.auto_register_from_profile(agents, phases)
        assert count == 3  # research, analysis, writing

        research = memory_skill_map.get_skill("research")
        assert research is not None
        assert "researcher" in research.agent_ids
        assert "research_phase" in research.phase_ids

        analysis = memory_skill_map.get_skill("analysis")
        assert analysis is not None
        assert "researcher" in analysis.agent_ids
        assert "writer" in analysis.agent_ids


class TestCoverageAnalysis:
    """Test organizational coverage reporting."""

    def test_coverage_empty(self, memory_skill_map: SkillMap) -> None:
        coverage = memory_skill_map.get_coverage()
        assert coverage.total_skills == 0
        assert coverage.coverage_ratio == 0.0

    def test_coverage_with_data(self, memory_skill_map: SkillMap) -> None:
        # Strong skill
        strong = _make_skill("strong", agent_ids=["a1"])
        strong.metrics = SkillMetrics(
            total_executions=100, successful_executions=95,
            total_confidence=85.0, total_duration_seconds=500.0,
        )
        memory_skill_map.register_skill(strong)

        # Weak skill
        weak = _make_skill("weak", agent_ids=["a2"])
        weak.metrics = SkillMetrics(
            total_executions=20, successful_executions=8,
            total_confidence=10.0, total_duration_seconds=200.0,
        )
        memory_skill_map.register_skill(weak)

        # Unassigned skill
        memory_skill_map.register_skill(_make_skill("unassigned"))

        coverage = memory_skill_map.get_coverage()
        assert coverage.total_skills == 3
        assert coverage.covered_skills == 2
        assert "strong" in coverage.strong_skills
        assert "weak" in coverage.weak_skills
        assert "unassigned" in coverage.unassigned_skills


class TestAgentProfile:
    """Test per-agent skill profiling."""

    def test_agent_profile(self, memory_skill_map: SkillMap) -> None:
        memory_skill_map.register_skill(_make_skill("skill-a", agent_ids=["agent-1"]))
        memory_skill_map.register_skill(_make_skill("skill-b", agent_ids=["agent-1", "agent-2"]))

        for _ in range(5):
            memory_skill_map.record_execution(
                "skill-a", "agent-1", success=True, confidence=0.9, duration_seconds=2.0,
            )
        for _ in range(3):
            memory_skill_map.record_execution(
                "skill-b", "agent-1", success=True, confidence=0.7, duration_seconds=3.0,
            )

        profile = memory_skill_map.get_agent_profile("agent-1")
        assert profile["agent_id"] == "agent-1"
        assert len(profile["skills"]) == 2
        assert profile["total_executions"] == 8
        assert profile["overall_success_rate"] == 1.0


class TestPersistence:
    """Test skill map persistence."""

    def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"

        # Create and populate
        sm1 = SkillMap(skills_dir)
        sm1.register_skill(_make_skill("test", agent_ids=["a1"]))
        sm1.record_execution(
            "test", "a1", success=True, confidence=0.9, duration_seconds=5.0,
        )

        # Reload from disk
        sm2 = SkillMap(skills_dir)
        skill = sm2.get_skill("test")
        assert skill is not None
        assert skill.metrics.total_executions == 1
        assert skill.metrics.success_rate == 1.0
        assert "a1" in skill.agent_ids


class TestSummary:
    """Test summary statistics."""

    def test_summary(self, memory_skill_map: SkillMap) -> None:
        memory_skill_map.register_skill(_make_skill("a", agent_ids=["a1"]))
        memory_skill_map.register_skill(_make_skill("b"))
        summary = memory_skill_map.summary()
        assert summary["total_skills"] == 2
        assert summary["covered_skills"] == 1
        assert "b" in summary["unassigned_skills"]
