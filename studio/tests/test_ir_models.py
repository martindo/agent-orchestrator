"""Tests for Studio IR models."""

import pytest
from studio.ir.models import (
    AgentSpec,
    ConditionSpec,
    FieldType,
    LLMSpec,
    OnFailureAction,
    PhaseSpec,
    QualityGateSpec,
    StatusSpec,
    TeamSpec,
    TransitionSpec,
    WorkflowSpec,
    WorkItemFieldSpec,
)


class TestLLMSpec:
    def test_defaults(self) -> None:
        spec = LLMSpec(provider="openai", model="gpt-4o")
        assert spec.temperature == 0.3
        assert spec.max_tokens == 4000
        assert spec.endpoint is None

    def test_custom_values(self) -> None:
        spec = LLMSpec(provider="anthropic", model="claude", temperature=0.7, max_tokens=8000)
        assert spec.temperature == 0.7
        assert spec.max_tokens == 8000

    def test_immutable(self) -> None:
        spec = LLMSpec(provider="openai", model="gpt-4o")
        with pytest.raises(Exception):
            spec.provider = "changed"  # type: ignore[misc]


class TestAgentSpec:
    def test_minimal(self) -> None:
        agent = AgentSpec(id="test", name="Test Agent")
        assert agent.id == "test"
        assert agent.enabled is True
        assert agent.concurrency == 1

    def test_full(self) -> None:
        agent = AgentSpec(
            id="analyzer",
            name="Analyzer",
            description="Analyzes things",
            system_prompt="You are an analyzer",
            skills=["nlp"],
            phases=["analysis"],
            llm=LLMSpec(provider="openai", model="gpt-4o"),
            concurrency=5,
        )
        assert len(agent.skills) == 1
        assert agent.concurrency == 5


class TestWorkflowSpec:
    def test_transitions_property(self) -> None:
        wf = WorkflowSpec(
            name="test",
            phases=[
                PhaseSpec(id="a", name="A", order=1, on_success="b", on_failure="c"),
                PhaseSpec(id="b", name="B", order=2, on_success="d"),
                PhaseSpec(id="c", name="C", order=3, on_success="d"),
                PhaseSpec(id="d", name="D", order=4, is_terminal=True),
            ],
        )
        transitions = wf.transitions
        assert len(transitions) == 4
        assert TransitionSpec(from_phase="a", to_phase="b", trigger="on_success") in transitions
        assert TransitionSpec(from_phase="a", to_phase="c", trigger="on_failure") in transitions


class TestWorkItemFieldSpec:
    def test_enum_field_with_values(self) -> None:
        field = WorkItemFieldSpec(
            name="status",
            type=FieldType.ENUM,
            values=["open", "closed"],
        )
        assert field.values == ["open", "closed"]

    def test_string_field(self) -> None:
        field = WorkItemFieldSpec(name="title", type=FieldType.STRING, required=True)
        assert field.required is True


class TestTeamSpec:
    def test_minimal(self) -> None:
        team = TeamSpec(name="Test Team")
        assert team.name == "Test Team"
        assert len(team.agents) == 0

    def test_from_fixture(self, content_moderation_team: TeamSpec) -> None:
        team = content_moderation_team
        assert team.name == "Content Moderation Pipeline"
        assert len(team.agents) == 3
        assert len(team.workflow.phases) == 4
