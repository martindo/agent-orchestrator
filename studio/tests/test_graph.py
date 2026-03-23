"""Tests for workflow graph validation."""

import pytest

from studio.graph.validator import validate_graph
from studio.ir.models import PhaseSpec, WorkflowSpec


class TestValidateGraph:
    def test_valid_graph(self, content_moderation_team) -> None:
        result = validate_graph(content_moderation_team.workflow)
        assert result.is_valid
        assert len(result.nodes) == 4
        assert len(result.edges) == 6

    def test_empty_workflow(self) -> None:
        result = validate_graph(WorkflowSpec(name="empty"))
        assert result.is_valid  # No phases = no errors, just warnings
        assert len(result.warnings) > 0

    def test_no_terminal_phase(self) -> None:
        wf = WorkflowSpec(
            name="test",
            phases=[
                PhaseSpec(id="a", name="A", order=1, on_success="b"),
                PhaseSpec(id="b", name="B", order=2, on_success="a"),
            ],
        )
        result = validate_graph(wf)
        assert not result.is_valid
        assert any("terminal" in e.lower() for e in result.errors)

    def test_invalid_transition_ref(self) -> None:
        wf = WorkflowSpec(
            name="test",
            phases=[
                PhaseSpec(id="a", name="A", order=1, on_success="nonexistent"),
                PhaseSpec(id="done", name="Done", order=2, is_terminal=True),
            ],
        )
        result = validate_graph(wf)
        assert not result.is_valid
        assert any("unknown phase" in e for e in result.errors)

    def test_unreachable_terminal(self) -> None:
        wf = WorkflowSpec(
            name="test",
            phases=[
                PhaseSpec(id="a", name="A", order=1),
                PhaseSpec(id="done", name="Done", order=2, is_terminal=True),
            ],
        )
        result = validate_graph(wf)
        assert any("cannot reach" in e.lower() for e in result.errors)

    def test_linear_graph(self) -> None:
        wf = WorkflowSpec(
            name="test",
            phases=[
                PhaseSpec(id="a", name="A", order=1, on_success="b"),
                PhaseSpec(id="b", name="B", order=2, on_success="c"),
                PhaseSpec(id="c", name="C", order=3, is_terminal=True),
            ],
        )
        result = validate_graph(wf)
        assert result.is_valid
        assert len(result.edges) == 2
