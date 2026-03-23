"""Tests for capability gap static validation."""

from __future__ import annotations

import pytest

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    ConditionConfig,
    GovernanceConfig,
    LLMConfig,
    ProfileConfig,
    QualityGateConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
)
from agent_orchestrator.configuration.validator import (
    ValidationResult,
    validate_capability_coverage,
    validate_profile,
)


def _llm() -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-4o")


def _agent(agent_id: str, phases: list[str], skills: list[str] | None = None) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        name=agent_id.title(),
        system_prompt=f"You are {agent_id}",
        phases=phases,
        llm=_llm(),
        skills=skills or [],
    )


def _phase(
    phase_id: str,
    agents: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    expected_output_fields: list[str] | None = None,
    quality_gates: list[QualityGateConfig] | None = None,
    is_terminal: bool = False,
    skippable: bool = False,
    on_success: str = "",
) -> WorkflowPhaseConfig:
    return WorkflowPhaseConfig(
        id=phase_id,
        name=phase_id.title(),
        order=0,
        agents=agents or [],
        required_capabilities=required_capabilities or [],
        expected_output_fields=expected_output_fields or [],
        quality_gates=quality_gates or [],
        is_terminal=is_terminal,
        skippable=skippable,
        on_success=on_success,
    )


def _profile(
    agents: list[AgentDefinition],
    phases: list[WorkflowPhaseConfig],
) -> ProfileConfig:
    return ProfileConfig(
        name="test",
        agents=agents,
        workflow=WorkflowConfig(name="test", phases=phases),
    )


