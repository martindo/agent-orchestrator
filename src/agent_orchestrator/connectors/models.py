"""Connector Capability Framework — data models.

All models are Pydantic v2 frozen dataclasses.
Domain-agnostic: no domain-specific fields anywhere in this module.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CapabilityType(str, Enum):
    """Taxonomy of external connector capability categories."""

    SEARCH = "search"
    DOCUMENTS = "documents"
    MESSAGING = "messaging"
    TICKETING = "ticketing"
    REPOSITORY = "repository"
    TELEMETRY = "telemetry"
    IDENTITY = "identity"
    EXTERNAL_API = "external_api"
    FILE_STORAGE = "file_storage"
    WORKFLOW_ACTION = "workflow_action"


class ConnectorStatus(str, Enum):
    """Result status of a connector invocation."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    REQUIRES_APPROVAL = "requires_approval"


class ConnectorOperationDescriptor(BaseModel, frozen=True):
    """Describes a single operation offered by a connector provider."""

    operation: str
    description: str
    capability_type: CapabilityType
    read_only: bool = True
    required_parameters: list[str] = Field(default_factory=list)
    optional_parameters: list[str] = Field(default_factory=list)


class ConnectorProviderDescriptor(BaseModel, frozen=True):
    """Describes a registered connector provider and its capabilities."""

    provider_id: str
    display_name: str
    capability_types: list[CapabilityType]
    operations: list[ConnectorOperationDescriptor] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict = Field(default_factory=dict)
    version: str | None = None
    auth_required: bool = False
    auth_type: str = "none"
    parameter_schemas: dict = Field(default_factory=dict)
    result_schema_hint: dict = Field(default_factory=dict)
    configuration_schema: dict = Field(default_factory=dict)


class ConnectorInvocationRequest(BaseModel, frozen=True):
    """Represents a request to invoke a connector capability."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capability_type: CapabilityType
    operation: str
    parameters: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    preferred_provider: str | None = None
    timeout_seconds: float | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConnectorCostInfo(BaseModel, frozen=True):
    """Cost and usage accounting information for a connector invocation."""

    request_cost: float | None = None
    usage_units: float | None = None
    provider_reported_cost: float | None = None
    estimated_cost: float | None = None
    currency: str = "USD"
    unit_label: str | None = None


class ConnectorInvocationResult(BaseModel, frozen=True):
    """Result of a connector invocation."""

    request_id: str
    connector_id: str
    provider: str
    capability_type: CapabilityType
    operation: str
    status: ConnectorStatus
    payload: dict | None = None
    error_message: str | None = None
    cost_info: ConnectorCostInfo | None = None
    duration_ms: float | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class ExternalReference(BaseModel, frozen=True):
    """A typed reference to an external resource."""

    ref_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider: str
    resource_type: str
    external_id: str
    url: str | None = None
    metadata: dict = Field(default_factory=dict)


class ExternalResourceDescriptor(BaseModel, frozen=True):
    """Describes a category of external resource a connector can return."""

    resource_type: str
    provider: str
    capability_type: CapabilityType
    description: str | None = None
    schema_hint: dict = Field(default_factory=dict)


class ExternalArtifact(BaseModel, frozen=True):
    """Domain-agnostic envelope wrapping a connector result payload.

    Domain modules may transform this into domain-specific artifacts.
    This model intentionally contains no domain-specific fields.
    """

    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_connector: str
    provider: str
    capability_type: CapabilityType
    resource_type: str
    raw_payload: dict | None = None
    normalized_payload: dict | None = None
    references: list[ExternalReference] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    provenance: dict = Field(default_factory=dict)


class ConnectorPermissionPolicy(BaseModel, frozen=True):
    """Permission policy governing connector invocations."""

    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    allowed_capability_types: list[CapabilityType] = Field(default_factory=list)
    denied_capability_types: list[CapabilityType] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    denied_operations: list[str] = Field(default_factory=list)
    allowed_modules: list[str] = Field(default_factory=list)
    allowed_agent_roles: list[str] = Field(default_factory=list)
    read_only: bool = False
    enabled: bool = True
    requires_approval: bool = False


class ConnectorRetryPolicy(BaseModel, frozen=True):
    """Retry configuration for connector execution."""

    max_retries: int = 0
    delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    retryable_statuses: list[ConnectorStatus] = Field(
        default_factory=lambda: [
            ConnectorStatus.TIMEOUT,
            ConnectorStatus.UNAVAILABLE,
            ConnectorStatus.FAILURE,
        ]
    )


class ConnectorRateLimit(BaseModel, frozen=True):
    """Rate and usage limit configuration for a connector."""

    max_requests_per_minute: int | None = None
    max_cost_per_hour: float | None = None
    max_usage_units_per_run: float | None = None
    currency: str = "USD"


class ConnectorCostMetadata(BaseModel, frozen=True):
    """Billing metadata for a connector (platform-level accounting reference)."""

    billing_label: str | None = None
    cost_center: str | None = None
    unit_price: float | None = None
    currency: str = "USD"
    notes: str | None = None


class ConnectorConfig(BaseModel, frozen=True):
    """Configuration for a connector instance registered with the platform."""

    connector_id: str
    display_name: str
    capability_type: CapabilityType
    provider_id: str
    enabled: bool = True
    scoped_modules: list[str] = Field(default_factory=list)
    scoped_agent_roles: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    permission_policies: list[ConnectorPermissionPolicy] = Field(default_factory=list)
    retry_policy: ConnectorRetryPolicy | None = None
    rate_limit: ConnectorRateLimit | None = None
    version: str | None = None
    auth_config: dict | None = None  # ConnectorAuthConfig.model_dump() - avoids circular import
    cost_metadata: ConnectorCostMetadata | None = None
