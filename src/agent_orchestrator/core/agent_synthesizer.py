"""LLM-powered agent synthesis for filling capability gaps.

Synthesizes new agent definitions by using an LLM to design agents
that address detected capability gaps in multi-agent workflows.

Thread-safe: all mutable state is protected by a threading.Lock.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    LLMConfig,
    ProfileConfig,
    WorkflowPhaseConfig,
)
from agent_orchestrator.core.gap_detector import CapabilityGap

logger = logging.getLogger(__name__)

# Type alias for the async LLM call function
LLMCallFn = Callable[
    [str, str, LLMConfig],
    Coroutine[Any, Any, dict[str, Any]],
]

# Maximum characters for system prompt summaries in the synthesis prompt
_PROMPT_SUMMARY_MAX_CHARS = 500

# Preferred providers for synthesis LLM selection (ordered by preference)
_PREFERRED_PROVIDERS = ("anthropic", "openai")

_SYSTEM_PROMPT = """\
You are an expert agent architect. You design AI agents for multi-agent orchestration workflows.
Given a capability gap in a workflow phase, design a new agent to fill that gap.

Your design should address the gap with whatever combination is most effective:
- **Prompt engineering**: Craft a precise system prompt that guides the LLM to produce the right outputs.
- **Code generation**: If the gap requires deterministic logic, data transformation, validation, \
or any processing that an LLM prompt alone can't reliably handle, embed executable Python code \
directly in the system prompt using fenced code blocks. The agent runtime will extract and execute \
these code blocks. Include function definitions, import statements, and clear docstrings.
- **Hybrid approach**: Many gaps are best filled by combining a natural-language prompt (for reasoning, \
analysis, creative tasks) with embedded code (for output formatting, validation, calculations, \
API calls). Use both when appropriate.

When including code:
- Write production-quality Python with type hints and error handling.
- If the code needs external packages, list them in a "requirements" field.
- Structure code as callable functions the agent can invoke.
- Include example inputs/outputs in docstrings.

You must respond with a JSON object containing:
- "agent_id": A slug-style ID for the new agent
- "agent_name": A human-readable name
- "system_prompt": The complete system prompt for the new agent. Be detailed and specific. \
Include embedded code blocks if the task warrants it.
- "skills": List of capability tags the agent should have
- "temperature": Recommended temperature (0.0-2.0). Use low values (0.0-0.3) for code-heavy agents, \
moderate (0.3-0.7) for mixed, higher (0.7-1.0) for creative/analysis tasks.
- "max_tokens": Recommended max tokens (increase for code-heavy agents)
- "rationale": Why this agent design fills the gap, including your reasoning about whether \
to use prompt, code, or both
- "confidence": Your confidence this will work (0.0-1.0)
- "requirements": Optional list of Python packages needed (e.g. ["pandas", "numpy"])