class TestValidateCapabilityCoverage:
    """Tests for validate_capability_coverage()."""

    def test_no_capabilities_no_warnings(self) -> None:
        """Profiles without required_capabilities produce no capability warnings."""
        profile = _profile(
            agents=[_agent("a1", ["p1"], skills=["nlp"])],
            phases=[_phase("p1", agents=["a1"], is_terminal=True)],
        )
        result = validate_capability_coverage(profile)
        assert result.is_valid
        assert len(result.warnings) == 0

    def test_missing_capability_flagged(self) -> None:
        """Phase with required capability not provided by agents is flagged."""
        profile = _profile(
            agents=[_agent("a1", ["analysis"], skills=["nlp"])],
            phases=[
                _phase(
                    "analysis",
                    agents=["a1"],
                    required_capabilities=["sentiment-analysis"],
                    on_success="done",
                ),
                _phase("done", is_terminal=True),
            ],
        )
        result = validate_capability_coverage(profile)
        assert len(result.warnings) >= 1
        assert any("sentiment-analysis" in w for w in result.warnings)

    def test_covered_capability_no_warning(self) -> None:
        """Phase where all required capabilities are covered produces no skill mismatch warning."""
        profile = _profile(
            agents=[_agent("a1", ["analysis"], skills=["sentiment-analysis"])],
            phases=[
                _phase(
                    "analysis",
                    agents=["a1"],
                    required_capabilities=["sentiment-analysis"],
                    on_success="done",
                ),
                _phase("done", is_terminal=True),
            ],
        )
        result = validate_capability_coverage(profile)
        # No "not provided" warnings — all required caps are covered
        mismatch_warnings = [w for w in result.warnings if "not provided" in w.lower()]
        assert len(mismatch_warnings) == 0

    def test_empty_phase_warning(self) -> None:
        """Non-terminal phase with no agents and not skippable triggers warning."""
        profile = _profile(
            agents=[_agent("a1", ["p2"])],
            phases=[
                _phase("p1", agents=[], on_success="p2"),
                _phase("p2", agents=["a1"], is_terminal=True),
            ],
        )
        result = validate_capability_coverage(profile)
        assert any("no agents" in w.lower() for w in result.warnings)

    def test_skippable_phase_no_warning(self) -> None:
        """Skippable empty phases don't trigger empty-phase warning."""
        profile = _profile(
            agents=[_agent("a1", ["p2"])],
            phases=[
                _phase("p1", agents=[], skippable=True, on_success="p2"),
                _phase("p2", agents=["a1"], is_terminal=True),
            ],
        )
        result = validate_capability_coverage(profile)
        empty_warnings = [w for w in result.warnings if "no agents" in w.lower()]
        assert len(empty_warnings) == 0

    def test_orphan_skills_warning(self) -> None:
        """Agent skills not referenced by any phase's required_capabilities."""
        profile = _profile(
            agents=[_agent("a1", ["p1"], skills=["nlp", "vision", "coding"])],
            phases=[
                _phase(
                    "p1",
                    agents=["a1"],
                    required_capabilities=["nlp"],
                    on_success="done",
                ),
                _phase("done", is_terminal=True),
            ],
        )
        result = validate_capability_coverage(profile)
        orphan_warnings = [w for w in result.warnings if "not referenced" in w.lower()]
        assert len(orphan_warnings) == 1
        warning_text = orphan_warnings[0]
        assert "vision" in warning_text or "coding" in warning_text

    def test_quality_gate_field_mismatch(self) -> None:
        """Gate referencing fields not in expected_output_fields triggers warning."""
        gate = QualityGateConfig(
            name="confidence-gate",
            conditions=[
                ConditionConfig(expression="confidence >= 0.8"),
                ConditionConfig(expression="risk_level == 'low'"),
            ],
        )
        profile = _profile(
            agents=[_agent("a1", ["p1"])],
            phases=[
                _phase(
                    "p1",
                    agents=["a1"],
                    expected_output_fields=["confidence"],
                    quality_gates=[gate],
                    on_success="done",
                ),
                _phase("done", is_terminal=True),
            ],
        )
        result = validate_capability_coverage(profile)
        field_warnings = [w for w in result.warnings if "risk_level" in w]
        assert len(field_warnings) == 1

    def test_validate_profile_includes_capability_check(self) -> None:
        """validate_profile() runs capability coverage as part of its passes."""
        profile = _profile(
            agents=[_agent("a1", ["p1"], skills=["nlp"])],
            phases=[
                _phase(
                    "p1",
                    agents=["a1"],
                    required_capabilities=["sentiment-analysis"],
                    on_success="done",
                ),
                _phase("done", is_terminal=True),
            ],
        )
        result = validate_profile(profile)
        assert any("sentiment-analysis" in w for w in result.warnings)

    def test_terminal_phases_skipped(self) -> None:
        """Terminal phases are not checked for capabilities."""
        profile = _profile(
            agents=[],
            phases=[
                _phase(
                    "done",
                    agents=[],
                    required_capabilities=["something"],
                    is_terminal=True,
                ),
            ],
        )
        result = validate_capability_coverage(profile)
        cap_warnings = [w for w in result.warnings if "capabilities" in w.lower()]
        assert len(cap_warnings) == 0

    def test_multiple_agents_cover_capabilities(self) -> None:
        """Multiple agents collectively covering capabilities is OK."""
        profile = _profile(
            agents=[
                _agent("a1", ["p1"], skills=["nlp"]),
                _agent("a2", ["p1"], skills=["sentiment-analysis"]),
            ],
            phases=[
                _phase(
                    "p1",
                    agents=["a1", "a2"],
                    required_capabilities=["nlp", "sentiment-analysis"],
                    is_terminal=True,
                ),
            ],
        )
        result = validate_capability_coverage(profile)
        cap_warnings = [w for w in result.warnings if "capabilities" in w.lower() and "not provided" in w.lower()]
        assert len(cap_warnings) == 0

    def test_backward_compatible_no_capabilities(self) -> None:
        """Existing profiles without capability fields validate cleanly."""
        profile = _profile(
            agents=[_agent("a1", ["p1"])],
            phases=[_phase("p1", agents=["a1"], is_terminal=True)],
        )
        result = validate_profile(profile)
        # Should have no errors from capability validation
        assert result.is_valid
