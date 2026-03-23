"""Tests for LLM-powered agent synthesis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    ConditionConfig,
    LLMConfig,
    ProfileConfig,
    QualityGateConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
)
from agent_orchestrator.core.agent_synthesizer import (
    AgentSynthesizer,
    SynthesisProposal,
    SynthesisTestResult,
)
from agent_orchestrator.core.gap_detector import CapabilityGap, GapSeverity, GapSource


def _llm() -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-4o")


def _gap(
    phase_id: str = "analysis",
    source: GapSource = GapSource.STATIC_SKILL_MISMATCH,
    suggested: list[str] | None = None,
) -> CapabilityGap:
    return CapabilityGap(
        id="gap-test-001",
        phase_id=phase_id,
        agent_id=None,
        gap_source=source,
        severity=GapSeverity.WARNING,
        description=f"Test gap in {phase_id}",
        evidence={"missing": suggested or ["sentiment-analysis"]},
        suggested_capabilities=suggested or ["sentiment-analysis"],
        detected_at=datetime.now(timezone.utc),
    )


def _profile(
    agents: list[AgentDefinition] | None = None,
    phases: list[WorkflowPhaseConfig] | None = None,
) -> ProfileConfig:
    default_agents = [
        AgentDefinition(
            id="existing-agent",
            name="Existing Agent",
            system_prompt="You are a test agent.",
            phases=["analysis"],
            llm=_llm(),
            skills=["nlp"],
        ),
    ]
    default_phases = [
        WorkflowPhaseConfig(
            id="analysis",
            name="Analysis",
            description="Analyze the input",
            order=0,
            agents=["existing-agent"],
            required_capabilities=["sentiment-analysis"],
            quality_gates=[
                QualityGateConfig(
                    name="confidence-check",
                    conditions=[ConditionConfig(expression="confidence >= 0.8")],
                ),
            ],
            on_success="done",
        ),
        WorkflowPhaseConfig(
            id="done",
            name="Done",
            order=1,
            is_terminal=True,
        ),
    ]
    return ProfileConfig(
        name="test-profile",
        agents=agents or default_agents,
        workflow=WorkflowConfig(
            name="test",
            phases=phases or default_phases,
        ),
    )


class TestAgentSynthesizer:
    """Tests for the AgentSynthesizer class."""

    @staticmethod
    async def _mock_llm_success(
        system_prompt: str, user_prompt: str, llm_config: LLMConfig,
    ) -> dict[str, Any]:
        """Mock LLM that returns valid synthesis JSON."""
        return {
            "response": json.dumps({
                "agent_id": "sentiment-analyzer",
                "agent_name": "Sentiment Analyzer Agent",
                "system_prompt": (
                    "You are a sentiment analysis specialist.\n\n"
                    "Analyze text and return a JSON object with:\n"
                    "- sentiment: positive/negative/neutral\n"
                    "- confidence: 0.0-1.0\n\n"
                    "```python\n"
                    "def validate_output(result: dict) -> bool:\n"
                    "    return 'sentiment' in result and 'confidence' in result\n"
                    "```"
                ),
                "skills": ["sentiment-analysis", "text-classification"],
                "temperature": 0.2,
                "max_tokens": 2000,
                "rationale": "Fills the sentiment analysis gap with a specialized agent",
                "confidence": 0.85,
            }),
            "model": "gpt-4o",
        }

    @staticmethod
    async def _mock_llm_failure(
        system_prompt: str, user_prompt: str, llm_config: LLMConfig,
    ) -> dict[str, Any]:
        """Mock LLM that returns invalid response."""
        return {"response": "This is not valid JSON"}

    @staticmethod
    async def _mock_llm_error(
        system_prompt: str, user_prompt: str, llm_config: LLMConfig,
    ) -> dict[str, Any]:
        """Mock LLM that raises an exception."""
        msg = "LLM service unavailable"
        raise ConnectionError(msg)

    @pytest.mark.asyncio
    async def test_propose_with_llm_success(self) -> None:
        """Successful LLM call produces valid proposal."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        gap = _gap()
        profile = _profile()

        proposal = await synthesizer.propose(gap, profile)

        assert proposal.id.startswith("synth-")
        assert proposal.gap_id == gap.id
        assert proposal.status == "pending"
        assert proposal.confidence == 0.85
        assert proposal.requires_approval is True
        assert "sentiment-analyzer" in proposal.agent_spec["id"]
        assert proposal.agent_spec["enabled"] is False
        assert "sentiment-analysis" in proposal.agent_spec["skills"]
        assert proposal.agent_spec["phases"] == ["analysis"]

    @pytest.mark.asyncio
    async def test_propose_fallback_on_json_error(self) -> None:
        """Invalid LLM JSON triggers template fallback."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_failure)
        gap = _gap()
        profile = _profile()

        proposal = await synthesizer.propose(gap, profile)

        assert proposal.id.startswith("synth-")
        assert proposal.confidence == 0.4  # Fallback confidence
        assert "Template-based" in proposal.rationale
        assert proposal.agent_spec["enabled"] is False

    @pytest.mark.asyncio
    async def test_propose_fallback_on_exception(self) -> None:
        """LLM exception triggers template fallback."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_error)
        gap = _gap()
        profile = _profile()

        proposal = await synthesizer.propose(gap, profile)

        assert proposal.id.startswith("synth-")
        assert proposal.confidence == 0.4
        assert proposal.agent_spec["enabled"] is False

    @pytest.mark.asyncio
    async def test_proposal_lifecycle(self) -> None:
        """Proposals go through pending -> approved -> deployed lifecycle."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        proposal = await synthesizer.propose(_gap(), _profile())

        assert proposal.status == "pending"

        approved = synthesizer.approve_proposal(proposal.id)
        assert approved is not None
        assert approved.status == "approved"

        deployed = synthesizer.mark_deployed(proposal.id)
        assert deployed is not None
        assert deployed.status == "deployed"

    @pytest.mark.asyncio
    async def test_reject_with_feedback(self) -> None:
        """Rejected proposals record feedback."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        proposal = await synthesizer.propose(_gap(), _profile())

        rejected = synthesizer.reject_proposal(
            proposal.id, feedback="System prompt needs more detail",
        )
        assert rejected is not None
        assert rejected.status == "rejected"
        assert rejected.feedback == "System prompt needs more detail"

    @pytest.mark.asyncio
    async def test_list_proposals_filter_by_status(self) -> None:
        """list_proposals() filters by status."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        p1 = await synthesizer.propose(_gap(), _profile())
        p2 = await synthesizer.propose(_gap(phase_id="review"), _profile())

        synthesizer.approve_proposal(p1.id)

        pending = synthesizer.list_proposals(status="pending")
        approved = synthesizer.list_proposals(status="approved")
        all_proposals = synthesizer.list_proposals()

        assert len(pending) == 1
        assert len(approved) == 1
        assert len(all_proposals) == 2

    @pytest.mark.asyncio
    async def test_get_nonexistent_proposal(self) -> None:
        """Getting non-existent proposal returns None."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        assert synthesizer.get_proposal("does-not-exist") is None

    @pytest.mark.asyncio
    async def test_agent_spec_has_required_fields(self) -> None:
        """Agent spec dict has all fields needed for AgentDefinition."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        proposal = await synthesizer.propose(_gap(), _profile())

        spec = proposal.agent_spec
        required_keys = {
            "id", "name", "description", "system_prompt",
            "skills", "phases", "llm", "concurrency",
            "retry_policy", "enabled",
        }
        assert required_keys.issubset(set(spec.keys()))
        assert isinstance(spec["llm"], dict)
        assert "provider" in spec["llm"]
        assert "model" in spec["llm"]

    @pytest.mark.asyncio
    async def test_synthesis_with_code_in_prompt(self) -> None:
        """LLM-generated system prompts can include code blocks."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        proposal = await synthesizer.propose(_gap(), _profile())

        system_prompt = proposal.agent_spec["system_prompt"]
        assert "```python" in system_prompt
        assert "def validate_output" in system_prompt

    @pytest.mark.asyncio
    async def test_custom_synthesis_llm_config(self) -> None:
        """Custom synthesis LLM config is used for the call."""
        custom_config = LLMConfig(
            provider="anthropic", model="claude-sonnet-4-20250514",
            temperature=0.1, max_tokens=8000,
        )
        synthesizer = AgentSynthesizer(
            llm_call_fn=self._mock_llm_success,
            synthesis_llm_config=custom_config,
        )
        # Just verify it doesn't error — the mock ignores config
        proposal = await synthesizer.propose(_gap(), _profile())
        assert proposal.id.startswith("synth-")

    @pytest.mark.asyncio
    async def test_validate_and_test_passes(self) -> None:
        """Valid proposal with working LLM passes all checks."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        proposal = await synthesizer.propose(_gap(), _profile())
        profile = _profile()

        result = await synthesizer.validate_and_test(proposal.id, profile)

        assert result.passed is True
        assert result.proposal_id == proposal.id
        assert result.checks["schema"].startswith("pass")
        assert result.checks["phase_compat"].startswith("pass")
        assert result.checks["dry_run"].startswith("pass")

    @pytest.mark.asyncio
    async def test_validate_and_test_nonexistent_proposal(self) -> None:
        """Testing a nonexistent proposal returns failed result."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        result = await synthesizer.validate_and_test("nope", _profile())

        assert result.passed is False
        assert "not found" in result.checks.get("lookup", "").lower()

    @pytest.mark.asyncio
    async def test_validate_and_test_bad_phase(self) -> None:
        """Proposal targeting a phase not in profile fails phase_compat."""
        synthesizer = AgentSynthesizer(llm_call_fn=self._mock_llm_success)
        gap = _gap(phase_id="nonexistent-phase")
        proposal = await synthesizer.propose(gap, _profile())
        profile = _profile()

        result = await synthesizer.validate_and_test(proposal.id, profile)

        assert result.passed is False
        assert result.checks["phase_compat"].startswith("fail")

    @pytest.mark.asyncio
    async def test_validate_and_test_llm_error_fails_dry_run(self) -> None:
        """When LLM errors during dry run, dry_run check fails."""
        # Use success for synthesis, error for dry run
        call_count = 0

        async def _success_then_error(
            system_prompt: str, user_prompt: str, llm_config: LLMConfig,
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return await self._mock_llm_success(
                    system_prompt, user_prompt, llm_config,
                )
            msg = "LLM unavailable"
            raise ConnectionError(msg)

        synthesizer = AgentSynthesizer(llm_call_fn=_success_then_error)
        proposal = await synthesizer.propose(_gap(), _profile())

        result = await synthesizer.validate_and_test(proposal.id, _profile())

        assert result.checks["schema"].startswith("pass")
        assert result.checks["dry_run"].startswith("fail")
        assert result.passed is False
