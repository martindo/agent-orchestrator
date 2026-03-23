"""Configuration validator — cross-reference and structural validation.

Validates relationships between config elements that Pydantic can't check:
- Agents referenced in phases must exist
- Phase graph has no orphans and terminal phases are reachable
- LLM providers have API keys configured
- Status transitions reference valid statuses

Thread-safe: All functions are pure (no shared mutable state).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agent_orchestrator.configuration.models import (
    GovernanceConfig,
    ProfileConfig,
    SettingsConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of configuration validation.

    Collects errors and warnings separately for flexible handling.
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if no errors were found."""
        return len(self.errors) == 0

    def add_error(self, message: str) -> None:
        """Add a validation error."""
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        """Add a validation warning."""
        self.warnings.append(message)

    def merge(self, other: ValidationResult) -> None:
        """Merge another result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


def validate_agent_phase_references(profile: ProfileConfig) -> ValidationResult:
    """Validate that agents reference existing workflow phases.

    Args:
        profile: Profile configuration to validate.

    Returns:
        ValidationResult with any errors found.
    """
    result = ValidationResult()
    phase_ids = {p.id for p in profile.workflow.phases}
    agent_ids = {a.id for a in profile.agents}

    for agent in profile.agents:
        for phase_id in agent.phases:
            if phase_id not in phase_ids:
                result.add_error(
                    f"Agent '{agent.id}' references unknown phase '{phase_id}'. "
                    f"Available phases: {sorted(phase_ids)}"
                )

    # Validate phases reference existing agents
    for phase in profile.workflow.phases:
        for agent_id in phase.agents:
            if agent_id not in agent_ids:
                result.add_error(
                    f"Phase '{phase.id}' references unknown agent '{agent_id}'. "
                    f"Available agents: {sorted(agent_ids)}"
                )

    return result


def validate_phase_graph(workflow: WorkflowConfig) -> ValidationResult:
    """Validate the phase graph structure.

    Checks:
    - No orphan phases (unreachable from any other phase)
    - Terminal phases are reachable from the first phase
    - on_success/on_failure reference existing phases
    - At least one terminal phase exists

    Args:
        workflow: Workflow configuration to validate.

    Returns:
        ValidationResult with any errors found.
    """
    result = ValidationResult()

    if not workflow.phases:
        result.add_warning("Workflow has no phases defined")
        return result

    phase_ids = {p.id for p in workflow.phases}
    terminal_phases = {p.id for p in workflow.phases if p.is_terminal}

    if not terminal_phases:
        result.add_error("Workflow must have at least one terminal phase")

    # Validate on_success/on_failure references
    for phase in workflow.phases:
        if phase.on_success and phase.on_success not in phase_ids:
            result.add_error(
                f"Phase '{phase.id}' on_success references unknown phase '{phase.on_success}'"
            )
        if phase.on_failure and phase.on_failure not in phase_ids:
            result.add_error(
                f"Phase '{phase.id}' on_failure references unknown phase '{phase.on_failure}'"
            )

    # Check reachability from first phase
    if len(workflow.phases) > 1:
        reachable = _find_reachable_phases(workflow)
        unreachable = phase_ids - reachable
        for phase_id in sorted(unreachable):
            result.add_warning(
                f"Phase '{phase_id}' is unreachable from the initial phase"
            )

    # Check terminal phases are reachable
    reachable = _find_reachable_phases(workflow)
    reachable_terminals = terminal_phases & reachable
    if terminal_phases and not reachable_terminals:
        result.add_error("No terminal phase is reachable from the initial phase")

    return result


def _find_reachable_phases(workflow: WorkflowConfig) -> set[str]:
    """Find all phases reachable from the first phase via BFS."""
    if not workflow.phases:
        return set()

    # Build adjacency from on_success/on_failure
    adjacency: dict[str, set[str]] = {}
    for phase in workflow.phases:
        neighbors: set[str] = set()
        if phase.on_success:
            neighbors.add(phase.on_success)
        if phase.on_failure:
            neighbors.add(phase.on_failure)
        adjacency[phase.id] = neighbors

    # BFS from first phase
    start = workflow.phases[0].id
    visited: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                queue.append(neighbor)

    return visited


def validate_llm_providers(
    profile: ProfileConfig,
    settings: SettingsConfig,
) -> ValidationResult:
    """Validate that agent LLM providers have API keys configured.

    Agents using 'ollama' or 'custom' providers with explicit endpoints
    don't need API keys.

    Args:
        profile: Profile with agent definitions.
        settings: Workspace settings with API keys.

    Returns:
        ValidationResult with any errors found.
    """
    result = ValidationResult()
    keyless_providers = {"ollama"}

    for agent in profile.agents:
        if not agent.enabled:
            continue
        provider = agent.llm.provider
        has_key = provider in settings.api_keys
        has_endpoint = agent.llm.endpoint is not None
        is_keyless = provider in keyless_providers

        if not has_key and not has_endpoint and not is_keyless:
            endpoint_from_settings = provider in settings.llm_endpoints
            if not endpoint_from_settings:
                result.add_error(
                    f"Agent '{agent.id}' uses provider '{provider}' but no API key "
                    f"is configured in settings.api_keys and no endpoint is specified. "
                    f"Configured providers: {sorted(settings.api_keys.keys())}"
                )

    return result


def validate_status_transitions(workflow: WorkflowConfig) -> ValidationResult:
    """Validate that status transitions reference valid statuses.

    Args:
        workflow: Workflow configuration to validate.

    Returns:
        ValidationResult with any errors found.
    """
    result = ValidationResult()

    if not workflow.statuses:
        return result

    status_ids = {s.id for s in workflow.statuses}
    initial_count = sum(1 for s in workflow.statuses if s.is_initial)
    terminal_count = sum(1 for s in workflow.statuses if s.is_terminal)

    if initial_count == 0:
        result.add_error("Workflow statuses must include at least one initial status")
    if initial_count > 1:
        result.add_warning("Multiple initial statuses defined; only one should be initial")
    if terminal_count == 0:
        result.add_error("Workflow statuses must include at least one terminal status")

    for status in workflow.statuses:
        for target_id in status.transitions_to:
            if target_id not in status_ids:
                result.add_error(
                    f"Status '{status.id}' transitions to unknown status '{target_id}'"
                )

    return result


def validate_governance(governance: GovernanceConfig) -> ValidationResult:
    """Validate governance configuration.

    Args:
        governance: Governance configuration to validate.

    Returns:
        ValidationResult with any errors found.
    """
    result = ValidationResult()
    da = governance.delegated_authority

    if da.auto_approve_threshold <= da.review_threshold:
        result.add_warning(
            f"auto_approve_threshold ({da.auto_approve_threshold}) should be "
            f"greater than review_threshold ({da.review_threshold})"
        )
    if da.review_threshold <= da.abort_threshold:
        result.add_warning(
            f"review_threshold ({da.review_threshold}) should be "
            f"greater than abort_threshold ({da.abort_threshold})"
        )

    valid_actions = {"allow", "deny", "review", "warn", "escalate"}
    for policy in governance.policies:
        if policy.action not in valid_actions:
            result.add_error(
                f"Policy '{policy.id}' has invalid action '{policy.action}'. "
                f"Must be one of {sorted(valid_actions)}"
            )

    return result


def validate_capability_coverage(profile: ProfileConfig) -> ValidationResult:
    """Validate that phase capability requirements are covered by assigned agents.

    Checks:
    - Phases with required_capabilities have agents with matching skills
    - Quality gate conditions reference fields covered by expected_output_fields
    - Non-terminal phases have at least one agent
    - Agents with skills not referenced by any phase (info-level)

    Args:
        profile: Profile configuration to validate.

    Returns:
        ValidationResult with capability gap findings.
    """
    result = ValidationResult()
    agent_map = {a.id: a for a in profile.agents if a.enabled}
    all_required: set[str] = set()

    for phase in profile.workflow.phases:
        if phase.is_terminal or phase.skip:
            continue

        # Collect skills from assigned agents
        phase_skills: set[str] = set()
        for agent_id in phase.agents:
            agent = agent_map.get(agent_id)
            if agent is not None:
                phase_skills.update(agent.skills)

        # Check required capabilities
        if phase.required_capabilities:
            all_required.update(phase.required_capabilities)
            missing = set(phase.required_capabilities) - phase_skills
            if missing:
                result.add_warning(
                    f"Phase '{phase.id}' requires capabilities {sorted(missing)} "
                    f"but no assigned agent provides them. "
                    f"Available skills: {sorted(phase_skills)}"
                )

        # Check expected output fields against quality gate conditions
        gate_fields = _extract_gate_fields(phase)
        if gate_fields and phase.expected_output_fields:
            unmatched = gate_fields - set(phase.expected_output_fields)
            if unmatched:
                result.add_warning(
                    f"Phase '{phase.id}' quality gates reference fields "
                    f"{sorted(unmatched)} not listed in expected_output_fields"
                )

        # Empty phase check
        if not phase.agents and not phase.skippable:
            result.add_warning(
                f"Phase '{phase.id}' has no agents assigned and is not skippable"
            )

    # Skill orphan check (info-level)
    all_agent_skills: set[str] = set()
    for agent in profile.agents:
        if agent.enabled:
            all_agent_skills.update(agent.skills)
    orphan_skills = all_agent_skills - all_required
    if orphan_skills and all_required:
        result.add_warning(
            f"Agent skills {sorted(orphan_skills)} are not referenced by "
            f"any phase's required_capabilities (may be unused)"
        )

    return result


def _extract_gate_fields(phase: "WorkflowPhaseConfig") -> set[str]:
    """Extract field names referenced in quality gate condition expressions."""
    import re
    fields: set[str] = set()
    for gate in phase.quality_gates:
        for condition in gate.conditions:
            # Match identifiers before comparison operators
            matches = re.findall(r"([a-zA-Z_]\w*)\s*[><=!]", condition.expression)
            fields.update(matches)
    return fields


def validate_profile(
    profile: ProfileConfig,
    settings: SettingsConfig | None = None,
) -> ValidationResult:
    """Run all validations on a profile.

    Args:
        profile: Profile to validate.
        settings: Optional settings for LLM provider validation.

    Returns:
        Combined ValidationResult from all checks.
    """
    result = ValidationResult()

    result.merge(validate_agent_phase_references(profile))
    result.merge(validate_phase_graph(profile.workflow))
    result.merge(validate_status_transitions(profile.workflow))
    result.merge(validate_governance(profile.governance))
    result.merge(validate_capability_coverage(profile))

    if settings is not None:
        result.merge(validate_llm_providers(profile, settings))

    if result.is_valid:
        logger.info("Profile '%s' validation passed", profile.name)
    else:
        logger.warning(
            "Profile '%s' validation failed with %d error(s)",
            profile.name,
            len(result.errors),
        )

    for warning in result.warnings:
        logger.warning("Validation warning: %s", warning)

    return result
