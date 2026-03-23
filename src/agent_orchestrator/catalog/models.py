"""Capability Catalog — data models.

Defines the CapabilityRegistration model and supporting enums for
team/capability discovery, governance, and invocation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from agent_orchestrator.contracts.models import LifecycleState


class InvocationMode(str, Enum):
    """How a capability can be invoked."""

    SYNC = "sync"
    ASYNC = "async"
    EVENT_DRIVEN = "event_driven"


class SecurityClassification(str, Enum):
    """Security classification for a registered capability."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class MemoryUsagePolicy(str, Enum):
    """Policy governing how a capability uses the knowledge store."""

    NONE = "none"
    READ_ONLY = "read_only"
    WRITE_ONLY = "write_only"
    READ_WRITE = "read_write"


class CapabilityRegistration(BaseModel, frozen=True):
    """A registered capability/team that can be discovered and invoked.

    Immutable (frozen) to ensure thread-safe reads without copying.
    """

    # Identity
    capability_id: str = Field(description="Unique ID, e.g. 'market_research.v1'")
    display_name: str = Field(description="Human-readable name")
    description: str = ""
    owner: str = ""
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)

    # Interface contract
    input_schema: dict = Field(
        default_factory=dict,
        description="JSON Schema describing accepted input",
    )
    output_schema: dict = Field(
        default_factory=dict,
        description="JSON Schema describing produced output",
    )

    # Execution binding
    profile_name: str = Field(description="YAML profile that powers this capability")
    deployment_mode: str = "lite"
    required_connectors: list[str] = Field(default_factory=list)

    # Governance
    security_classification: SecurityClassification = SecurityClassification.INTERNAL
    approval_requirements: list[str] = Field(default_factory=list)
    review_required_below: float = 0.5
    memory_usage_policy: MemoryUsagePolicy = MemoryUsagePolicy.NONE

    # Invocation
    invocation_modes: list[InvocationMode] = Field(
        default_factory=lambda: [InvocationMode.ASYNC],
    )

    # Lifecycle
    status: LifecycleState = LifecycleState.DRAFT
    registered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    metadata: dict = Field(default_factory=dict)
