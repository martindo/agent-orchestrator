"""Shared base for file_storage capability connector providers."""
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
from ...normalized import FileStorageArtifact

logger = logging.getLogger(__name__)

_FILE_STORAGE_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="upload_file",
        description="Upload a file to storage",
        capability_type=CapabilityType.FILE_STORAGE,
        read_only=False,
        required_parameters=["name", "content"],
        optional_parameters=["path", "content_type", "bucket"],
    ),
    ConnectorOperationDescriptor(
        operation="download_file",
        description="Download a file by ID or path",
        capability_type=CapabilityType.FILE_STORAGE,
        read_only=True,
        required_parameters=["file_id"],
        optional_parameters=["bucket"],
    ),
    ConnectorOperationDescriptor(
        operation="list_files",
        description="List files in a directory or bucket",
        capability_type=CapabilityType.FILE_STORAGE,
        read_only=True,
        required_parameters=[],
        optional_parameters=["path", "query", "limit", "bucket"],
    ),
    ConnectorOperationDescriptor(
        operation="delete_file",
        description="Delete a file by ID or path",
        capability_type=CapabilityType.FILE_STORAGE,
        read_only=False,
        required_parameters=["file_id"],
        optional_parameters=["bucket"],
    ),
    ConnectorOperationDescriptor(
        operation="get_metadata",
        description="Get file metadata without downloading content",
        capability_type=CapabilityType.FILE_STORAGE,
        read_only=True,
        required_parameters=["file_id"],
        optional_parameters=["bucket"],
    ),
]


class FileStorageProviderError(Exception):
    """Raised when a file storage provider encounters an unrecoverable error."""


class BaseFileStorageProvider(ABC):
    """Abstract base with common execute() dispatch for file storage providers.

    Subclasses implement _upload_file(), _download_file(), _list_files(),
    _delete_file(), and _get_metadata(). Each must return a tuple of
    (dict, ConnectorCostInfo | None) where the dict is an ExternalArtifact
    model_dump().
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.FILE_STORAGE],
            operations=_FILE_STORAGE_OPS,
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
        """Return True if the provider has a non-empty API key configured."""
        return bool(getattr(self, "_api_key", None))

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        """Dispatch the request to the appropriate handler and return a result.

        Args:
            request: Connector invocation request with operation and parameters.

        Returns:
            ConnectorInvocationResult with status, payload, and cost info.
        """
        start = time.monotonic()
        op = request.operation
        params = request.parameters

        try:
            payload, cost_info = await self._dispatch(op, params)
        except FileStorageProviderError as exc:
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

        if payload is None:
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self.provider_id,
                provider=self.provider_id,
                capability_type=request.capability_type,
                operation=op,
                status=ConnectorStatus.NOT_FOUND,
                error_message=f"Unknown operation: {op!r}",
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

    async def _dispatch(
        self, op: str, params: dict
    ) -> tuple[dict, ConnectorCostInfo | None] | tuple[None, None]:
        """Route an operation name to the corresponding handler method."""
        if op == "upload_file":
            return await self._upload_file(
                name=params["name"],
                content=params["content"],
                path=params.get("path"),
                content_type=params.get("content_type"),
                bucket=params.get("bucket"),
            )
        if op == "download_file":
            return await self._download_file(
                file_id=params["file_id"],
                bucket=params.get("bucket"),
            )
        if op == "list_files":
            return await self._list_files(
                path=params.get("path"),
                query=params.get("query"),
                limit=params.get("limit"),
                bucket=params.get("bucket"),
            )
        if op == "delete_file":
            return await self._delete_file(
                file_id=params["file_id"],
                bucket=params.get("bucket"),
            )
        if op == "get_metadata":
            return await self._get_metadata(
                file_id=params["file_id"],
                bucket=params.get("bucket"),
            )
        return None, None

    @abstractmethod
    async def _upload_file(
        self,
        name: str,
        content: str | bytes,
        path: str | None,
        content_type: str | None,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _download_file(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _list_files(
        self,
        path: str | None,
        query: str | None,
        limit: int | None,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _delete_file(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _get_metadata(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @staticmethod
    def _make_file_artifact(
        provider: str,
        connector_id: str,
        file_id: str | None,
        name: str,
        path: str | None,
        size_bytes: int | None,
        content_type: str | None,
        url: str | None,
        content: str | None,
        raw_payload: dict,
        resource_type: str,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap file metadata in a platform-standard ExternalArtifact.

        The normalized_payload contains a FileStorageArtifact-shaped dict.
        The raw_payload holds the provider's original response.

        Args:
            provider: Provider ID.
            connector_id: Connector ID (typically same as provider).
            file_id: Provider-specific file ID or object key.
            name: File name.
            path: Full path or storage key, or None.
            size_bytes: File size in bytes, or None.
            content_type: MIME content type, or None.
            url: Browser-accessible or download URL, or None.
            content: Decoded text content or base64-encoded binary, or None.
            raw_payload: Raw provider API response dict.
            resource_type: Resource type label (e.g. "file", "folder").
            provenance: Provenance dict (provider, bucket, etc.).
            references: Optional list of ExternalReference for related resources.

        Returns:
            ExternalArtifact with normalized_payload containing FileStorageArtifact
            fields.
        """
        normalized = FileStorageArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.FILE_STORAGE,
            file_id=file_id,
            name=name,
            path=path,
            size_bytes=size_bytes,
            content_type=content_type,
            url=url,
            content=content,
        )
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.FILE_STORAGE,
            resource_type=resource_type,
            raw_payload=raw_payload,
            normalized_payload=normalized.model_dump(mode="json"),
            references=references or [],
            provenance=provenance,
        )

    @staticmethod
    def _make_file_list_artifact(
        provider: str,
        connector_id: str,
        path: str | None,
        items: list[dict],
        total: int,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap a list of file items in a platform-standard ExternalArtifact.

        The raw_payload holds the full item list and total count.
        normalized_payload is omitted because FileStorageArtifact represents a
        single file, not a list.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            path: Directory path or prefix used for listing, or None.
            items: List of item summary dicts from the provider response.
            total: Total number of items returned.
            provenance: Provenance dict.

        Returns:
            ExternalArtifact with resource_type "file_list".
        """
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.FILE_STORAGE,
            resource_type="file_list",
            raw_payload={"path": path, "total": total, "items": items},
            normalized_payload=None,
            references=[],
            provenance=provenance,
        )