Respond ONLY with valid JSON, no markdown fences."""


class SynthesisTestResult(BaseModel):
    """Result of pre-deployment validation and testing."""

    model_config = {"frozen": True}

    passed: bool = Field(description="Whether all checks passed")
    proposal_id: str = Field(description="ID of the tested proposal")
    checks: dict[str, str] = Field(
        description="Individual check results (name → 'pass: ...' or 'fail: ...')",
    )


class SynthesisProposal(BaseModel):
    """A proposal for a synthesized agent to fill a capability gap."""

    model_config = {"frozen": True}

    id: str = Field(description="Unique proposal identifier")
    gap_id: str = Field(description="ID of the capability gap this addresses")
    agent_spec: dict[str, Any] = Field(
        description="Agent specification ready for AgentDefinition(**spec)",
    )
    rationale: str = Field(description="Explanation of the design rationale")
    confidence: float = Field(
        description="Confidence that this proposal will help (0.0-1.0)",
    )
    requires_approval: bool = True
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    feedback: str = ""


class AgentSynthesizer:
    """Synthesizes new agent definitions to fill capability gaps using an LLM.

    Args:
        llm_call_fn: Async callable for making LLM requests.
        synthesis_llm_config: Optional LLM config for synthesis calls.
            If None, derived from the most capable agent in the target phase.
    """

    def __init__(
        self,
        llm_call_fn: LLMCallFn,
        synthesis_llm_config: LLMConfig | None = None,
    ) -> None:
        self._llm_call_fn = llm_call_fn
        self._synthesis_llm_config = synthesis_llm_config
        self._proposals: dict[str, SynthesisProposal] = {}
        self._lock = threading.Lock()

    # -- public API ----------------------------------------------------------

    async def propose(
        self,
        gap: CapabilityGap,
        profile: ProfileConfig,
    ) -> SynthesisProposal:
        """Propose a new agent to fill the given capability gap.

        Uses LLM to design the agent, falling back to template-based
        synthesis if the LLM call or response parsing fails.

        Args:
            gap: The detected capability gap to address.
            profile: The active profile configuration.

        Returns:
            A SynthesisProposal with the designed agent spec.
        """
        phase = self._find_phase(gap.phase_id, profile)
        phase_agents = self._get_phase_agents(phase, profile) if phase else []
        llm_config = self._select_llm_config(phase_agents)
        user_prompt = self._build_user_prompt(gap, phase, phase_agents)

        agent_spec = await self._call_llm_for_spec(
            gap, profile, phase, llm_config, user_prompt,
        )

        proposal_id = f"synth-{uuid4().hex[:12]}"
        confidence = agent_spec.pop("_confidence", 0.7)
        rationale = agent_spec.pop("_rationale", "Template-based synthesis")

        proposal = SynthesisProposal(
            id=proposal_id,
            gap_id=gap.id,
            agent_spec=agent_spec,
            rationale=rationale,
            confidence=confidence,
        )

        with self._lock:
            self._proposals[proposal_id] = proposal

        logger.info(
            "Created synthesis proposal %s for gap %s (confidence=%.2f)",
            proposal_id, gap.id, confidence,
        )
        return proposal

    def get_proposal(self, proposal_id: str) -> SynthesisProposal | None:
        """Retrieve a proposal by ID.

        Args:
            proposal_id: The proposal identifier.

        Returns:
            The proposal if found, otherwise None.
        """
        with self._lock:
            return self._proposals.get(proposal_id)

    def list_proposals(
        self,
        status: str | None = None,
    ) -> list[SynthesisProposal]:
        """List proposals, optionally filtered by status.

        Args:
            status: If provided, only return proposals with this status.

        Returns:
            List of matching proposals.
        """
        with self._lock:
            proposals = list(self._proposals.values())
        if status is not None:
            proposals = [p for p in proposals if p.status == status]
        return proposals

    def approve_proposal(
        self,
        proposal_id: str,
    ) -> SynthesisProposal | None:
        """Approve a pending proposal.

        Args:
            proposal_id: The proposal to approve.

        Returns:
            Updated proposal with status 'approved', or None if not found.
        """
        return self._update_status(proposal_id, "approved")

    def reject_proposal(
        self,
        proposal_id: str,
        feedback: str = "",
    ) -> SynthesisProposal | None:
        """Reject a proposal with optional feedback.

        Args:
            proposal_id: The proposal to reject.
            feedback: Rejection reason for future improvement.

        Returns:
            Updated proposal with status 'rejected', or None if not found.
        """
        return self._update_status(proposal_id, "rejected", feedback=feedback)

    def mark_deployed(
        self,
        proposal_id: str,
    ) -> SynthesisProposal | None:
        """Mark a proposal as deployed.

        Args:
            proposal_id: The proposal to mark deployed.

        Returns:
            Updated proposal with status 'deployed', or None if not found.
        """
        return self._update_status(proposal_id, "deployed")

    async def validate_and_test(
        self,
        proposal_id: str,
        profile: ProfileConfig,
    ) -> SynthesisTestResult:
        """Validate agent spec and run a dry-run LLM test before deployment.

        Performs three checks:
        1. Schema validation — can the spec construct a valid AgentDefinition?
        2. Phase compatibility — does the target phase exist in the profile?
        3. Dry-run test — send a lightweight probe to the LLM to verify
           the agent's system prompt produces a response.

        Args:
            proposal_id: The proposal to validate and test.
            profile: The active profile configuration.

        Returns:
            SynthesisTestResult with pass/fail and details.
        """
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return SynthesisTestResult(
                passed=False,
                proposal_id=proposal_id,
                checks={"lookup": "Proposal not found"},
            )

        checks: dict[str, str] = {}

        # 1. Schema validation
        agent_def = self._validate_spec_schema(proposal.agent_spec, checks)
        if agent_def is None:
            return SynthesisTestResult(
                passed=False, proposal_id=proposal_id, checks=checks,
            )

        # 2. Phase compatibility
        self._validate_phase_compat(agent_def, profile, checks)

        # 3. Dry-run LLM test
        await self._dry_run_test(agent_def, checks)

        passed = all(
            v.startswith("pass") for v in checks.values()
        )
        return SynthesisTestResult(
            passed=passed, proposal_id=proposal_id, checks=checks,
        )

    def _validate_spec_schema(
        self,
        agent_spec: dict[str, Any],
        checks: dict[str, str],
    ) -> AgentDefinition | None:
        """Validate the agent spec can construct a valid AgentDefinition.

        Args:
            agent_spec: The agent specification dict.
            checks: Results dict to update.

        Returns:
            AgentDefinition if valid, None otherwise.
        """
        try:
            agent_def = AgentDefinition(**agent_spec)
            checks["schema"] = "pass: valid AgentDefinition"
            return agent_def
        except (ValueError, TypeError) as exc:
            checks["schema"] = f"fail: {exc}"
            logger.warning("Agent spec schema validation failed: %s", exc)
            return None

    def _validate_phase_compat(
        self,
        agent_def: AgentDefinition,
        profile: ProfileConfig,
        checks: dict[str, str],
    ) -> None:
        """Check that the agent's target phases exist in the profile.

        Args:
            agent_def: The validated agent definition.
            profile: The active profile configuration.
            checks: Results dict to update.
        """
        profile_phase_ids = {p.id for p in profile.workflow.phases}
        missing_phases = [
            p for p in agent_def.phases if p not in profile_phase_ids
        ]
        if missing_phases:
            checks["phase_compat"] = (
                f"fail: phases not in profile: {missing_phases}"
            )
        else:
            checks["phase_compat"] = "pass: all target phases exist"

    async def _dry_run_test(
        self,
        agent_def: AgentDefinition,
        checks: dict[str, str],
    ) -> None:
        """Send a lightweight probe to the LLM to verify the agent works.

        Uses a simple test prompt that asks the agent to confirm readiness.
        This catches invalid API keys, model IDs, and prompt issues.

        Args:
            agent_def: The agent definition to test.
            checks: Results dict to update.
        """
        test_prompt = (
            "This is a pre-deployment validation test. "
            "Respond with a JSON object: "
            '{"status": "ready", "capabilities": [<your main capabilities>]}. '
            "Respond ONLY with valid JSON."
        )
        try:
            response = await self._llm_call_fn(
                agent_def.system_prompt, test_prompt, agent_def.llm,
            )
            response_text = response.get("response", "")
            if not response_text or len(response_text.strip()) < 2:
                checks["dry_run"] = "fail: empty response from LLM"
            else:
                checks["dry_run"] = (
                    f"pass: LLM responded ({len(response_text)} chars)"
                )
        except Exception as exc:
            checks["dry_run"] = f"fail: LLM call error: {exc}"
            logger.warning(
                "Dry-run test failed for agent '%s': %s",
                agent_def.id, exc,
                exc_info=True,
            )

    # -- private helpers: LLM interaction ------------------------------------

    async def _call_llm_for_spec(
        self,
        gap: CapabilityGap,
        profile: ProfileConfig,
        phase: WorkflowPhaseConfig | None,
        llm_config: LLMConfig,
        user_prompt: str,
    ) -> dict[str, Any]:
        """Call the LLM and parse the response into an agent spec.

        Falls back to template-based synthesis on any error.

        Returns:
            Agent spec dict with extra _confidence and _rationale keys.
        """
        try:
            response = await self._llm_call_fn(
                _SYSTEM_PROMPT, user_prompt, llm_config,
            )
            return self._parse_llm_response(
                response, gap, profile, phase, llm_config,
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "LLM response parsing failed for gap %s: %s. "
                "Falling back to template synthesis.",
                gap.id, exc,
            )
            return self._fallback_synthesis(gap, profile)
        except Exception as exc:
            logger.warning(
                "LLM call failed for gap %s: %s. "
                "Falling back to template synthesis.",
                gap.id, exc,
                exc_info=True,
            )
            return self._fallback_synthesis(gap, profile)

    def _parse_llm_response(
        self,
        response: dict[str, Any],
        gap: CapabilityGap,
        profile: ProfileConfig,
        phase: WorkflowPhaseConfig | None,
        llm_config: LLMConfig,
    ) -> dict[str, Any]:
        """Parse the LLM response JSON into an agent spec dict.

        Args:
            response: Raw LLM response with a 'response' key.
            gap: The capability gap being addressed.
            profile: Active profile configuration.
            phase: Target workflow phase config.
            llm_config: LLM config used for the synthesis call.

        Returns:
            Agent spec dict with _confidence and _rationale metadata.

        Raises:
            json.JSONDecodeError: If response text is not valid JSON.
            KeyError: If required fields are missing.
        """
        response_text = response["response"]
        parsed = json.loads(response_text)

        all_skills = list(set(
            parsed.get("skills", [])
            + gap.suggested_capabilities
            + self._get_phase_required_capabilities(phase, profile)
        ))

        temperature = float(parsed.get("temperature", llm_config.temperature))
        max_tokens = int(parsed.get("max_tokens", llm_config.max_tokens))

        spec = self._build_agent_spec(
            agent_id=parsed.get("agent_id", f"synth-agent-{uuid4().hex[:8]}"),
            agent_name=parsed.get("agent_name", "Synthesized Agent"),
            system_prompt=parsed["system_prompt"],
            skills=all_skills,
            gap=gap,
            llm_config=llm_config,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        spec["_confidence"] = float(parsed.get("confidence", 0.7))
        spec["_rationale"] = parsed.get("rationale", "LLM-designed agent")
        return spec

    # -- private helpers: fallback -------------------------------------------

    def _fallback_synthesis(
        self,
        gap: CapabilityGap,
        profile: ProfileConfig,
    ) -> dict[str, Any]:
        """Template-based fallback when LLM synthesis fails.

        Args:
            gap: The capability gap to address.
            profile: Active profile configuration.

        Returns:
            Agent spec dict with _confidence and _rationale metadata.
        """
        phase = self._find_phase(gap.phase_id, profile)
        phase_agents = self._get_phase_agents(phase, profile) if phase else []
        llm_config = self._select_llm_config(phase_agents)

        phase_desc = phase.description if phase else "unknown phase"
        gate_conditions = self._collect_gate_conditions(phase)

        system_prompt = (
            f"You are a specialized agent for the '{gap.phase_id}' phase.\n\n"
            f"Phase description: {phase_desc}\n\n"
            f"Your task is to address the following gap: {gap.description}\n\n"
        )
        if gate_conditions:
            system_prompt += (
                "Quality gate conditions you must satisfy:\n"
                + "\n".join(f"- {c}" for c in gate_conditions)
                + "\n\n"
            )
        system_prompt += (
            "Provide thorough, well-structured output that meets all "
            "quality requirements for this phase."
        )

        spec = self._build_agent_spec(
            agent_id=f"synth-agent-{uuid4().hex[:8]}",
            agent_name=f"Synthesized Agent for {gap.phase_id}",
            system_prompt=system_prompt,
            skills=list(gap.suggested_capabilities),
            gap=gap,
            llm_config=llm_config,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

        spec["_confidence"] = 0.4
        spec["_rationale"] = "Template-based synthesis (LLM call failed)"
        return spec

    # -- private helpers: spec building --------------------------------------

    def _build_agent_spec(
        self,
        *,
        agent_id: str,
        agent_name: str,
        system_prompt: str,
        skills: list[str],
        gap: CapabilityGap,
        llm_config: LLMConfig,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Build the agent_spec dict ready for AgentDefinition(**spec).

        Args:
            agent_id: Unique agent identifier.
            agent_name: Human-readable agent name.
            system_prompt: The agent's system prompt.
            skills: Capability tags for the agent.
            gap: The gap being addressed.
            llm_config: Base LLM config for provider/model.
            temperature: Temperature setting for the agent.
            max_tokens: Max tokens setting for the agent.

        Returns:
            Dict suitable for AgentDefinition(**spec).
        """
        return {
            "id": agent_id,
            "name": agent_name,
            "description": (
                f"Synthesized agent to fill {gap.gap_source.value} gap "
                f"in phase '{gap.phase_id}'"
            ),
            "system_prompt": system_prompt,
            "skills": skills,
            "phases": [gap.phase_id],
            "llm": {
                "provider": llm_config.provider,
                "model": llm_config.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            "concurrency": 1,
            "retry_policy": {
                "max_retries": 3,
                "delay_seconds": 1.0,
                "backoff_multiplier": 2.0,
            },
            "enabled": False,
        }

    # -- private helpers: prompt building ------------------------------------

    def _build_user_prompt(
        self,
        gap: CapabilityGap,
        phase: WorkflowPhaseConfig | None,
        phase_agents: list[AgentDefinition],
    ) -> str:
        """Build the user prompt with full context for the LLM.

        Args:
            gap: The capability gap to address.
            phase: Target workflow phase config.
            phase_agents: Existing agents in the target phase.

        Returns:
            Formatted user prompt string.
        """
        lines: list[str] = []

        lines.append("## Workflow Phase")
        if phase is not None:
            lines.append(f"- Phase ID: {phase.id}")
            lines.append(f"- Phase Name: {phase.name}")
            lines.append(f"- Description: {phase.description}")
        else:
            lines.append(f"- Phase ID: {gap.phase_id}")
            lines.append("- (Phase configuration not found)")

        self._append_quality_gate_info(lines, phase)
        self._append_gap_details(lines, gap)
        self._append_existing_agents(lines, phase_agents)

        return "\n".join(lines)

    def _append_quality_gate_info(
        self,
        lines: list[str],
        phase: WorkflowPhaseConfig | None,
    ) -> None:
        """Append quality gate information to prompt lines."""
        gate_conditions = self._collect_gate_conditions(phase)
        if gate_conditions:
            lines.append("\n## Quality Gate Conditions")
            for cond in gate_conditions:
                lines.append(f"- {cond}")

    def _append_gap_details(
        self,
        lines: list[str],
        gap: CapabilityGap,
    ) -> None:
        """Append gap details to prompt lines."""
        lines.append("\n## Capability Gap")
        lines.append(f"- Source: {gap.gap_source.value}")
        lines.append(f"- Severity: {gap.severity.value}")
        lines.append(f"- Description: {gap.description}")
        lines.append(f"- Evidence: {json.dumps(gap.evidence)}")
        if gap.suggested_capabilities:
            lines.append(
                f"- Suggested capabilities: {', '.join(gap.suggested_capabilities)}"
            )

    def _append_existing_agents(
        self,
        lines: list[str],
        phase_agents: list[AgentDefinition],
    ) -> None:
        """Append existing agent summaries to prompt lines."""
        if not phase_agents:
            lines.append("\n## Existing Agents")
            lines.append("- None currently assigned to this phase")
            return

        lines.append("\n## Existing Agents in Phase")
        for agent in phase_agents:
            prompt_summary = agent.system_prompt[:_PROMPT_SUMMARY_MAX_CHARS]
            if len(agent.system_prompt) > _PROMPT_SUMMARY_MAX_CHARS:
                prompt_summary += "..."
            lines.append(f"\n### {agent.name} ({agent.id})")
            lines.append(f"- Skills: {', '.join(agent.skills) or 'none'}")
            lines.append(f"- System prompt: {prompt_summary}")

    # -- private helpers: config selection ------------------------------------

    def _select_llm_config(
        self,
        phase_agents: list[AgentDefinition],
    ) -> LLMConfig:
        """Select the LLM config for the synthesis call.

        Uses synthesis_llm_config if provided, otherwise picks the most
        capable agent's config from the phase (preferring anthropic/openai).

        Args:
            phase_agents: Agents in the target phase.

        Returns:
            LLM config to use for the synthesis call.
        """
        if self._synthesis_llm_config is not None:
            return self._synthesis_llm_config

        if not phase_agents:
            return LLMConfig(
                provider="openai",
                model="gpt-4o",
                temperature=0.3,
                max_tokens=4000,
            )

        return self._pick_most_capable_config(phase_agents)

    def _pick_most_capable_config(
        self,
        agents: list[AgentDefinition],
    ) -> LLMConfig:
        """Pick the most capable LLM config from a list of agents.

        Prefers anthropic/openai providers and highest max_tokens.

        Args:
            agents: Agents to choose from.

        Returns:
            The selected LLM config.
        """
        def _rank(agent: AgentDefinition) -> tuple[int, int]:
            provider_score = 0
            for i, preferred in enumerate(_PREFERRED_PROVIDERS):
                if agent.llm.provider == preferred:
                    provider_score = len(_PREFERRED_PROVIDERS) - i
                    break
            return (provider_score, agent.llm.max_tokens)

        best = max(agents, key=_rank)
        return best.llm

    # -- private helpers: phase/agent lookup ----------------------------------

    def _find_phase(
        self,
        phase_id: str,
        profile: ProfileConfig,
    ) -> WorkflowPhaseConfig | None:
        """Find a phase config by ID in the profile.

        Args:
            phase_id: The phase identifier to look up.
            profile: The active profile configuration.

        Returns:
            The phase config if found, otherwise None.
        """
        for phase in profile.workflow.phases:
            if phase.id == phase_id:
                return phase
        return None

    def _get_phase_agents(
        self,
        phase: WorkflowPhaseConfig | None,
        profile: ProfileConfig,
    ) -> list[AgentDefinition]:
        """Get all agents assigned to a phase.

        Args:
            phase: The phase to look up agents for.
            profile: The active profile configuration.

        Returns:
            List of agent definitions assigned to the phase.
        """
        if phase is None:
            return []
        phase_agent_ids = set(phase.agents)
        return [a for a in profile.agents if a.id in phase_agent_ids]

    def _get_phase_required_capabilities(
        self,
        phase: WorkflowPhaseConfig | None,
        profile: ProfileConfig,
    ) -> list[str]:
        """Collect required capabilities declared on the phase.

        Args:
            phase: The target phase config.
            profile: The active profile configuration.

        Returns:
            List of required capability tags from the phase config.
        """
        if phase is None:
            return []
        return list(phase.required_capabilities)

    def _collect_gate_conditions(
        self,
        phase: WorkflowPhaseConfig | None,
    ) -> list[str]:
        """Collect all quality gate condition expressions for a phase.

        Args:
            phase: The phase to inspect.

        Returns:
            List of condition expression strings.
        """
        if phase is None:
            return []
        conditions: list[str] = []
        for gate in phase.quality_gates:
            for condition in gate.conditions:
                conditions.append(condition.expression)
        return conditions

    # -- private helpers: status updates -------------------------------------

    def _update_status(
        self,
        proposal_id: str,
        new_status: str,
        feedback: str = "",
    ) -> SynthesisProposal | None:
        """Update the status of a proposal.

        Creates a new frozen instance with the updated fields.

        Args:
            proposal_id: The proposal to update.
            new_status: The new status value.
            feedback: Optional feedback (used for rejections).

        Returns:
            Updated proposal, or None if not found.
        """
        with self._lock:
            existing = self._proposals.get(proposal_id)
            if existing is None:
                logger.warning(
                    "Proposal %s not found for status update to '%s'",
                    proposal_id, new_status,
                )
                return None

            update_fields: dict[str, Any] = {"status": new_status}
            if feedback:
                update_fields["feedback"] = feedback

            updated = existing.model_copy(update=update_fields)
            self._proposals[proposal_id] = updated

        logger.info(
            "Updated proposal %s status to '%s'",
            proposal_id, new_status,
        )
        return updated
