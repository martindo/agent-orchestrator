"""Microsoft OneDrive file storage connector provider.

Uses the Microsoft Graph API v1.0 to list, search, and download files from
OneDrive Personal or OneDrive for Business (SharePoint-backed).

Two authentication modes are supported:

1. **Access token** — pass an already-obtained OAuth2 access token.
2. **Client credentials** — pass tenant_id, client_id, and client_secret for
   application-level access (requires ``msal`` package).

Usage::

    # Access token
    provider = OneDriveFileStorageProvider(access_token="eyJ0...")

    # App credentials (requires msal)
    provider = OneDriveFileStorageProvider(
        tenant_id="...",
        client_id="...",
        client_secret="...",
    )

Environment variables::

    ONEDRIVE_ACCESS_TOKEN                     (OAuth2 token)
    ONEDRIVE_TENANT_ID, ONEDRIVE_CLIENT_ID,
    ONEDRIVE_CLIENT_SECRET                    (app credentials via MSAL)
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

_GRAPH_API = "https://graph.microsoft.com/v1.0"
_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/yaml")
_FILE_SELECT = "id,name,file,folder,size,webUrl,parentReference,lastModifiedDateTime"


def _is_text_mime(mime_type: str) -> bool:
    return any(mime_type.startswith(p) for p in _TEXT_MIME_PREFIXES)


class OneDriveFileStorageProvider(BaseFileStorageProvider):
    """Microsoft OneDrive file storage connector provider (Graph API)."""

    def __init__(
        self,
        access_token: str | None = None,
        tenant_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        drive_id: str | None = None,
    ) -> None:
        if not access_token and not (tenant_id and client_id and client_secret):
            raise ValueError(
                "OneDriveFileStorageProvider requires either access_token "
                "or (tenant_id + client_id + client_secret)"
            )
        self._access_token = access_token
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._drive_id = drive_id
        self._cached_token: str | None = None

    @classmethod
    def from_env(cls) -> "OneDriveFileStorageProvider | None":
        """Create an instance from environment variables.

        Checks ``ONEDRIVE_ACCESS_TOKEN`` first, then app credential env vars.

        Returns None if neither set is available.
        """
        import os
        token = os.environ.get("ONEDRIVE_ACCESS_TOKEN", "")
        if token:
            return cls(
                access_token=token,
                drive_id=os.environ.get("ONEDRIVE_DRIVE_ID") or None,
            )
        tenant_id = os.environ.get("ONEDRIVE_TENANT_ID", "")
        client_id = os.environ.get("ONEDRIVE_CLIENT_ID", "")
        client_secret = os.environ.get("ONEDRIVE_CLIENT_SECRET", "")
        if tenant_id and client_id and client_secret:
            return cls(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
                drive_id=os.environ.get("ONEDRIVE_DRIVE_ID") or None,
            )
        return None

    @property
    def provider_id(self) -> str:
        return "file_storage.onedrive"

    @property
    def display_name(self) -> str:
        return "Microsoft OneDrive"

    def is_available(self) -> bool:
        return bool(
            self._access_token
            or (self._tenant_id and self._client_id and self._client_secret)
        )

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        if self._cached_token:
            return self._cached_token
        return self._acquire_app_token()

    def _acquire_app_token(self) -> str:
        """Acquire an app-level token via MSAL client credentials flow."""
        try:
            import msal  # type: ignore[import-untyped]
        except ImportError as exc:
            raise FileStorageProviderError(
                "msal is required for client-credentials auth. "
                "Install it with: pip install msal"
            ) from exc

        app = msal.ConfidentialClientApplication(
            self._client_id,
            authority=f"https://login.microsoftonline.com/{self._tenant_id}",
            client_credential=self._client_secret,
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "unknown"))
            raise FileStorageProviderError(f"MSAL token acquisition failed: {error}")
        self._cached_token = result["access_token"]
        return self._cached_token  # type: ignore[return-value]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Accept": "application/json",
        }

    def _drive_root(self) -> str:
        """Return the Graph API drive root path."""
        if self._drive_id:
            return f"{_GRAPH_API}/drives/{self._drive_id}"
        return f"{_GRAPH_API}/me/drive"

    async def _list_folder(
        self,
        folder_id: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List children of a OneDrive folder.

        Args:
            folder_id: Drive item ID for the folder. None lists the root.
            limit: Maximum number of items to return.

        Returns:
            Tuple of (payload dict with items list, None).

        Raises:
            FileStorageProviderError: When the Graph API call fails.
        """
        if folder_id:
            url = f"{self._drive_root()}/items/{folder_id}/children"
        else:
            url = f"{self._drive_root()}/root/children"

        params = {
            "$select": _FILE_SELECT,
            "$top": min(limit, 1000),
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params, headers=self._headers())
                resp.raise_for_status()
                data: dict = resp.json()
        except httpx.HTTPError as exc:
            raise FileStorageProviderError(f"OneDrive list_folder error: {exc}") from exc

        items = self._parse_items(
            data.get("value", []),
            provenance={"folder_id": folder_id, "provider": "onedrive"},
        )
        logger.info("OneDrive list_folder: folder=%r items=%d", folder_id, len(items))
        return {"folder_id": folder_id, "total_count": len(items), "items": items}, None

    async def _search_files(
        self,
        query: str,
        scope: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Search OneDrive using the Graph search endpoint.

        Args:
            query: Search term (full-text search across file names and content).
            scope: Optional folder item ID to restrict the search scope.
            limit: Maximum number of results.

        Returns:
            Tuple of (payload dict with items list, None).

        Raises:
            FileStorageProviderError: When the Graph API call fails.
        """
        if scope:
            url = f"{self._drive_root()}/items/{scope}/search(q='{query}')"
        else:
            url = f"{self._drive_root()}/root/search(q='{query}')"

        params = {"$select": _FILE_SELECT, "$top": min(limit, 1000)}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params, headers=self._headers())
                resp.raise_for_status()
                data: dict = resp.json()
        except httpx.HTTPError as exc:
            raise FileStorageProviderError(f"OneDrive search_files error: {exc}") from exc

        items = self._parse_items(
            data.get("value", []),
            provenance={"query": query, "scope": scope, "provider": "onedrive"},
        )
        logger.info("OneDrive search_files: query=%r scope=%r results=%d", query, scope, len(items))
        return {"query": query, "scope": scope, "total_count": len(items), "items": items}, None

    async def _fetch_file(
        self,
        file_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Download a OneDrive file and return its content.

        Text files (text/*, JSON, XML) are decoded. Binary files have content=None.

        Args:
            file_id: Drive item ID.

        Returns:
            Tuple of (ExternalArtifact dict, None).

        Raises:
            FileStorageProviderError: When the Graph API call fails.
        """
        meta = await self._get_item_meta(file_id)
        mime_type: str = meta.get("file", {}).get("mimeType", "application/octet-stream")
        content: str | None = None

        if _is_text_mime(mime_type):
            download_url = meta.get("@microsoft.graph.downloadUrl") or (
                f"{self._drive_root()}/items/{file_id}/content"
            )
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    if "@microsoft.graph.downloadUrl" in meta:
                        resp = await client.get(download_url)
                    else:
                        resp = await client.get(download_url, headers=self._headers())
                    resp.raise_for_status()
                    content = resp.content[:MAX_CONTENT_BYTES].decode("utf-8", errors="replace")
            except httpx.HTTPError as exc:
                raise FileStorageProviderError(
                    f"OneDrive fetch_file download error for id={file_id!r}: {exc}"
                ) from exc

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=meta.get("name"),
            path=meta.get("parentReference", {}).get("path"),
            content=content,
            mime_type=mime_type,
            size_bytes=meta.get("size"),
            url=meta.get("webUrl"),
            raw_payload=meta,
            resource_type="file",
            provenance={"provider": "onedrive"},
            references=self._make_refs(file_id, meta),
        )
        logger.info("OneDrive fetch_file: id=%r name=%r", file_id, meta.get("name"))
        return artifact.model_dump(mode="json"), None

    async def _fetch_metadata(
        self,
        file_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve OneDrive item metadata without downloading content.

        Args:
            file_id: Drive item ID.

        Returns:
            Tuple of (ExternalArtifact dict with content=None, None).

        Raises:
            FileStorageProviderError: When the Graph API call fails.
        """
        meta = await self._get_item_meta(file_id)
        is_folder = "folder" in meta
        mime_type = (
            "application/x-directory"
            if is_folder
            else meta.get("file", {}).get("mimeType", "application/octet-stream")
        )
        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=meta.get("name"),
            path=meta.get("parentReference", {}).get("path"),
            content=None,
            mime_type=mime_type,
            size_bytes=meta.get("size"),
            url=meta.get("webUrl"),
            raw_payload=meta,
            resource_type="folder" if is_folder else "file",
            provenance={"provider": "onedrive"},
            is_folder=is_folder,
            references=self._make_refs(file_id, meta),
        )
        logger.info("OneDrive fetch_metadata: id=%r name=%r", file_id, meta.get("name"))
        return artifact.model_dump(mode="json"), None

    async def _get_item_meta(self, file_id: str) -> dict:
        """Fetch item metadata from the Graph API."""
        url = f"{self._drive_root()}/items/{file_id}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    url,
                    params={"$select": _FILE_SELECT + ",@microsoft.graph.downloadUrl"},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise FileStorageProviderError(
                f"OneDrive get_item_meta error for id={file_id!r}: {exc}"
            ) from exc

    def _parse_items(self, raw_items: list[dict], provenance: dict) -> list[dict]:
        """Convert a list of Graph API drive items to ExternalArtifact dicts."""
        results: list[dict] = []
        for item in raw_items:
            is_folder = "folder" in item
            mime_type = (
                "application/x-directory"
                if is_folder
                else item.get("file", {}).get("mimeType", "application/octet-stream")
            )
            artifact = self._make_file_artifact(
                provider=self.provider_id,
                connector_id=self.provider_id,
                file_id=item.get("id"),
                name=item.get("name"),
                path=item.get("parentReference", {}).get("path"),
                content=None,
                mime_type=mime_type,
                size_bytes=item.get("size"),
                url=item.get("webUrl"),
                raw_payload=item,
                resource_type="folder" if is_folder else "file",
                provenance=provenance,
                is_folder=is_folder,
            )
            results.append(artifact.model_dump(mode="json"))
        return results

    def _make_refs(self, file_id: str, meta: dict) -> list[ExternalReference]:
        web_url = meta.get("webUrl")
        if not web_url:
            return []
        return [
            ExternalReference(
                provider=self.provider_id,
                resource_type="onedrive_item",
                external_id=file_id,
                url=web_url,
                metadata={"name": meta.get("name", "")},
            )
        ]
