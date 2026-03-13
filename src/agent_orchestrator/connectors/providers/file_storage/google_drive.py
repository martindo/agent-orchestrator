"""Google Drive file storage connector provider."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...models import ConnectorCostInfo
from ._base import BaseFileStorageProvider, FileStorageProviderError

logger = logging.getLogger(__name__)


class GoogleDriveFileStorageProvider(BaseFileStorageProvider):
    """Google Drive file storage connector provider.

    Uses the google-api-python-client (optional dependency) with service
    account JSON authentication.

    Example::

        provider = GoogleDriveFileStorageProvider(
            service_account_json='{"type": "service_account", ...}'
        )

    Environment variables::

        GDRIVE_SERVICE_ACCOUNT_JSON  (JSON string or file path)
    """

    def __init__(self, service_account_json: str) -> None:
        self._service_account_json = service_account_json
        self._api_key = "configured"  # satisfies is_available()
        self._service = None  # lazy init

    @classmethod
    def from_env(cls) -> "GoogleDriveFileStorageProvider | None":
        """Create an instance from environment variables.

        Required env var: ``GDRIVE_SERVICE_ACCOUNT_JSON`` — a JSON string
        containing service account credentials, or a file path to a JSON file.

        Returns None if the env var is missing. Warns if google-api-python-client
        is not importable.
        """
        import os
        value = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")
        if not value:
            return None
        try:
            from googleapiclient.discovery import build  # type: ignore[import-untyped]  # noqa: F401
        except ImportError:
            logger.warning(
                "google-api-python-client is not installed; "
                "GoogleDriveFileStorageProvider will not be functional. "
                "Install it with: pip install google-api-python-client google-auth"
            )
        # Accept either a JSON string or a file path
        if not value.strip().startswith("{"):
            try:
                with open(value) as fh:
                    value = fh.read()
            except OSError as exc:
                logger.warning(
                    "GDRIVE_SERVICE_ACCOUNT_JSON looks like a path but could not be read: %s",
                    exc,
                )
                return None
        return cls(service_account_json=value)

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "file_storage.google_drive"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Google Drive File Storage"

    def _get_service(self) -> Any:
        """Return a cached Google Drive API service client, building it on first call."""
        if self._service is not None:
            return self._service
        import json
        from google.oauth2 import service_account  # type: ignore[import-untyped]
        from googleapiclient.discovery import build  # type: ignore[import-untyped]
        info = json.loads(self._service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        self._service = build("drive", "v3", credentials=creds)
        return self._service

    async def _upload_file(
        self,
        name: str,
        content: str | bytes,
        path: str | None,
        content_type: str | None,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Upload a file to Google Drive.

        Args:
            name: File name to create in Drive.
            content: File content as str or bytes.
            path: Optional parent folder ID in Drive.
            content_type: MIME type of the file.
            bucket: Unused for Drive; ignored.

        Returns:
            Tuple of (ExternalArtifact dict, None).

        Raises:
            FileStorageProviderError: When the Drive API call fails.
        """
        def _call() -> dict:
            try:
                from googleapiclient.http import MediaInMemoryUpload  # type: ignore[import-untyped]
                service = self._get_service()
                content_bytes = content.encode() if isinstance(content, str) else content
                media = MediaInMemoryUpload(
                    content_bytes,
                    mimetype=content_type or "application/octet-stream",
                )
                metadata: dict = {"name": name}
                if path:
                    metadata["parents"] = [path]
                return service.files().create(
                    body=metadata,
                    media_body=media,
                    fields="id,name,size,mimeType,webViewLink",
                ).execute()
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Google Drive upload_file error for name={name!r}: {exc}"
                ) from exc

        file = await asyncio.get_running_loop().run_in_executor(None, _call)

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file.get("id"),
            name=file.get("name", name),
            path=path,
            size_bytes=int(file["size"]) if file.get("size") else None,
            content_type=file.get("mimeType") or content_type,
            url=file.get("webViewLink"),
            content=None,
            raw_payload=file,
            resource_type="file",
            provenance={"provider": "google_drive"},
        )
        logger.info(
            "Google Drive upload_file: name=%r file_id=%r",
            name, file.get("id"),
        )
        return artifact.model_dump(mode="json"), None

    async def _download_file(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Download a file from Google Drive.

        Args:
            file_id: Drive file ID.
            bucket: Unused for Drive; ignored.

        Returns:
            Tuple of (ExternalArtifact dict with content, None).

        Raises:
            FileStorageProviderError: When the Drive API call fails.
        """
        def _call() -> tuple[str, dict]:
            try:
                import io
                from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import-untyped]
                service = self._get_service()
                request = service.files().get_media(fileId=file_id)
                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                content = buf.getvalue().decode("utf-8", errors="replace")
                meta = service.files().get(
                    fileId=file_id, fields="id,name,size,mimeType"
                ).execute()
                return content, meta
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Google Drive download_file error for id={file_id!r}: {exc}"
                ) from exc

        content, meta = await asyncio.get_running_loop().run_in_executor(None, _call)

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=meta.get("name", file_id),
            path=None,
            size_bytes=int(meta["size"]) if meta.get("size") else None,
            content_type=meta.get("mimeType"),
            url=None,
            content=content,
            raw_payload=meta,
            resource_type="file",
            provenance={"provider": "google_drive"},
        )
        logger.info("Google Drive download_file: id=%r name=%r", file_id, meta.get("name"))
        return artifact.model_dump(mode="json"), None

    async def _list_files(
        self,
        path: str | None,
        query: str | None,
        limit: int | None,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List files in a Google Drive folder.

        Args:
            path: Optional parent folder ID to restrict listing.
            query: Optional name substring filter.
            limit: Maximum number of results (default 100).
            bucket: Unused for Drive; ignored.

        Returns:
            Tuple of (ExternalArtifact dict with file_list, None).

        Raises:
            FileStorageProviderError: When the Drive API call fails.
        """
        def _call() -> list[dict]:
            try:
                service = self._get_service()
                q_parts: list[str] = []
                if path:
                    q_parts.append(f"'{path}' in parents")
                if query:
                    q_parts.append(f"name contains '{query}'")
                kwargs: dict = {
                    "pageSize": limit or 100,
                    "fields": "files(id,name,size,mimeType,webViewLink)",
                }
                if q_parts:
                    kwargs["q"] = " and ".join(q_parts)
                result = service.files().list(**kwargs).execute()
                return result.get("files", [])
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Google Drive list_files error: {exc}"
                ) from exc

        files = await asyncio.get_running_loop().run_in_executor(None, _call)
        items = [
            {
                "file_id": f["id"],
                "name": f["name"],
                "size_bytes": int(f.get("size", 0)),
                "content_type": f.get("mimeType"),
                "url": f.get("webViewLink"),
            }
            for f in files
        ]

        artifact = self._make_file_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            path=path,
            items=items,
            total=len(items),
            provenance={"provider": "google_drive", "query": query},
        )
        logger.info(
            "Google Drive list_files: path=%r query=%r items=%d",
            path, query, len(items),
        )
        return artifact.model_dump(mode="json"), None

    async def _delete_file(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Delete a file from Google Drive.

        Args:
            file_id: Drive file ID.
            bucket: Unused for Drive; ignored.

        Returns:
            Tuple of (ExternalArtifact dict, None).

        Raises:
            FileStorageProviderError: When the Drive API call fails.
        """
        def _call() -> None:
            try:
                service = self._get_service()
                service.files().delete(fileId=file_id).execute()
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Google Drive delete_file error for id={file_id!r}: {exc}"
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
            raw_payload={"file_id": file_id},
            resource_type="file",
            provenance={"provider": "google_drive"},
        )
        logger.info("Google Drive delete_file: id=%r", file_id)
        return artifact.model_dump(mode="json"), None

    async def _get_metadata(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Get Google Drive file metadata without downloading content.

        Args:
            file_id: Drive file ID.
            bucket: Unused for Drive; ignored.

        Returns:
            Tuple of (ExternalArtifact dict with size/content_type, None).

        Raises:
            FileStorageProviderError: When the Drive API call fails.
        """
        def _call() -> dict:
            try:
                service = self._get_service()
                return service.files().get(
                    fileId=file_id,
                    fields="id,name,size,mimeType,webViewLink",
                ).execute()
            except Exception as exc:
                raise FileStorageProviderError(
                    f"Google Drive get_metadata error for id={file_id!r}: {exc}"
                ) from exc

        file = await asyncio.get_running_loop().run_in_executor(None, _call)

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=file.get("name", file_id),
            path=None,
            size_bytes=int(file["size"]) if file.get("size") else None,
            content_type=file.get("mimeType"),
            url=file.get("webViewLink"),
            content=None,
            raw_payload=file,
            resource_type="file",
            provenance={"provider": "google_drive"},
        )
        logger.info(
            "Google Drive get_metadata: id=%r name=%r",
            file_id, file.get("name"),
        )
        return artifact.model_dump(mode="json"), None
