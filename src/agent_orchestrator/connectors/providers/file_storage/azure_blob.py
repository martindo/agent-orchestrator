"""Azure Blob Storage file storage connector provider."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...models import ConnectorCostInfo
from ._base import BaseFileStorageProvider, FileStorageProviderError

logger = logging.getLogger(__name__)


class AzureBlobFileStorageProvider(BaseFileStorageProvider):
    """Azure Blob Storage file storage connector provider.

    Uses azure-storage-blob (optional dependency) with a connection string.

    Example::

        provider = AzureBlobFileStorageProvider(
            connection_string="DefaultEndpointsProtocol=https;...",
            default_container="my-container",
        )

    Environment variables::

        AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER
    """

    def __init__(self, connection_string: str, default_container: str) -> None:
        self._connection_string = connection_string
        self._default_container = default_container
        self._api_key = default_container  # satisfies is_available()

    @classmethod
    def from_env(cls) -> "AzureBlobFileStorageProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``AZURE_STORAGE_CONNECTION_STRING``,
        ``AZURE_STORAGE_CONTAINER``

        Returns None if either is missing. Warns if azure-storage-blob is not
        importable.
        """
        import os
        conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        container = os.environ.get("AZURE_STORAGE_CONTAINER", "")
        if not conn_str or not container:
            return None
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore[import-untyped]  # noqa: F401
        except ImportError:
            logger.warning(
                "azure-storage-blob is not installed; "
                "AzureBlobFileStorageProvider will not be functional. "
                "Install it with: pip install azure-storage-blob"
            )
        return cls(connection_string=conn_str, default_container=container)

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "file_storage.azure_blob"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Azure Blob Storage"

    def _get_client(self, container: str | None = None) -> Any:
        """Return an Azure ContainerClient for the given (or default) container."""
        from azure.storage.blob import BlobServiceClient  # type: ignore[import-untyped]
        service = BlobServiceClient.from_connection_string(self._connection_string)
        return service.get_container_client(container or self._default_container)

    async def _upload_file(
        self,
        name: str,
        content: str | bytes,
        path: str | None,
        content_type: str | None,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Upload a file to Azure Blob Storage.

        Args:
            name: Blob name (filename).
            content: File content as str or bytes.
            path: Optional prefix/directory path within the container.
            content_type: MIME type of the file.
            bucket: Target container; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict, None).

        Raises:
            FileStorageProviderError: When the Azure API call fails.
        """
        blob_name = f"{path}/{name}" if path else name
        content_bytes = content.encode() if isinstance(content, str) else content

        def _call() -> None:
            try:
                from azure.storage.blob import ContentSettings  # type: ignore[import-untyped]
                container_client = self._get_client(bucket)
                container_client.upload_blob(
                    name=blob_name,
                    data=content_bytes,
                    overwrite=True,
                    content_settings=ContentSettings(
                        content_type=content_type or "application/octet-stream"
                    ),
                )
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Azure upload_file error for blob={blob_name!r}: {exc}"
                ) from exc

        await asyncio.get_running_loop().run_in_executor(None, _call)

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=blob_name,
            name=name,
            path=path,
            size_bytes=len(content_bytes),
            content_type=content_type,
            url=None,
            content=None,
            raw_payload={"container": bucket or self._default_container, "blob": blob_name},
            resource_type="file",
            provenance={"provider": "azure_blob", "container": bucket or self._default_container},
        )
        logger.info(
            "Azure upload_file: container=%r blob=%r",
            bucket or self._default_container, blob_name,
        )
        return artifact.model_dump(mode="json"), None

    async def _download_file(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Download a blob from Azure Blob Storage.

        Args:
            file_id: Blob name/path.
            bucket: Source container; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict with content, None).

        Raises:
            FileStorageProviderError: When the Azure API call fails.
        """
        def _call() -> tuple[str, object]:
            try:
                container_client = self._get_client(bucket)
                blob_client = container_client.get_blob_client(file_id)
                data = blob_client.download_blob().readall()
                content = data.decode("utf-8", errors="replace")
                props = blob_client.get_blob_properties()
                return content, props
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Azure download_file error for blob={file_id!r}: {exc}"
                ) from exc

        content, props = await asyncio.get_running_loop().run_in_executor(None, _call)
        name = file_id.split("/")[-1]
        cs = getattr(props, "content_settings", None)
        blob_content_type: str | None = getattr(cs, "content_type", None) if cs else None

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=name,
            path=None,
            size_bytes=getattr(props, "size", None),
            content_type=blob_content_type,
            url=None,
            content=content,
            raw_payload={"container": bucket or self._default_container, "blob": file_id},
            resource_type="file",
            provenance={"provider": "azure_blob", "container": bucket or self._default_container},
        )
        logger.info(
            "Azure download_file: container=%r blob=%r",
            bucket or self._default_container, file_id,
        )
        return artifact.model_dump(mode="json"), None

    async def _list_files(
        self,
        path: str | None,
        query: str | None,
        limit: int | None,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List blobs in an Azure container.

        Args:
            path: Optional name prefix to restrict listing.
            query: Optional substring filter applied to blob names.
            limit: Maximum number of results (default 100).
            bucket: Target container; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict with file_list, None).

        Raises:
            FileStorageProviderError: When the Azure API call fails.
        """
        def _call() -> list:
            try:
                container_client = self._get_client(bucket)
                kwargs: dict = {}
                if path:
                    kwargs["name_starts_with"] = path
                blobs = list(container_client.list_blobs(**kwargs))
                return blobs
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Azure list_files error: {exc}"
                ) from exc

        blobs = await asyncio.get_running_loop().run_in_executor(None, _call)

        if query:
            blobs = [b for b in blobs if query.lower() in b.name.lower()]
        blobs = blobs[: limit or 100]

        items = [
            {
                "file_id": b.name,
                "name": b.name.split("/")[-1],
                "size_bytes": b.size,
                "content_type": (
                    b.content_settings.content_type
                    if b.content_settings
                    else None
                ),
            }
            for b in blobs
        ]

        artifact = self._make_file_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            path=path,
            items=items,
            total=len(items),
            provenance={"provider": "azure_blob", "container": bucket or self._default_container},
        )
        logger.info(
            "Azure list_files: container=%r path=%r items=%d",
            bucket or self._default_container, path, len(items),
        )
        return artifact.model_dump(mode="json"), None

    async def _delete_file(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Delete a blob from Azure Blob Storage.

        Args:
            file_id: Blob name/path.
            bucket: Target container; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict, None).

        Raises:
            FileStorageProviderError: When the Azure API call fails.
        """
        def _call() -> None:
            try:
                container_client = self._get_client(bucket)
                container_client.delete_blob(file_id)
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Azure delete_file error for blob={file_id!r}: {exc}"
                ) from exc

        await asyncio.get_running_loop().run_in_executor(None, _call)

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=file_id,
            path=None,
            size_bytes=None,
            content_type=None,
            url=None,
            content=None,
            raw_payload={"container": bucket or self._default_container, "blob": file_id},
            resource_type="file",
            provenance={"provider": "azure_blob", "container": bucket or self._default_container},
        )
        logger.info(
            "Azure delete_file: container=%r blob=%r",
            bucket or self._default_container, file_id,
        )
        return artifact.model_dump(mode="json"), None

    async def _get_metadata(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Get Azure blob metadata without downloading content.

        Args:
            file_id: Blob name/path.
            bucket: Target container; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict with size/content_type, None).

        Raises:
            FileStorageProviderError: When the Azure API call fails.
        """
        def _call() -> object:
            try:
                container_client = self._get_client(bucket)
                blob_client = container_client.get_blob_client(file_id)
                return blob_client.get_blob_properties()
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Azure get_metadata error for blob={file_id!r}: {exc}"
                ) from exc

        props = await asyncio.get_running_loop().run_in_executor(None, _call)
        name = file_id.split("/")[-1]
        cs = getattr(props, "content_settings", None)
        blob_content_type: str | None = getattr(cs, "content_type", None) if cs else None

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=name,
            path=None,
            size_bytes=getattr(props, "size", None),
            content_type=blob_content_type,
            url=None,
            content=None,
            raw_payload={"container": bucket or self._default_container, "blob": file_id},
            resource_type="file",
            provenance={"provider": "azure_blob", "container": bucket or self._default_container},
        )
        logger.info(
            "Azure get_metadata: container=%r blob=%r size=%s",
            bucket or self._default_container, file_id, getattr(props, "size", None),
        )
        return artifact.model_dump(mode="json"), None
