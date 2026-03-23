"""Tests for profile validation."""

import pytest

from studio.ir.models import (
    AgentSpec,
    DelegatedAuthoritySpec,
    GovernanceSpec,
    LLMSpec,
    PhaseSpec,
    PolicySpec,
    StatusSpec,
    TeamSpec,
    WorkflowSpec,
)
from studio.validation.validator import validate_team


class TestValidateTeam:
    def test_valid_team(self, content_moderation_team: TeamSpec) -> None:
        result = validate_team(content_moderation_team)
        assert result.is_valid

    def test_empty_name(self) -> None:
        team = TeamSpec(name="")
        result = validate_team(team)
        assert not result.is_valid
        assert any("name" in e.message.lower() for e in result.errors)

    def test_duplicate_agent_ids(self) -> None:
        team = TeamSpec(
            name="test",
            agents=[
                AgentSpec(id="dup", name="A", system_prompt="p", llm=LLMSpec(provider="openai", model="gpt-4o")),
                AgentSpec(id="dup", name="B", system_prompt="p", llm=LLMSpec(provider="openai", model="gpt-4o")),
            ],
        )
        result = validate_team(team)
        assert any("Duplicate agent ID" in e.message for e in result.errors)

    def test_agent_references_unknown_phase(self) -> None:
        team = TeamSpec(
            name="test",
            agents=[
                AgentSpec(id="a1", name="A", system_prompt="p", phases=["nonexistent"],
                          llm=LLMSpec(provider="openai", model="gpt-4o")),
            ],
            workflow=WorkflowSpec(
                name="test",
                phases=[PhaseSpec(id="real", name="Real", order=1, is_terminal=True)],
            ),
        )
        result = validate_team(team)
        assert any("unknown phase" in e.message for e in result.errors)

    def test_phase_references_unknown_agent(self) -> None:
        team = TeamSpec(
            name="test",
            agents=[
                AgentSpec(id="a1", name="A", system_prompt="p", phases=["p1"],
                          llm=LLMSpec(provider="openai", model="gpt-4o")),
            ],
            workflow=WorkflowSpec(
                name="test",
                phases=[
                    PhaseSpec(id="p1", name="P1", order=1, agents=["a1", "nonexistent"],
                              on_success="done"),
                    PhaseSpec(id="done", name="Done", order=2, is_terminal=True),
                ],
            ),
        )
        result = validate_team(team)
        assert any("unknown agent" in e.message for e in result.errors)

    def test_no_terminal_phase(self) -> None:
        team = TeamSpec(
            name="test",
            workflow=WorkflowSpec(
                name="test",
                phases=[PhaseSpec(id="p1", name="P1", order=1)],
            ),
        )
        result = validate_team(team)
        assert any("terminal" in e.message.lower() for e in result.errors)

    def test_governance_threshold_order(self) -> None:
        team = TeamSpec(
            name="test",
            governance=GovernanceSpec(
                delegated_authority=DelegatedAuthoritySpec(
                    auto_approve_threshold=0.3,
                    review_threshold=0.5,
                    abort_threshold=0.7,
                ),
            ),
        )
        result = validate_team(team)
        assert any("threshold" in e.message.lower() for e in result.errors)

    def test_invalid_policy_action(self) -> None:
        team = TeamSpec(
            name="test",
            governance=GovernanceSpec(
                policies=[PolicySpec(id="p1", name="Bad", action="invalid_action")],
            ),
        )
        result = validate_team(team)
        assert any("Invalid policy action" in e.message for e in result.errors)

    def test_invalid_transition_reference(self) -> None:
        team = TeamSpec(
            name="test",
            workflow=WorkflowSpec(
                name="test",
                phases=[
                    PhaseSpec(id="p1", name="P1", order=1, on_success="nonexistent"),
                    PhaseSpec(id="done", name="Done", order=2, is_terminal=True),
                ],
            ),
        )
        result = validate_team(team)
        assert any("unknown phase" in e.message for e in result.errors)

    def test_status_transitions_unknown(self) -> None:
        team = TeamSpec(
            name="test",
            workflow=WorkflowSpec(
                name="test",
                statuses=[
                    StatusSpec(id="s1", name="S1", is_initial=True, transitions_to=["nonexistent"]),
                ],
                phases=[PhaseSpec(id="done", name="Done", order=1, is_terminal=True)],
            ),
        )
        result = validate_team(team)
        assert any("unknown status" in e.message for e in result.errors)
