"""Pydantic v2 configuration models for all user-defined configuration.

All domain knowledge is expressed through these models — the application
itself contains zero hardcoded agent names, phase names, or work item types.

Thread-safe: Models are immutable (frozen) after creation.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# ---- Named Constants ----

DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4000
DEFAULT_CONCURRENCY = 1
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0
DEFAULT_RETRY_BACKOFF_MULTIPLIER = 2.0
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_PERSISTENCE_BACKEND = "file"
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0
MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 200_000
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 100


class FieldType(str, Enum):
    """Supported field types for custom work item fields."""

    TEXT = "text"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    ENUM = "enum"
    BOOLEAN = "boolean"


class PersistenceBackend(str, Enum):
    """Supported persistence backends."""

    FILE = "file"
    SQLITE = "sqlite"


# ---- System Settings (workspace-level, shared across profiles) ----


class SettingsConfig(BaseModel):
    """Workspace-level settings shared across all profiles.

    API keys are stored here centrally — agents reference them by provider name.
    """

    model_config = {"frozen": True}

    active_profile: str = Field(description="Which profile is currently loaded")
    api_keys: dict[str, str] = Field(
        default_factory=dict,
        description="Provider -> API key mapping (openai, anthropic, grok, etc.)",
    )
    llm_endpoints: dict[str, str] = Field(
        default_factory=dict,
        description="Custom LLM endpoints (e.g., ollama: http://localhost:11434)",
    )
    log_level: str = DEFAULT_LOG_LEVEL
    persistence_backend: str = DEFAULT_PERSISTENCE_BACKEND

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            msg = f"Invalid log level '{v}', must be one of {valid_levels}"
            raise ValueError(msg)
        return upper

    @field_validator("persistence_backend")
    @classmethod
    def _validate_backend(cls, v: str) -> str:
        valid = {b.value for b in PersistenceBackend}
        if v not in valid:
            msg = f"Invalid persistence backend '{v}', must be one of {valid}"
            raise ValueError(msg)
        return v


# ---- Per-Agent LLM Config ----


class LLMConfig(BaseModel):
    """Per-agent LLM provider and model selection.

    References api_keys in SettingsConfig by provider name.
    Endpoint can override for self-hosted LLMs (Ollama, vLLM, etc.).
    """

    model_config = {"frozen": True}

    provider: str = Field(description="LLM provider (openai, anthropic, google, ollama, grok, custom)")
    model: str = Field(description="Model identifier (gpt-4o, claude-sonnet-4-20250514, llama3, etc.)")
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    endpoint: str | None = Field(
        default=None,
        description="Override endpoint for self-hosted (e.g., http://my-ollama:11434)",
    )

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, v: float) -> float:
        if not MIN_TEMPERATURE <= v <= MAX_TEMPERATURE:
            msg = f"Temperature must be between {MIN_TEMPERATURE} and {MAX_TEMPERATURE}, got {v}"
            raise ValueError(msg)
        return v

    @field_validator("max_tokens")
    @classmethod
    def _validate_max_tokens(cls, v: int) -> int:
        if not MIN_MAX_TOKENS <= v <= MAX_MAX_TOKENS:
            msg = f"max_tokens must be between {MIN_MAX_TOKENS} and {MAX_MAX_TOKENS}, got {v}"
            raise ValueError(msg)
        return v


# ---- Retry Policy ----


class RetryPolicy(BaseModel):
    """Retry configuration for agent execution failures."""

    model_config = {"frozen": True}

    max_retries: int = DEFAULT_MAX_RETRIES
    delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS
    backoff_multiplier: float = DEFAULT_RETRY_BACKOFF_MULTIPLIER


# ---- Condition & Quality Gate ----


class ConditionConfig(BaseModel):
    """A condition expression evaluated at phase boundaries.

    Expressions are string-based and evaluated at runtime.
    Example: "confidence >= 0.8", "risk_level == 'low'"
    """

    model_config = {"frozen": True}

    expression: str = Field(description="Condition expression (e.g., 'confidence >= 0.8')")
    description: str = ""


class QualityGateConfig(BaseModel):
    """Quality gate evaluated after phase completion.

    All conditions must pass for the gate to pass.
    """

    model_config = {"frozen": True}

    name: str
    description: str = ""
    conditions: list[ConditionConfig] = Field(default_factory=list)
    on_failure: str = Field(
        default="block",
        description="Action on failure: 'block', 'warn', 'skip'",
    )


# ---- Agent Definition (per-profile) ----


class AgentDefinition(BaseModel):
    """Definition of an agent within a profile.

    Each agent has its own LLM config, system prompt, and
    is assigned to specific workflow phases.
    """

    model_config = {"frozen": True}

    id: str = Field(description="Unique identifier within the profile")
    name: str = Field(description="Human-readable display name")
    description: str = ""
    system_prompt: str = Field(description="The agent's instruction prompt")
    skills: list[str] = Field(default_factory=list, description="Capability tags")
    phases: list[str] = Field(description="Workflow phase IDs this agent runs in")
    llm: LLMConfig = Field(description="Per-agent LLM provider/model selection")
    concurrency: int = DEFAULT_CONCURRENCY
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    enabled: bool = True

    @field_validator("concurrency")
    @classmethod
    def _validate_concurrency(cls, v: int) -> int:
        if not MIN_CONCURRENCY <= v <= MAX_CONCURRENCY:
            msg = f"Concurrency must be between {MIN_CONCURRENCY} and {MAX_CONCURRENCY}, got {v}"
            raise ValueError(msg)
        return v


# ---- Status Lifecycle ----


class StatusConfig(BaseModel):
    """A status in the work item lifecycle."""

    model_config = {"frozen": True}

    id: str
    name: str
    description: str = ""
    is_initial: bool = False
    is_terminal: bool = False
    transitions_to: list[str] = Field(
        default_factory=list,
        description="Status IDs this status can transition to",
    )


# ---- Workflow Phase ----


class WorkflowPhaseConfig(BaseModel):
    """A phase in the workflow pipeline.

    Phases form a directed graph via on_success/on_failure links.
    """

    model_config = {"frozen": True}

    id: str
    name: str
    description: str = ""
    order: int = Field(description="Execution order (for linear display)")
    agents: list[str] = Field(
        default_factory=list,
        description="Agent IDs that run in this phase",
    )
    parallel: bool = Field(
        default=False,
        description="Run agents concurrently within this phase",
    )
    entry_conditions: list[ConditionConfig] = Field(default_factory=list)
    exit_conditions: list[ConditionConfig] = Field(default_factory=list)
    quality_gates: list[QualityGateConfig] = Field(default_factory=list)
    on_success: str = Field(
        default="",
        description="Next phase ID on success (empty = terminal)",
    )
    on_failure: str = Field(
        default="",
        description="Fallback phase ID on failure (empty = terminal)",
    )
    skippable: bool = False
    skip: bool = Field(default=False, description="Runtime toggle to skip this phase")
    is_terminal: bool = False
    requires_human: bool = False


# ---- Workflow ----


class WorkflowConfig(BaseModel):
    """Complete workflow definition for a profile.

    Contains the phase graph and status lifecycle.
    """

    model_config = {"frozen": True}

    name: str
    description: str = ""
    statuses: list[StatusConfig] = Field(default_factory=list)
    phases: list[WorkflowPhaseConfig] = Field(default_factory=list)


# ---- Governance ----


class DelegatedAuthorityConfig(BaseModel):
    """Thresholds for automated governance decisions."""

    model_config = {"frozen": True}

    auto_approve_threshold: float = 0.8
    review_threshold: float = 0.5
    abort_threshold: float = 0.2
    work_type_overrides: dict[str, dict[str, float]] = Field(default_factory=dict)


class PolicyConfig(BaseModel):
    """A governance policy evaluated at phase transitions."""

    model_config = {"frozen": True}

    id: str
    name: str
    description: str = ""
    scope: str = "global"
    action: str = Field(description="Policy action: allow, deny, review, warn, escalate")
    conditions: list[str] = Field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


class GovernanceConfig(BaseModel):
    """Governance configuration for a profile.

    Reuses decision_os YAML format for compatibility.
    """

    model_config = {"frozen": True}

    delegated_authority: DelegatedAuthorityConfig = Field(
        default_factory=DelegatedAuthorityConfig,
    )
    policies: list[PolicyConfig] = Field(default_factory=list)


# ---- Work Item Types ----


class ArtifactTypeConfig(BaseModel):
    """Definition of an artifact type produced during workflow execution."""

    model_config = {"frozen": True}

    id: str
    name: str
    description: str = ""
    file_extensions: list[str] = Field(default_factory=list)


class FieldDefinition(BaseModel):
    """Custom field definition for work item types."""

    model_config = {"frozen": True}

    name: str
    type: FieldType = FieldType.STRING
    required: bool = False
    default: Any = None
    values: list[str] | None = Field(
        default=None,
        description="Allowed values for enum type fields",
    )

    @model_validator(mode="after")
    def _validate_enum_values(self) -> FieldDefinition:
        if self.type == FieldType.ENUM and not self.values:
            msg = "Enum fields must specify 'values' list"
            raise ValueError(msg)
        return self


class WorkItemTypeConfig(BaseModel):
    """Definition of a work item type within a profile."""

    model_config = {"frozen": True}

    id: str
    name: str
    description: str = ""
    custom_fields: list[FieldDefinition] = Field(default_factory=list)
    artifact_types: list[ArtifactTypeConfig] = Field(default_factory=list)


# ---- Profile (bundles all domain config) ----


class ProfileConfig(BaseModel):
    """Complete profile bundling all domain configuration.

    A profile defines the entire domain: agents, workflow, governance,
    and work item types. Switching profiles switches the entire domain.
    """

    model_config = {"frozen": True}

    name: str = Field(description="Profile display name")
    description: str = ""
    agents: list[AgentDefinition] = Field(default_factory=list)
    workflow: WorkflowConfig = Field(default_factory=lambda: WorkflowConfig(name="default"))
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    work_item_types: list[WorkItemTypeConfig] = Field(default_factory=list)
