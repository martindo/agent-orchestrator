"""Profile validation for Studio.

Two validation paths:
1. **Studio-side** — fast structural checks without round-tripping to runtime.
2. **Runtime integration** — converts IR → ProfileConfig, calls the runtime's
   ``validate_profile()`` for full cross-reference and semantic validation.

Both paths return a ``StudioValidationResult`` with errors, warnings, and
per-field error locations where possible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from studio.exceptions import ValidationError
from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)


@dataclass
class ValidationMessage:
    """A single validation error or warning.

    Attributes:
        message: Human-readable description.
        path: Dot-path to the offending field (e.g. ``agents[0].llm.provider``).
        severity: 'error' or 'warning'.
    """

    message: str
    path: str = ""
    severity: str = "error"


@dataclass
class StudioValidationResult:
    """Aggregated validation result.

    Attributes:
        errors: Blocking issues that prevent deployment.
        warnings: Non-blocking issues to be aware of.
    """

    errors: list[ValidationMessage] = field(default_factory=list)
    warnings: list[ValidationMessage] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if there are no errors (warnings are OK)."""
        return len(self.errors) == 0

    def add_error(self, message: str, path: str = "") -> None:
        """Add a blocking error."""
        self.errors.append(ValidationMessage(message=message, path=path, severity="error"))

    def add_warning(self, message: str, path: str = "") -> None:
        """Add a non-blocking warning."""
        self.warnings.append(ValidationMessage(message=message, path=path, severity="warning"))

    def merge(self, other: StudioValidationResult) -> None:
        """Merge another result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


def _validate_agents(team: TeamSpec, result: StudioValidationResult) -> None:
    """Check agent definitions for structural issues."""
    if not team.agents:
        result.add_warning("No agents defined", "agents")
        return

    agent_ids: set[str] = set()
    phase_ids = {p.id for p in team.workflow.phases}

    for i, agent in enumerate(team.agents):
        prefix = f"agents[{i}]"

        if not agent.id:
            result.add_error("Agent ID is required", f"{prefix}.id")
            continue

        if agent.id in agent_ids:
            result.add_error(f"Duplicate agent ID: '{agent.id}'", f"{prefix}.id")
        agent_ids.add(agent.id)

        if not agent.name:
            result.add_error("Agent name is required", f"{prefix}.name")

        if not agent.system_prompt.strip():
            result.add_warning("Agent has no system prompt", f"{prefix}.system_prompt")

        if not agent.phases:
            result.add_warning(
                f"Agent '{agent.id}' not assigned to any phase", f"{prefix}.phases"
            )

        for phase_id in agent.phases:
            if phase_ids and phase_id not in phase_ids:
                result.add_error(
                    f"Agent '{agent.id}' references unknown phase '{phase_id}'",
                    f"{prefix}.phases",
                )

        if not agent.llm.provider:
            result.add_error("LLM provider is required", f"{prefix}.llm.provider")
        if not agent.llm.model:
            result.add_error("LLM model is required", f"{prefix}.llm.model")
        if not 0.0 <= agent.llm.temperature <= 2.0:
            result.add_error(
                f"Temperature must be 0.0–2.0, got {agent.llm.temperature}",
                f"{prefix}.llm.temperature",
            )
        if not 1 <= agent.llm.max_tokens <= 200_000:
            result.add_error(
                f"max_tokens must be 1–200000, got {agent.llm.max_tokens}",
                f"{prefix}.llm.max_tokens",
            )


def _validate_workflow(team: TeamSpec, result: StudioValidationResult) -> None:
    """Check workflow phases and statuses for structural issues."""
    wf = team.workflow
    agent_ids = {a.id for a in team.agents}
    phase_ids = {p.id for p in wf.phases}

    # Statuses
    initial_count = sum(1 for s in wf.statuses if s.is_initial)
    terminal_count = sum(1 for s in wf.statuses if s.is_terminal)
    status_ids = {s.id for s in wf.statuses}

    if wf.statuses:
        if initial_count == 0:
            result.add_error("No initial status defined", "workflow.statuses")
        elif initial_count > 1:
            result.add_error("Multiple initial statuses defined", "workflow.statuses")
        if terminal_count == 0:
            result.add_error("No terminal status defined", "workflow.statuses")

        for i, status in enumerate(wf.statuses):
            for target in status.transitions_to:
                if target not in status_ids:
                    result.add_error(
                        f"Status '{status.id}' transitions to unknown status '{target}'",
                        f"workflow.statuses[{i}].transitions_to",
                    )

    # Phases
    if not wf.phases:
        result.add_warning("No workflow phases defined", "workflow.phases")
        return

    terminal_phases = [p for p in wf.phases if p.is_terminal]
    if not terminal_phases:
        result.add_error("No terminal phase defined", "workflow.phases")

    for i, phase in enumerate(wf.phases):
        prefix = f"workflow.phases[{i}]"

        if not phase.id:
            result.add_error("Phase ID is required", f"{prefix}.id")
            continue

        for agent_id in phase.agents:
            if agent_ids and agent_id not in agent_ids:
                result.add_error(
                    f"Phase '{phase.id}' references unknown agent '{agent_id}'",
                    f"{prefix}.agents",
                )

        if phase.on_success and phase.on_success not in phase_ids:
            result.add_error(
                f"Phase '{phase.id}' on_success references unknown phase '{phase.on_success}'",
                f"{prefix}.on_success",
            )
        if phase.on_failure and phase.on_failure not in phase_ids:
            result.add_error(
                f"Phase '{phase.id}' on_failure references unknown phase '{phase.on_failure}'",
                f"{prefix}.on_failure",
            )

        if not phase.is_terminal and not phase.on_success and not phase.on_failure:
            result.add_warning(
                f"Non-terminal phase '{phase.id}' has no transitions",
                f"{prefix}",
            )


def _validate_governance(team: TeamSpec, result: StudioValidationResult) -> None:
    """Check governance configuration for structural issues."""
    gov = team.governance
    da = gov.delegated_authority

    if da.auto_approve_threshold <= da.review_threshold:
        result.add_error(
            "auto_approve_threshold must be greater than review_threshold",
            "governance.delegated_authority",
        )
    if da.review_threshold <= da.abort_threshold:
        result.add_error(
            "review_threshold must be greater than abort_threshold",
            "governance.delegated_authority",
        )

    valid_actions = {"allow", "deny", "review", "warn", "escalate"}
    policy_ids: set[str] = set()
    for i, policy in enumerate(gov.policies):
        prefix = f"governance.policies[{i}]"

        if not policy.id:
            result.add_error("Policy ID is required", f"{prefix}.id")
            continue

        if policy.id in policy_ids:
            result.add_error(f"Duplicate policy ID: '{policy.id}'", f"{prefix}.id")
        policy_ids.add(policy.id)

        if policy.action not in valid_actions:
            result.add_error(
                f"Invalid policy action '{policy.action}', must be one of {valid_actions}",
                f"{prefix}.action",
            )


def _validate_work_items(team: TeamSpec, result: StudioValidationResult) -> None:
    """Check work-item types for structural issues."""
    wit_ids: set[str] = set()
    for i, wit in enumerate(team.work_item_types):
        prefix = f"work_item_types[{i}]"

        if not wit.id:
            result.add_error("Work item type ID is required", f"{prefix}.id")
            continue

        if wit.id in wit_ids:
            result.add_error(f"Duplicate work item type ID: '{wit.id}'", f"{prefix}.id")
        wit_ids.add(wit.id)

        field_names: set[str] = set()
        for j, fld in enumerate(wit.custom_fields):
            fprefix = f"{prefix}.custom_fields[{j}]"
            if not fld.name:
                result.add_error("Field name is required", fprefix)
                continue
            if fld.name in field_names:
                result.add_error(
                    f"Duplicate field name '{fld.name}' in work item type '{wit.id}'",
                    fprefix,
                )
            field_names.add(fld.name)

            if fld.type == "enum" and not fld.values:
                result.add_error(
                    f"Enum field '{fld.name}' must have values defined",
                    f"{fprefix}.values",
                )


def _validate_capability_coverage(team: TeamSpec, result: StudioValidationResult) -> None:
    """Check that phase required_capabilities are covered by assigned agents."""
    # Build agent_id -> set of skills
    agent_skills_map: dict[str, set[str]] = {
        agent.id: set(agent.skills) for agent in team.agents
    }

    # Collect all capabilities referenced by any phase
    all_required_capabilities: set[str] = set()
    for phase in team.workflow.phases:
        all_required_capabilities.update(phase.required_capabilities)

    # Check each phase's required capabilities are covered
    for i, phase in enumerate(team.workflow.phases):
        prefix = f"workflow.phases[{i}]"

        if phase.is_terminal:
            continue

        if not phase.agents and not phase.skippable:
            result.add_warning(
                f"Phase '{phase.id}' has no agents assigned",
                f"{prefix}.agents",
            )

        if phase.required_capabilities and not phase.skippable:
            # Collect all skills from agents assigned to this phase
            covered_skills: set[str] = set()
            for agent_id in phase.agents:
                covered_skills.update(agent_skills_map.get(agent_id, set()))

            missing = set(phase.required_capabilities) - covered_skills
            for cap in sorted(missing):
                result.add_error(
                    f"Phase '{phase.id}' requires capability '{cap}' "
                    f"but no assigned agent provides it",
                    f"{prefix}.required_capabilities",
                )

    # Check for agents with skills not referenced by any phase
    for i, agent in enumerate(team.agents):
        unused_skills = set(agent.skills) - all_required_capabilities
        for skill in sorted(unused_skills):
            result.add_warning(
                f"Agent '{agent.id}' has skill '{skill}' not referenced "
                f"by any phase's required_capabilities",
                f"agents[{i}].skills",
            )


def validate_team(team: TeamSpec) -> StudioValidationResult:
    """Run all Studio-side structural validations on a TeamSpec.

    This is fast and doesn't require the runtime to be installed.

    Args:
        team: The team specification to validate.

    Returns:
        StudioValidationResult with all errors and warnings.
    """
    result = StudioValidationResult()

    if not team.name:
        result.add_error("Team name is required", "name")

    _validate_agents(team, result)
    _validate_workflow(team, result)
    _validate_governance(team, result)
    _validate_work_items(team, result)
    _validate_capability_coverage(team, result)

    logger.info(
        "Validation complete: %d errors, %d warnings",
        len(result.errors),
        len(result.warnings),
    )
    return result


def validate_team_via_runtime(team: TeamSpec) -> StudioValidationResult:
    """Validate by converting to ProfileConfig and calling the runtime validator.

    This gives the most thorough validation including cross-reference checks,
    phase graph reachability, and LLM provider verification.

    Falls back to Studio-side validation if the runtime is not installed.

    Args:
        team: The team specification to validate.

    Returns:
        StudioValidationResult with errors and warnings from both
        Studio-side and runtime validation.
    """
    # Always run Studio-side validation first
    result = validate_team(team)

    try:
        from agent_orchestrator.configuration.models import ProfileConfig
        from agent_orchestrator.configuration.validator import validate_profile
        from studio.conversion.converter import ir_to_profile_dict
    except ImportError:
        result.add_warning(
            "Runtime not installed — only Studio-side validation was performed",
            "",
        )
        return result

    # Convert IR → ProfileConfig
    try:
        profile_dict = ir_to_profile_dict(team)
        profile = ProfileConfig(**profile_dict)
    except Exception as exc:
        result.add_error(f"Failed to create ProfileConfig: {exc}", "")
        return result

    # Run runtime validation
    try:
        runtime_result = validate_profile(profile)
        for error in runtime_result.errors:
            result.add_error(f"[runtime] {error}", "")
        for warning in runtime_result.warnings:
            result.add_warning(f"[runtime] {warning}", "")
    except Exception as exc:
        result.add_error(f"Runtime validation failed: {exc}", "")

    logger.info(
        "Runtime validation complete: %d errors, %d warnings",
        len(result.errors),
        len(result.warnings),
    )
    return result
