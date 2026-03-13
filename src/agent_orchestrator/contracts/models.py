"""Contract Framework — data models.

Defines CapabilityContract and ArtifactContract as first-class platform concepts.

Domain-agnostic: no domain-specific fields anywhere in this module.
Domain modules register their own contracts against these models.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---- Enums ----


class ReadWriteClassification(str, Enum):
    """Classifies whether a capability operation reads, writes, or both."""

    READ_ONLY = "read_only"
    WRITE_ONLY = "write_only"
    READ_WRITE = "read_write"


class AuditRequirement(str, Enum):
    """Specifies the audit depth required for a capability contract."""

    NONE = "none"
    INVOCATION = "invocation"
    FULL = "full"


class FailureSemantic(str, Enum):
    """Defines how the platform should behave when contract validation fails."""

    FAIL_FAST = "fail_fast"
    RETURN_PARTIAL = "return_partial"
    RETRY = "retry"
    SKIP = "skip"
    WARN_ONLY = "warn_only"


class ContractViolationSeverity(str, Enum):
    """Severity level of a contract violation."""

    WARNING = "warning"
    ERROR = "error"


class LifecycleState(str, Enum):
    """Standard lifecycle states for artifacts."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    EXPIRED = "expired"


# ---- Sub-models ----


class ContractTimeoutPolicy(BaseModel, frozen=True):
    """Timeout configuration specified by a capability contract."""

    timeout_seconds: float
    on_timeout: FailureSemantic = FailureSemantic.FAIL_FAST


class ContractRetryPolicy(BaseModel, frozen=True):
    """Retry configuration specified by a capability contract."""

    max_retries: int = 0
    delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0


class ArtifactValidationRule(BaseModel, frozen=True):
    """A single named validation rule applied to an artifact field or the whole artifact.

    Supported rule_type values:
    - ``min_length``: parameters: {"value": int}
    - ``max_length``: parameters: {"value": int}
    - ``allowed_values``: parameters: {"values": list}
    - ``type_check``: parameters: {"type": "string"|"integer"|"number"|"boolean"|"array"|"object"}
    - ``required_if``: parameters: {"condition_field": str, "condition_value": Any}
    - ``pattern``: parameters: {"regex": str}  (requires stdlib re)

    Domain modules may interpret rule_type extensions not listed here.
    """

    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    field: str | None = None
    rule_type: str
    parameters: dict = Field(default_factory=dict)
    message: str = ""
    severity: ContractViolationSeverity = ContractViolationSeverity.ERROR


# ---- Contract violation result ----


class ContractViolation(BaseModel, frozen=True):
    """A single contract violation detected during validation."""

    contract_id: str
    violation_type: str
    field: str | None = None
    message: str
    severity: ContractViolationSeverity = ContractViolationSeverity.ERROR


class ContractValidationResult(BaseModel, frozen=True):
    """Result of validating a payload against a registered contract."""

    is_valid: bool
    contract_id: str
    violations: list[ContractViolation] = Field(default_factory=list)
    validated_at: datetime = Field(default_factory=datetime.utcnow)


# ---- Capability Contract ----


class CapabilityContract(BaseModel, frozen=True):
    """Defines the interface contract for a connector capability operation.

    A capability contract governs:
    - What inputs are required and their types
    - What outputs are expected
    - Whether the operation is read-only or mutating
    - Timeout and retry expectations
    - Audit and cost reporting requirements

    Domain modules may register contracts for any capability_type string
    without modifying platform core.
    """

    contract_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capability_type: str
    operation_name: str
    description: str = ""
    input_schema: dict = Field(
        default_factory=dict,
        description="JSON Schema fragment describing required/optional input parameters.",
    )
    output_schema: dict = Field(
        default_factory=dict,
        description="JSON Schema fragment describing expected output payload fields.",
    )
    read_write_classification: ReadWriteClassification = ReadWriteClassification.READ_ONLY
    permission_requirements: list[str] = Field(
        default_factory=list,
        description="Platform permission tokens required before invocation.",
    )
    timeout_policy: ContractTimeoutPolicy | None = None
    retry_policy: ContractRetryPolicy | None = None
    audit_requirements: AuditRequirement = AuditRequirement.INVOCATION
    cost_reporting_required: bool = False
    failure_semantics: FailureSemantic = FailureSemantic.WARN_ONLY
    metadata: dict = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=datetime.utcnow)


# ---- Artifact Contract ----


class ArtifactContract(BaseModel, frozen=True):
    """Defines the structural and lifecycle contract for a workflow artifact.

    An artifact contract governs:
    - Which fields are required vs optional
    - Validation rules applied to field values
    - What provenance metadata producers must supply
    - Lifecycle states an artifact may pass through
    - Constraints on who may produce or consume the artifact

    Domain modules may register contracts for any artifact_type string
    without modifying platform core.
    """

    contract_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    artifact_type: str
    description: str = ""
    required_fields: list[str] = Field(
        default_factory=list,
        description="Fields that must be present in every artifact of this type.",
    )
    optional_fields: list[str] = Field(
        default_factory=list,
        description="Known optional fields; others are permitted for extensibility.",
    )
    validation_rules: list[ArtifactValidationRule] = Field(
        default_factory=list,
        description="Ordered list of validation rules applied to artifact payloads.",
    )
    provenance_requirements: list[str] = Field(
        default_factory=list,
        description="Provenance keys that producers must include.",
    )
    lifecycle_state_model: list[LifecycleState] = Field(
        default_factory=list,
        description="Valid lifecycle states for artifacts of this type.",
    )
    initial_lifecycle_state: LifecycleState = LifecycleState.DRAFT
    producer_constraints: list[str] = Field(
        default_factory=list,
        description="Agent roles or module names permitted to produce this artifact.",
    )
    consumer_constraints: list[str] = Field(
        default_factory=list,
        description="Agent roles or module names permitted to consume this artifact.",
    )
    metadata: dict = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=datetime.utcnow)
