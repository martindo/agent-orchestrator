"""Dropbox file storage connector provider.

Uses the Dropbox API v2 (HTTPS endpoints) to list, search, and download
files from a Dropbox account or team namespace.

Requires a Dropbox OAuth2 access token (long-lived or short-lived with
refresh token support).

Usage::

    provider = DropboxFileStorageProvider(access_token="sl....")

Environment variables::

    DROPBOX_ACCESS_TOKEN        Long-lived access token
    DROPBOX_REFRESH_TOKEN       (optional) Refresh token for short-lived tokens
    DROPBOX_APP_KEY             (optional) App key for token refresh
    DROPBOX_APP_SECRET          (optional) App secret for token refresh
"""
from __future__ import annotations

import logging

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import (
    MAX_CONTENT_BYTES,
    BaseFileStorageProvider,
    FileStorageProviderError,
)

logger = logging.getLogger(__name__)

_API_BASE = "https://api.dropboxapi.com/2"
_CONTENT_BASE = "https://content.dropboxapi.com/2"
_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/yaml")


def _is_text_mime(mime_type: str) -> bool:
    return any(mime_type.startswith(p) for p in _TEXT_MIME_PREFIXES)


class DropboxFileStorageProvider(BaseFileStorageProvider):
    """Dropbox file storage connector provider (API v2)."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None = None,
        app_key: str | None = None,
        app_secret: str | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("DropboxFileStorageProvider requires a non-empty access_token")
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._app_key = app_key
        self._app_secret = app_secret

    @classmethod
    def from_env(cls) -> "DropboxFileStorageProvider | None":
        """Create an instance from environment variables.

        Required: ``DROPBOX_ACCESS_TOKEN``
        Optional: ``DROPBOX_REFRESH_TOKEN``, ``DROPBOX_APP_KEY``, ``DROPBOX_APP_SECRET``

        Returns None if the access token is not set.
        """
        import os
        token = os.environ.get("DROPBOX_ACCESS_TOKEN", "")
        if not token:
            return None
        return cls(
            access_token=token,
            refresh_token=os.environ.get("DROPBOX_REFRESH_TOKEN") or None,
            app_key=os.environ.get("DROPBOX_APP_KEY") or None,
            app_secret=os.environ.get("DROPBOX_APP_SECRET") or None,
        )

    @property
    def provider_id(self) -> str:
        return "file_storage.dropbox"

    @property
    def display_name(self) -> str:
        return "Dropbox"

    def is_available(self) -> bool:
        return bool(self._access_token)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    async def _list_folder(
        self,
        folder_id: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List contents of a Dropbox folder.

        Args:
            folder_id: Dropbox path string (e.g. "/Documents"). None or "" lists root.
            limit: Maximum number of items to return.

        Returns:
            Tuple of (payload dict with items list, None).

        Raises:
            FileStorageProviderError: When the Dropbox API call fails.
        """
        path = folder_id or ""
        # Dropbox root must be empty string, not "/"
        if path == "/":
            path = ""

        body: dict = {"path": path, "limit": min(limit, 2000), "recursive": False}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{_API_BASE}/files/list_folder",
                    json=body,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data: dict = resp.json()
        except httpx.HTTPError as exc:
            raise FileStorageProviderError(f"Dropbox list_folder error: {exc}") from exc

        items = self._parse_entries(
            data.get("entries", []),
            provenance={"folder_id": folder_id, "provider": "dropbox"},
        )
        logger.info("Dropbox list_folder: path=%r items=%d", path, len(items))
        return {"folder_id": folder_id, "total_count": len(items), "items": items}, None

    async def _search_files(
        self,
        query: str,
        scope: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Search Dropbox files by name and content.

        Args:
            query: Full-text search query.
            scope: Optional Dropbox path to restrict search.
            limit: Maximum number of results.

        Returns:
            Tuple of (payload dict with items list, None).

        Raises:
            FileStorageProviderError: When the Dropbox API call fails.
        """
        options: dict = {"max_results": min(limit, 1000)}
        if scope:
            options["path"] = scope

        body = {"query": query, "options": options}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{_API_BASE}/files/search_v2",
                    json=body,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data: dict = resp.json()
        except httpx.HTTPError as exc:
            raise FileStorageProviderError(f"Dropbox search_files error: {exc}") from exc

        raw_entries = [
            match.get("metadata", {}).get("metadata", {})
            for match in data.get("matches", [])
        ]
        items = self._parse_entries(
            raw_entries,
            provenance={"query": query, "scope": scope, "provider": "dropbox"},
        )
        logger.info("Dropbox search_files: query=%r scope=%r results=%d", query, scope, len(items))
        return {"query": query, "scope": scope, "total_count": len(items), "items": items}, None

    async def _fetch_file(
        self,
        file_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Download a Dropbox file and return its content.

        Text files are decoded to UTF-8. Binary files have content=None.
        The file_id is the Dropbox path (e.g. "/reports/q1.txt") or id: prefix.

        Args:
            file_id: Dropbox file path or id:xxxx identifier.

        Returns:
            Tuple of (ExternalArtifact dict, None).

        Raises:
            FileStorageProviderError: When the Dropbox API call fails.
        """
        import json as _json

        path_arg = file_id if file_id.startswith("id:") else file_id
        dropbox_api_arg = _json.dumps({"path": path_arg})

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{_CONTENT_BASE}/files/download",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Dropbox-API-Arg": dropbox_api_arg,
                    },
                    content=b"",
                )
                resp.raise_for_status()
                api_result: dict = _json.loads(resp.headers.get("dropbox-api-result", "{}"))
                raw_bytes: bytes = resp.content[:MAX_CONTENT_BYTES]
        except httpx.HTTPError as exc:
            raise FileStorageProviderError(
                f"Dropbox fetch_file error for path={file_id!r}: {exc}"
            ) from exc

        mime_type = api_result.get("media_info", {}).get("metadata", {}).get(".tag")
        if not mime_type:
            name_lower = (api_result.get("name") or file_id).lower()
            mime_type = _guess_mime(name_lower)

        content: str | None = None
        if _is_text_mime(mime_type):
            content = raw_bytes.decode("utf-8", errors="replace")

        path_display: str = api_result.get("path_display", file_id)
        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=api_result.get("id", file_id),
            name=api_result.get("name", path_display.rsplit("/", 1)[-1]),
            path=path_display,
            content=content,
            mime_type=mime_type,
            size_bytes=api_result.get("size"),
            url=None,
            raw_payload=api_result,
            resource_type="file",
            provenance={"provider": "dropbox"},
        )
        logger.info(
            "Dropbox fetch_file: path=%r name=%r size=%s",
            path_display, api_result.get("name"), api_result.get("size"),
        )
        return artifact.model_dump(mode="json"), None

    async def _fetch_metadata(
        self,
        file_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve Dropbox file or folder metadata without downloading content.

        Args:
            file_id: Dropbox path or id:xxxx identifier.

        Returns:
            Tuple of (ExternalArtifact dict with content=None, None).

        Raises:
            FileStorageProviderError: When the Dropbox API call fails.
        """
        body = {"path": file_id}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{_API_BASE}/files/get_metadata",
                    json=body,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data: dict = resp.json()
        except httpx.HTTPError as exc:
            raise FileStorageProviderError(
                f"Dropbox fetch_metadata error for path={file_id!r}: {exc}"
            ) from exc

        is_folder = data.get(".tag") == "folder"
        path_display: str = data.get("path_display", file_id)
        name_lower = (data.get("name") or path_display).lower()
        mime_type = "application/x-directory" if is_folder else _guess_mime(name_lower)

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=data.get("id", file_id),
            name=data.get("name", path_display.rsplit("/", 1)[-1]),
            path=path_display,
            content=None,
            mime_type=mime_type,
            size_bytes=data.get("size"),
            url=None,
            raw_payload=data,
            resource_type="folder" if is_folder else "file",
            provenance={"provider": "dropbox"},
            is_folder=is_folder,
        )
        logger.info(
            "Dropbox fetch_metadata: path=%r name=%r", path_display, data.get("name")
        )
        return artifact.model_dump(mode="json"), None

    def _parse_entries(self, entries: list[dict], provenance: dict) -> list[dict]:
        """Convert Dropbox API list_folder entries to ExternalArtifact dicts."""
        results: list[dict] = []
        for entry in entries:
            if not entry:
                continue
            tag = entry.get(".tag", "file")
            is_folder = tag == "folder"
            path_display: str = entry.get("path_display", "")
            name_lower = (entry.get("name") or path_display).lower()
            mime_type = "application/x-directory" if is_folder else _guess_mime(name_lower)

            artifact = self._make_file_artifact(
                provider=self.provider_id,
                connector_id=self.provider_id,
                file_id=entry.get("id", path_display),
                name=entry.get("name", path_display.rsplit("/", 1)[-1]),
                path=path_display,
                content=None,
                mime_type=mime_type,
                size_bytes=entry.get("size"),
                url=None,
                raw_payload=entry,
                resource_type="folder" if is_folder else "file",
                provenance=provenance,
                is_folder=is_folder,
            )
            results.append(artifact.model_dump(mode="json"))
        return results


def _guess_mime(filename: str) -> str:
    """Guess MIME type from a filename extension."""
    ext_map: dict[str, str] = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xml": "application/xml",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".html": "text/html",
        ".htm": "text/html",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".zip": "application/zip",
    }
    for ext, mime in ext_map.items():
        if filename.endswith(ext):
            return mime
    return "application/octet-stream"
