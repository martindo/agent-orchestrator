"""Studio IR (Intermediate Representation) models.

Each *Spec model maps 1-to-1 with a runtime Pydantic model in
``agent_orchestrator.configuration.models``.  Studio editors work with
these IR objects; the conversion layer translates to/from runtime models
for validation and YAML generation.

Design decisions
~~~~~~~~~~~~~~~~
* All models are Pydantic ``BaseModel`` with ``frozen=True`` so they are
  immutable and hashable — safe to pass between threads.
* Field names intentionally mirror the runtime model field names so the
  conversion layer is a straightforward mapping.
* Extra fields that only Studio cares about (e.g. ``_ui_position``) are
  kept in a separate dict so they never leak into generated YAML.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums (mirror runtime enums)
# ---------------------------------------------------------------------------

class FieldType(str, Enum):
    """Work-item field data types (mirrors runtime FieldType)."""

    TEXT = "text"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    ENUM = "enum"
    BOOLEAN = "boolean"


class OnFailureAction(str, Enum):
    """What a quality gate does when its conditions are not met."""

    BLOCK = "block"
    WARN = "warn"
    SKIP = "skip"


# ---------------------------------------------------------------------------
# Low-level value objects
# ---------------------------------------------------------------------------

class LLMSpec(BaseModel, frozen=True):
    """LLM provider configuration for an agent.

    Attributes:
        provider: LLM provider key (openai, anthropic, google, ollama, grok, custom).
        model: Model identifier within the provider.
        temperature: Sampling temperature (0.0–2.0).
        max_tokens: Maximum tokens in the response (1–200 000).
        endpoint: Optional override URL for self-hosted models.
    """

    provider: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 4000
    endpoint: str | None = None


class RetryPolicySpec(BaseModel, frozen=True):
    """Retry behaviour attached to an agent.

    Attributes:
        max_retries: How many times to retry a failed LLM call.
        delay_seconds: Initial delay between retries.
        backoff_multiplier: Multiplier applied to the delay after each retry.
    """

    max_retries: int = 3
    delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0


class ConditionSpec(BaseModel, frozen=True):
    """A single boolean condition expression.

    Attributes:
        expression: Free-form expression like ``confidence >= 0.8``.
        description: Human-readable explanation of the condition.
    """

    expression: str
    description: str = ""


class TransitionSpec(BaseModel, frozen=True):
    """Explicit directed edge in the workflow phase graph.

    Attributes:
        from_phase: Source phase ID.
        to_phase: Target phase ID.
        trigger: Whether the edge fires on success or failure of the source.
    """

    from_phase: str
    to_phase: str
    trigger: str = "on_success"


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class AgentSpec(BaseModel, frozen=True):
    """One agent in the team.

    Attributes:
        id: Unique agent identifier (slug-style).
        name: Human-readable display name.
        description: What this agent does.
        system_prompt: The system prompt sent to the LLM.
        skills: Tags describing agent capabilities.
        phases: Workflow phase IDs this agent participates in.
        llm: LLM provider and model configuration.
        concurrency: Max parallel invocations (1–100).
        retry_policy: Retry behaviour for failed calls.
        enabled: Whether the agent is active.
    """

    id: str
    name: str
    description: str = ""
    system_prompt: str = ""
    skills: list[str] = Field(default_factory=list)
    phases: list[str] = Field(default_factory=list)
    llm: LLMSpec = Field(default_factory=lambda: LLMSpec(provider="openai", model="gpt-4o"))
    concurrency: int = 1
    retry_policy: RetryPolicySpec = Field(default_factory=RetryPolicySpec)
    enabled: bool = True


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

class QualityGateSpec(BaseModel, frozen=True):
    """A quality gate that guards phase completion.

    Attributes:
        name: Gate identifier.
        description: Human-readable explanation.
        conditions: List of conditions that must all pass.
        on_failure: Action when any condition fails (block | warn | skip).
    """

    name: str
    description: str = ""
    conditions: list[ConditionSpec] = Field(default_factory=list)
    on_failure: OnFailureAction = OnFailureAction.BLOCK


class StatusSpec(BaseModel, frozen=True):
    """One status in the work-item lifecycle.

    Attributes:
        id: Unique status slug.
        name: Display name.
        description: What this status means.
        is_initial: True if this is the starting status.
        is_terminal: True if work items in this status are done.
        transitions_to: Status IDs reachable from this status.
    """

    id: str
    name: str
    description: str = ""
    is_initial: bool = False
    is_terminal: bool = False
    transitions_to: list[str] = Field(default_factory=list)


class PhaseSpec(BaseModel, frozen=True):
    """One phase in the workflow pipeline.

    Attributes:
        id: Unique phase slug.
        name: Display name.
        description: What happens in this phase.
        order: Numeric ordering (1-based).
        agents: Agent IDs that execute in this phase.
        parallel: Whether agents run in parallel within the phase.
        entry_conditions: Conditions that must pass to enter the phase.
        exit_conditions: Conditions that must pass to leave the phase.
        quality_gates: Gates evaluated after agent execution.
        critic_agent: Optional agent ID that evaluates phase output.
        critic_rubric: Evaluation rubric for the critic agent.
        max_phase_retries: How many times to retry the whole phase.
        retry_backoff_seconds: Delay between phase retries.
        on_success: Phase ID to transition to on success.
        on_failure: Phase ID to transition to on failure.
        skippable: Whether the phase can be skipped.
        skip: Runtime toggle — skip this phase.
        is_terminal: True if this is a terminal (sink) phase.
        requires_human: True if human approval is needed.
        required_capabilities: Skills/capabilities agents must provide for this phase.
        expected_output_fields: Field names the phase is expected to produce.
    """

    id: str
    name: str
    description: str = ""
    order: int = 0
    agents: list[str] = Field(default_factory=list)
    parallel: bool = False
    entry_conditions: list[ConditionSpec] = Field(default_factory=list)
    exit_conditions: list[ConditionSpec] = Field(default_factory=list)
    quality_gates: list[QualityGateSpec] = Field(default_factory=list)
    critic_agent: str | None = None
    critic_rubric: str = ""
    max_phase_retries: int = 1
    retry_backoff_seconds: float = 1.0
    on_success: str = ""
    on_failure: str = ""
    skippable: bool = False
    skip: bool = False
    is_terminal: bool = False
    requires_human: bool = False
    required_capabilities: list[str] = Field(default_factory=list)
    expected_output_fields: list[str] = Field(default_factory=list)


class WorkflowSpec(BaseModel, frozen=True):
    """Complete workflow definition.

    Attributes:
        name: Workflow display name.
        description: What this workflow accomplishes.
        statuses: Status lifecycle definitions.
        phases: Ordered pipeline of phases.
    """

    name: str = "default"
    description: str = ""
    statuses: list[StatusSpec] = Field(default_factory=list)
    phases: list[PhaseSpec] = Field(default_factory=list)

    @property
    def transitions(self) -> list[TransitionSpec]:
        """Derive explicit transitions from phase on_success/on_failure."""
        result: list[TransitionSpec] = []
        for phase in self.phases:
            if phase.on_success:
                result.append(
                    TransitionSpec(
                        from_phase=phase.id,
                        to_phase=phase.on_success,
                        trigger="on_success",
                    )
                )
            if phase.on_failure and phase.on_failure != phase.on_success:
                result.append(
                    TransitionSpec(
                        from_phase=phase.id,
                        to_phase=phase.on_failure,
                        trigger="on_failure",
                    )
                )
        return result


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------

class DelegatedAuthoritySpec(BaseModel, frozen=True):
    """Confidence thresholds for automatic governance decisions.

    Attributes:
        auto_approve_threshold: Confidence above which work is auto-approved.
        review_threshold: Confidence below which work goes to human review.
        abort_threshold: Confidence below which work is aborted.
        work_type_overrides: Per-work-type threshold overrides.
    """

    auto_approve_threshold: float = 0.8
    review_threshold: float = 0.5
    abort_threshold: float = 0.2
    work_type_overrides: dict[str, dict[str, float]] = Field(default_factory=dict)


class PolicySpec(BaseModel, frozen=True):
    """A governance policy rule.

    Attributes:
        id: Unique policy slug.
        name: Display name.
        description: What this policy enforces.
        scope: Policy scope (global or a specific context).
        action: What happens when conditions match (allow, deny, review, warn, escalate).
        conditions: Expression strings that must all be true to trigger.
        priority: Higher-priority policies are evaluated first.
        enabled: Whether the policy is active.
        tags: Metadata tags for categorisation.
    """

    id: str
    name: str
    description: str = ""
    scope: str = "global"
    action: str = "allow"
    conditions: list[str] = Field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


class GovernanceSpec(BaseModel, frozen=True):
    """Governance configuration for the team.

    Attributes:
        delegated_authority: Automatic decision thresholds.
        policies: Ordered list of governance policies.
    """

    delegated_authority: DelegatedAuthoritySpec = Field(
        default_factory=DelegatedAuthoritySpec
    )
    policies: list[PolicySpec] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Work items
# ---------------------------------------------------------------------------

class WorkItemFieldSpec(BaseModel, frozen=True):
    """A custom field on a work-item type.

    Attributes:
        name: Field name (slug-style).
        type: Data type.
        required: Whether the field must be provided.
        default: Default value (None means no default).
        values: Allowed enum values (only for FieldType.ENUM).
    """

    name: str
    type: FieldType = FieldType.STRING
    required: bool = False
    default: Any = None
    values: list[str] | None = None


class ArtifactTypeSpec(BaseModel, frozen=True):
    """Artifact type definition attached to a work-item type.

    Attributes:
        id: Artifact type slug.
        name: Display name.
        description: What this artifact represents.
        file_extensions: Accepted file extensions (e.g. ``.json``, ``.md``).
    """

    id: str
    name: str
    description: str = ""
    file_extensions: list[str] = Field(default_factory=list)


class WorkItemTypeSpec(BaseModel, frozen=True):
    """A type of work item the team processes.

    Attributes:
        id: Work-item type slug.
        name: Display name.
        description: What this work-item type represents.
        custom_fields: Additional typed fields beyond the base work-item.
        artifact_types: Artifacts that can be attached.
    """

    id: str
    name: str
    description: str = ""
    custom_fields: list[WorkItemFieldSpec] = Field(default_factory=list)
    artifact_types: list[ArtifactTypeSpec] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# App manifest (optional)
# ---------------------------------------------------------------------------

class AppManifestSpec(BaseModel, frozen=True):
    """Optional application manifest for a profile.

    Attributes:
        name: Application display name.
        version: Semantic version string.
        description: Application description.
        platform_version: Minimum runtime version required.
        requires: Capability requirements (e.g. ``{"connectors": ["slack"]}``).
        produces: Output declarations.
        hooks: Phase-to-function mappings (e.g. ``{"analysis": "hooks:pre_analysis"}``).
        author: Author name or email.
    """

    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    platform_version: str = ""
    requires: dict[str, list[str]] = Field(default_factory=dict)
    produces: dict[str, list[str]] = Field(default_factory=dict)
    hooks: dict[str, str] = Field(default_factory=dict)
    author: str = ""


# ---------------------------------------------------------------------------
# Top-level team
# ---------------------------------------------------------------------------

class TeamSpec(BaseModel, frozen=True):
    """Root IR model — a complete agent team profile.

    This is the single object that Studio editors read and write.
    It contains every piece of configuration needed to generate a
    full runtime profile directory.

    Attributes:
        name: Team / profile display name.
        description: What this team does.
        agents: Agent definitions.
        workflow: Workflow pipeline definition.
        governance: Governance rules and policies.
        work_item_types: Domain-specific work-item types.
        manifest: Optional application manifest.
    """

    name: str
    description: str = ""
    agents: list[AgentSpec] = Field(default_factory=list)
    workflow: WorkflowSpec = Field(default_factory=WorkflowSpec)
    governance: GovernanceSpec = Field(default_factory=GovernanceSpec)
    work_item_types: list[WorkItemTypeSpec] = Field(default_factory=list)
    manifest: AppManifestSpec | None = None
