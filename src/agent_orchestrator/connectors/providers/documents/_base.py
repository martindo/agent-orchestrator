"""Shared base for documents capability connector providers."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from ...models import (
    CapabilityType,
    ConnectorCostInfo,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorStatus,
    ExternalArtifact,
    ExternalReference,
)
from ...normalized import DocumentArtifact

logger = logging.getLogger(__name__)

_DOCUMENTS_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="search_documents",
        description="Search for documents matching a query, optionally scoped to a space or folder",
        capability_type=CapabilityType.DOCUMENTS,
        read_only=True,
        required_parameters=["query"],
        optional_parameters=["scope", "limit"],
    ),
    ConnectorOperationDescriptor(
        operation="get_document",
        description="Retrieve a document by its provider-specific ID",
        capability_type=CapabilityType.DOCUMENTS,
        read_only=True,
        required_parameters=["document_id"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="extract_section",
        description="Extract a named section from a document identified by a selector",
        capability_type=CapabilityType.DOCUMENTS,
        read_only=True,
        required_parameters=["document_id", "selector"],
        optional_parameters=[],
    ),
]

_DEFAULT_LIMIT = 10


class DocumentsProviderError(Exception):
    """Raised when a documents provider encounters an unrecoverable error."""


class BaseDocumentsProvider(ABC):
    """Abstract base with common execute() dispatch for documents providers.

    Subclasses implement _search_documents(), _get_document(), and
    _extract_section(). All three must return an ExternalArtifact or
    a list-wrapper dict — never raw provider payloads.
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.DOCUMENTS],
            operations=_DOCUMENTS_OPS,
            enabled=self.is_available(),
            auth_required=True,
            auth_type="api_key",
            version="1.0",
        )

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    def is_available(self) -> bool:
        """Return True if the provider has credentials configured."""
        return bool(getattr(self, "_api_token", None))

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        """Dispatch the request to the appropriate handler and return a result.

        Args:
            request: Connector invocation request with operation and parameters.

        Returns:
            ConnectorInvocationResult with status, payload as ExternalArtifact dict,
            and optional cost info.
        """
        start = time.monotonic()
        op = request.operation
        params = request.parameters

        try:
            if op == "search_documents":
                payload, cost_info = await self._search_documents(
                    query=params["query"],
                    scope=params.get("scope"),
                    limit=int(params.get("limit", _DEFAULT_LIMIT)),
                )
            elif op == "get_document":
                payload, cost_info = await self._get_document(
                    document_id=params["document_id"],
                )
            elif op == "extract_section":
                payload, cost_info = await self._extract_section(
                    document_id=params["document_id"],
                    selector=params["selector"],
                )
            else:
                return ConnectorInvocationResult(
                    request_id=request.request_id,
                    connector_id=self.provider_id,
                    provider=self.provider_id,
                    capability_type=request.capability_type,
                    operation=op,
                    status=ConnectorStatus.NOT_FOUND,
                    error_message=f"Unknown operation: {op!r}",
                )
        except DocumentsProviderError as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self.provider_id,
                provider=self.provider_id,
                capability_type=request.capability_type,
                operation=op,
                status=ConnectorStatus.FAILURE,
                error_message=str(exc),
                duration_ms=duration_ms,
            )

        duration_ms = (time.monotonic() - start) * 1000
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id=self.provider_id,
            provider=self.provider_id,
            capability_type=request.capability_type,
            operation=op,
            status=ConnectorStatus.SUCCESS,
            payload=payload,
            cost_info=cost_info,
            duration_ms=duration_ms,
        )

    @abstractmethod
    async def _search_documents(
        self,
        query: str,
        scope: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _get_document(
        self,
        document_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _extract_section(
        self,
        document_id: str,
        selector: str,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @staticmethod
    def _make_document_artifact(
        provider: str,
        connector_id: str,
        document_id: str | None,
        title: str | None,
        content: str | None,
        url: str | None,
        content_type: str,
        raw_payload: dict,
        resource_type: str,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap a document in a platform-standard ExternalArtifact.

        The normalized_payload contains a DocumentArtifact-shaped dict.
        The raw_payload holds the provider's original response.

        Args:
            provider: Provider ID.
            connector_id: Connector ID (typically same as provider).
            document_id: Provider-specific document ID, or None.
            title: Document title, or None.
            content: Document text content, or None.
            url: Document URL, or None.
            content_type: MIME type of the content.
            raw_payload: Raw provider API response dict.
            resource_type: "document" or "document_section".
            provenance: Provenance dict (space, query, selector, etc.).
            references: Optional list of ExternalReference for related resources.

        Returns:
            ExternalArtifact with normalized_payload containing DocumentArtifact fields.
        """
        normalized = DocumentArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.DOCUMENTS,
            document_id=document_id,
            title=title,
            content=content,
            url=url,
            content_type=content_type,
            size_bytes=len(content.encode()) if content else None,
        )
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.DOCUMENTS,
            resource_type=resource_type,
            raw_payload=raw_payload,
            normalized_payload=normalized.model_dump(mode="json"),
            references=references or [],
            provenance=provenance,
        )
