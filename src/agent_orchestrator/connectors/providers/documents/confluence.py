"""Confluence documents connector provider.

Implements search_documents, get_document, and extract_section against the
Confluence REST API v1. Supports Confluence Cloud (api_token + email Basic auth)
and Confluence Server/DC (personal access token Bearer auth).
"""
from __future__ import annotations

import base64
import logging
import re
from urllib.parse import quote

import httpx

from ...models import ConnectorCostInfo, ExternalReference, CapabilityType
from ._base import BaseDocumentsProvider, DocumentsProviderError

logger = logging.getLogger(__name__)

_DEFAULT_EXPAND_SEARCH = "space,ancestors"
_DEFAULT_EXPAND_CONTENT = "body.storage,space,metadata.labels,ancestors"


class ConfluenceDocumentsProvider(BaseDocumentsProvider):
    """Confluence-backed documents connector provider.

    Supports search_documents(), get_document(), and extract_section().

    For Confluence Cloud:
        provider = ConfluenceDocumentsProvider(
            base_url="https://myorg.atlassian.net",
            api_token="ATATT...",
            email="user@example.com",
        )

    For Confluence Server / Data Center (PAT):
        provider = ConfluenceDocumentsProvider(
            base_url="https://confluence.internal",
            api_token="my-personal-access-token",
        )
    """

    def __init__(
        self,
        base_url: str,
        api_token: str,
        email: str | None = None,
        default_space: str | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("ConfluenceDocumentsProvider requires a non-empty base_url")
        if not api_token:
            raise ValueError("ConfluenceDocumentsProvider requires a non-empty api_token")
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._email = email
        self._default_space = default_space

    @classmethod
    def from_env(cls) -> "ConfluenceDocumentsProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``CONFLUENCE_BASE_URL``, ``CONFLUENCE_API_TOKEN``
        Optional env vars: ``CONFLUENCE_EMAIL``, ``CONFLUENCE_DEFAULT_SPACE``

        Returns None if required env vars are not set.
        """
        import os
        base_url = os.environ.get("CONFLUENCE_BASE_URL", "")
        api_token = os.environ.get("CONFLUENCE_API_TOKEN", "")
        if not base_url or not api_token:
            return None
        return cls(
            base_url=base_url,
            api_token=api_token,
            email=os.environ.get("CONFLUENCE_EMAIL") or None,
            default_space=os.environ.get("CONFLUENCE_DEFAULT_SPACE") or None,
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "documents.confluence"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Confluence Documents"

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the configured auth mode."""
        if self._email:
            credentials = f"{self._email}:{self._api_token}"
            encoded = base64.b64encode(credentials.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        return {"Authorization": f"Bearer {self._api_token}"}

    def _api_url(self, path: str) -> str:
        """Build a full Confluence REST API URL."""
        return f"{self._base_url}/wiki/rest/api{path}"

    async def _search_documents(
        self,
        query: str,
        scope: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Search Confluence using CQL and return a list of ExternalArtifact dicts.

        Args:
            query: CQL text search term (e.g. "authentication flow").
            scope: Optional Confluence space key to restrict results.
            limit: Maximum number of documents to return.

        Returns:
            Tuple of (payload dict with items list, None — no API cost).

        Raises:
            DocumentsProviderError: When the Confluence API request fails.
        """
        space_filter = f' AND space.key = "{scope}"' if scope else (
            f' AND space.key = "{self._default_space}"' if self._default_space else ""
        )
        cql = f'text ~ "{query}"{space_filter} ORDER BY relevance'
        params = {
            "cql": cql,
            "limit": limit,
            "expand": _DEFAULT_EXPAND_SEARCH,
        }
        headers = {**self._auth_headers(), "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url("/search"),
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise DocumentsProviderError(f"Confluence search error: {exc}") from exc

        results: list[dict] = data.get("results", [])
        items: list[dict] = []

        for result in results:
            content = result.get("content", {})
            doc_id: str = content.get("id", "")
            title: str = content.get("title", "")
            excerpt: str = result.get("excerpt", "")
            base_link: str = content.get("_links", {}).get("base", self._base_url)
            webui_path: str = content.get("_links", {}).get("webui", "")
            doc_url = f"{base_link}{webui_path}" if webui_path else None
            space_key: str = content.get("space", {}).get("key", "")

            refs: list[ExternalReference] = []
            if doc_url:
                refs.append(
                    ExternalReference(
                        provider=self.provider_id,
                        resource_type="confluence_page",
                        external_id=doc_id,
                        url=doc_url,
                        metadata={"space_key": space_key},
                    )
                )

            artifact = self._make_document_artifact(
                provider=self.provider_id,
                connector_id=self.provider_id,
                document_id=doc_id,
                title=title,
                content=excerpt,
                url=doc_url,
                content_type="text/plain",
                raw_payload=result,
                resource_type="document",
                provenance={"query": query, "scope": scope or space_key, "provider": "confluence"},
                references=refs,
            )
            items.append(artifact.model_dump(mode="json"))

        logger.info(
            "Confluence search_documents: query=%r scope=%r results=%d",
            query,
            scope,
            len(items),
        )

        payload = {
            "query": query,
            "scope": scope,
            "total_count": len(items),
            "items": items,
        }
        return payload, None

    async def _get_document(
        self,
        document_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve a Confluence page by its content ID.

        Args:
            document_id: Confluence content ID (numeric string, e.g. "123456").

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            DocumentsProviderError: When the Confluence API request fails.
        """
        params = {"expand": _DEFAULT_EXPAND_CONTENT}
        headers = {**self._auth_headers(), "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url(f"/content/{quote(document_id, safe='')}"),
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise DocumentsProviderError(
                f"Confluence get_document error for id={document_id!r}: {exc}"
            ) from exc

        title: str = data.get("title", "")
        body_storage: str = (
            data.get("body", {}).get("storage", {}).get("value", "")
        )
        base_link: str = data.get("_links", {}).get("base", self._base_url)
        webui_path: str = data.get("_links", {}).get("webui", "")
        doc_url = f"{base_link}{webui_path}" if webui_path else None
        space_key: str = data.get("space", {}).get("key", "")

        refs: list[ExternalReference] = []
        if doc_url:
            refs.append(
                ExternalReference(
                    provider=self.provider_id,
                    resource_type="confluence_page",
                    external_id=document_id,
                    url=doc_url,
                    metadata={"space_key": space_key},
                )
            )

        artifact = self._make_document_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            document_id=document_id,
            title=title,
            content=body_storage,
            url=doc_url,
            content_type="text/html",
            raw_payload=data,
            resource_type="document",
            provenance={"space_key": space_key, "provider": "confluence"},
            references=refs,
        )

        logger.info(
            "Confluence get_document: id=%r title=%r space=%r",
            document_id,
            title,
            space_key,
        )

        return artifact.model_dump(mode="json"), None

    async def _extract_section(
        self,
        document_id: str,
        selector: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Extract a named section from a Confluence page.

        Fetches the full document body and extracts the content fragment that
        follows the heading or anchor matching the selector string.

        Args:
            document_id: Confluence content ID.
            selector: Heading text or anchor name to locate the section.

        Returns:
            Tuple of (ExternalArtifact dict with resource_type="document_section", None).

        Raises:
            DocumentsProviderError: When the API request fails.
        """
        params = {"expand": _DEFAULT_EXPAND_CONTENT}
        headers = {**self._auth_headers(), "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url(f"/content/{quote(document_id, safe='')}"),
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise DocumentsProviderError(
                f"Confluence extract_section error for id={document_id!r}: {exc}"
            ) from exc

        title: str = data.get("title", "")
        body_storage: str = (
            data.get("body", {}).get("storage", {}).get("value", "")
        )
        base_link: str = data.get("_links", {}).get("base", self._base_url)
        webui_path: str = data.get("_links", {}).get("webui", "")
        doc_url = f"{base_link}{webui_path}" if webui_path else None
        space_key: str = data.get("space", {}).get("key", "")

        section_content = _extract_section_from_storage(body_storage, selector)

        artifact = self._make_document_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            document_id=document_id,
            title=f"{title} § {selector}",
            content=section_content,
            url=doc_url,
            content_type="text/html",
            raw_payload={"document_id": document_id, "selector": selector, "document_title": title},
            resource_type="document_section",
            provenance={
                "document_id": document_id,
                "selector": selector,
                "space_key": space_key,
                "provider": "confluence",
            },
            references=[
                ExternalReference(
                    provider=self.provider_id,
                    resource_type="confluence_page",
                    external_id=document_id,
                    url=doc_url,
                    metadata={"space_key": space_key},
                )
            ] if doc_url else [],
        )

        logger.info(
            "Confluence extract_section: id=%r selector=%r matched=%s",
            document_id,
            selector,
            section_content is not None,
        )

        return artifact.model_dump(mode="json"), None


def _extract_section_from_storage(body: str, selector: str) -> str | None:
    """Extract a section from Confluence storage-format markup.

    Searches for a heading tag (h1-h6) whose text content matches the selector
    (case-insensitive). Returns the markup between that heading and the next
    heading at the same or higher level, or the remainder of the body if no
    subsequent heading is found. Returns None if the selector is not found.

    Args:
        body: Confluence storage-format HTML string.
        selector: Section heading text to search for.

    Returns:
        Matched section HTML, or None if selector not found.
    """
    heading_pattern = re.compile(
        r"<h([1-6])[^>]*>(.*?)</h\1>",
        re.IGNORECASE | re.DOTALL,
    )

    for match in heading_pattern.finditer(body):
        heading_level = int(match.group(1))
        heading_text = re.sub(r"<[^>]+>", "", match.group(2))
        if selector.lower() in heading_text.lower():
            section_start = match.end()
            end_pattern = re.compile(
                rf"<h[1-{heading_level}][^>]*>",
                re.IGNORECASE,
            )
            end_match = end_pattern.search(body, section_start)
            section_end = end_match.start() if end_match else len(body)
            return body[section_start:section_end].strip()

    # No heading found — try anchor/id attribute match
    anchor_pattern = re.compile(
        rf'(?:id|name)="{re.escape(selector)}"',
        re.IGNORECASE,
    )
    anchor_match = anchor_pattern.search(body.lower())
    if anchor_match:
        return body[anchor_match.end():].strip() or None

    return None
