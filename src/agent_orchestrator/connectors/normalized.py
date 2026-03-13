"""Normalized capability-specific artifact schemas.

Each schema corresponds to a CapabilityType and provides a structured
representation of common connector outputs. These are capability-centric,
not domain-specific — a SearchResultArtifact works for any search provider.

Domain modules may further transform these into domain-specific structures.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from .models import CapabilityType

logger = logging.getLogger(__name__)


class NormalizedArtifactBase(BaseModel, frozen=True):
    """Base fields shared by all normalized capability artifacts."""
    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_connector: str
    provider: str
    capability_type: CapabilityType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class SearchResultItem(BaseModel, frozen=True):
    """A single item within a search result set."""
    rank: int = 0
    title: str
    snippet: str | None = None
    url: str | None = None
    score: float | None = None
    metadata: dict = Field(default_factory=dict)


class SearchResultArtifact(NormalizedArtifactBase, frozen=True):
    """Normalized artifact for search capability results."""
    capability_type: CapabilityType = CapabilityType.SEARCH
    query: str
    results: list[SearchResultItem] = Field(default_factory=list)
    total_count: int | None = None


class DocumentArtifact(NormalizedArtifactBase, frozen=True):
    """Normalized artifact for a document from the documents capability."""
    capability_type: CapabilityType = CapabilityType.DOCUMENTS
    document_id: str | None = None
    title: str | None = None
    content: str | None = None
    content_type: str = "text/plain"
    url: str | None = None
    size_bytes: int | None = None


class MessageArtifact(NormalizedArtifactBase, frozen=True):
    """Normalized artifact for a message from the messaging capability."""
    capability_type: CapabilityType = CapabilityType.MESSAGING
    message_id: str | None = None
    channel: str | None = None
    sender: str | None = None
    recipients: list[str] = Field(default_factory=list)
    subject: str | None = None
    body: str | None = None


class TicketArtifact(NormalizedArtifactBase, frozen=True):
    """Normalized artifact for a ticket from the ticketing capability."""
    capability_type: CapabilityType = CapabilityType.TICKETING
    ticket_id: str
    title: str
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee: str | None = None
    url: str | None = None


class FileStorageArtifact(NormalizedArtifactBase, frozen=True):
    """Normalized artifact for a file from the file_storage capability."""
    capability_type: CapabilityType = CapabilityType.FILE_STORAGE
    file_id: str | None = None
    name: str
    path: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    url: str | None = None
    content: str | None = None  # base64-encoded for binary, plain text for text files


class RepositoryArtifact(NormalizedArtifactBase, frozen=True):
    """Normalized artifact for a repository from the repository capability."""
    capability_type: CapabilityType = CapabilityType.REPOSITORY
    repo_id: str | None = None
    name: str
    description: str | None = None
    url: str | None = None
    default_branch: str | None = None


class TelemetryArtifact(NormalizedArtifactBase, frozen=True):
    """Normalized artifact for a telemetry data point."""
    capability_type: CapabilityType = CapabilityType.TELEMETRY
    metric_name: str
    value: float
    unit: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    interval_seconds: float | None = None


class IdentityArtifact(NormalizedArtifactBase, frozen=True):
    """Normalized artifact for an identity principal from the identity capability."""
    capability_type: CapabilityType = CapabilityType.IDENTITY
    principal_id: str
    display_name: str | None = None
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)


# Type alias for the union of all normalized artifact types
NormalizedArtifact = (
    SearchResultArtifact
    | DocumentArtifact
    | MessageArtifact
    | TicketArtifact
    | FileStorageArtifact
    | RepositoryArtifact
    | TelemetryArtifact
    | IdentityArtifact
)

_CAPABILITY_TO_TYPE: dict[CapabilityType, type] = {
    CapabilityType.SEARCH: SearchResultArtifact,
    CapabilityType.DOCUMENTS: DocumentArtifact,
    CapabilityType.MESSAGING: MessageArtifact,
    CapabilityType.TICKETING: TicketArtifact,
    CapabilityType.FILE_STORAGE: FileStorageArtifact,
    CapabilityType.REPOSITORY: RepositoryArtifact,
    CapabilityType.TELEMETRY: TelemetryArtifact,
    CapabilityType.IDENTITY: IdentityArtifact,
}


def get_normalized_type(capability_type: CapabilityType) -> type | None:
    """Return the normalized artifact class for a given capability type.

    Returns None if the capability type has no defined normalized schema.

    Args:
        capability_type: The capability type to look up.

    Returns:
        Artifact class or None.
    """
    return _CAPABILITY_TO_TYPE.get(capability_type)


def try_normalize(
    payload: dict,
    capability_type: CapabilityType,
    source_connector: str,
    provider: str,
) -> NormalizedArtifact | None:
    """Attempt to construct a normalized artifact from a raw payload dict.

    Returns None if normalization fails or capability_type has no schema.
    Never raises — normalization is best-effort.

    Args:
        payload: Raw dict payload from a connector result.
        capability_type: The capability type to normalize for.
        source_connector: Connector ID that produced the payload.
        provider: Provider ID.

    Returns:
        NormalizedArtifact instance or None.
    """
    artifact_cls = _CAPABILITY_TO_TYPE.get(capability_type)
    if artifact_cls is None:
        return None
    try:
        return artifact_cls(
            source_connector=source_connector,
            provider=provider,
            **payload,
        )
    except Exception as exc:
        logger.debug(
            "Normalization failed for capability=%s: %s",
            capability_type.value, exc,
        )
        return None
