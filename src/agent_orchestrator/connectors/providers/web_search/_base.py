"""Shared base for web search connector providers."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

import httpx

from ...models import (
    CapabilityType,
    ConnectorCostInfo,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorStatus,
)
from ...normalized import DocumentArtifact, SearchResultArtifact, SearchResultItem

logger = logging.getLogger(__name__)

_SEARCH_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="search",
        description="Execute a web search query",
        capability_type=CapabilityType.SEARCH,
        read_only=True,
        required_parameters=["query"],
        optional_parameters=["limit", "filters"],
    ),
    ConnectorOperationDescriptor(
        operation="fetch_page",
        description="Fetch and return the content of a URL",
        capability_type=CapabilityType.SEARCH,
        read_only=True,
        required_parameters=["url"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="extract_content",
        description="Extract structured text content from a URL",
        capability_type=CapabilityType.SEARCH,
        read_only=True,
        required_parameters=["url"],
        optional_parameters=[],
    ),
]

_FETCH_TIMEOUT = 15.0
_DEFAULT_LIMIT = 10


class WebSearchProviderError(Exception):
    """Raised when a web search provider encounters an unrecoverable error."""


class BaseWebSearchProvider(ABC):
    """Abstract base with common execute() dispatch for web search providers.

    Subclasses implement _search(); fetch_page is handled here via httpx.
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.SEARCH],
            operations=_SEARCH_OPS,
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
            if op == "search":
                payload, cost_info = await self._search(
                    query=params["query"],
                    limit=int(params.get("limit", _DEFAULT_LIMIT)),
                    filters=dict(params.get("filters", {})),
                )
            elif op in ("fetch_page", "extract_content"):
                payload, cost_info = await self._fetch_page(url=params["url"])
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
        except WebSearchProviderError as exc:
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
    async def _search(
        self,
        query: str,
        limit: int,
        filters: dict,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    async def _fetch_page(self, url: str) -> tuple[dict, ConnectorCostInfo | None]:
        """Fetch raw page content from a URL using httpx.

        Args:
            url: The URL to retrieve.

        Returns:
            Tuple of (DocumentArtifact dict, None) — fetch has no API cost.

        Raises:
            WebSearchProviderError: When the HTTP request fails.
        """
        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT, follow_redirects=True
            ) as client:
                response = await client.get(
                    url, headers={"User-Agent": "AgentOrchestrator/1.0"}
                )
                response.raise_for_status()
                content = response.text
                content_type = response.headers.get("content-type", "text/html")
        except httpx.HTTPError as exc:
            raise WebSearchProviderError(f"Failed to fetch {url}: {exc}") from exc

        artifact = DocumentArtifact(
            source_connector=self.provider_id,
            provider=self.provider_id,
            capability_type=CapabilityType.SEARCH,
            url=url,
            content=content,
            content_type=content_type,
            size_bytes=len(content.encode()),
        )
        return artifact.model_dump(mode="json"), None

    @staticmethod
    def _normalize_search(
        provider: str,
        connector_id: str,
        query: str,
        items: list[SearchResultItem],
    ) -> dict:
        """Build a SearchResultArtifact dict from a list of SearchResultItems.

        Args:
            provider: Provider ID string.
            connector_id: Connector ID string (typically same as provider).
            query: Original search query string.
            items: Ordered list of result items.

        Returns:
            Dict representation of a SearchResultArtifact.
        """
        artifact = SearchResultArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.SEARCH,
            query=query,
            results=items,
            total_count=len(items),
        )
        return artifact.model_dump(mode="json")
