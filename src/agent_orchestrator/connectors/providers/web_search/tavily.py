"""Tavily search connector provider.

Tavily is optimized for AI agents — returns cleaned, structured results.
Primary / preferred provider for production use.
"""
from __future__ import annotations

import logging

import httpx

from ...models import ConnectorCostInfo
from ...normalized import SearchResultItem
from ._base import BaseWebSearchProvider, WebSearchProviderError

logger = logging.getLogger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_COST_BASIC = 0.004
_COST_ADVANCED = 0.008


class TavilySearchProvider(BaseWebSearchProvider):
    """Tavily-backed web search connector provider.

    Supports search(), fetch_page(), and extract_content() operations.
    Primary provider — uses Tavily's AI-optimized search index.
    """

    def __init__(self, api_key: str, search_depth: str = "basic") -> None:
        if not api_key:
            raise ValueError("TavilySearchProvider requires a non-empty api_key")
        self._api_key = api_key
        self._search_depth = search_depth

    @classmethod
    def from_env(cls) -> "TavilySearchProvider | None":
        """Create an instance from environment variables.

        Required env var: ``TAVILY_API_KEY``
        Optional env var: ``TAVILY_SEARCH_DEPTH`` (default: ``basic``)

        Returns None if ``TAVILY_API_KEY`` is not set.
        """
        import os
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return None
        depth = os.environ.get("TAVILY_SEARCH_DEPTH", "basic")
        return cls(api_key=api_key, search_depth=depth)

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "web_search.tavily"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Tavily Web Search"

    async def _search(
        self,
        query: str,
        limit: int,
        filters: dict,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Execute a Tavily search and return a normalized SearchResultArtifact dict.

        Args:
            query: Search query string.
            limit: Maximum number of results to return.
            filters: Optional filters including search_depth, include_domains,
                     exclude_domains.

        Returns:
            Tuple of (SearchResultArtifact dict, ConnectorCostInfo).

        Raises:
            WebSearchProviderError: When the Tavily API request fails.
        """
        body: dict = {
            "api_key": self._api_key,
            "query": query,
            "max_results": limit,
            "search_depth": filters.get("search_depth", self._search_depth),
            "include_answer": False,
            "include_raw_content": False,
        }
        if "include_domains" in filters:
            body["include_domains"] = filters["include_domains"]
        if "exclude_domains" in filters:
            body["exclude_domains"] = filters["exclude_domains"]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(_TAVILY_SEARCH_URL, json=body)
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise WebSearchProviderError(f"Tavily API error: {exc}") from exc

        raw_results: list[dict] = data.get("results", [])
        items = [
            SearchResultItem(
                rank=i,
                title=r.get("title", ""),
                snippet=r.get("content", ""),
                url=r.get("url"),
                score=r.get("score"),
                metadata={"published_date": r.get("published_date")},
            )
            for i, r in enumerate(raw_results)
        ]

        depth = body["search_depth"]
        unit_cost = _COST_ADVANCED if depth == "advanced" else _COST_BASIC
        cost_info = ConnectorCostInfo(
            estimated_cost=unit_cost,
            usage_units=float(len(items)),
            currency="USD",
            unit_label="results",
        )

        logger.info(
            "Tavily search: query=%r results=%d depth=%s cost=%.4f",
            query,
            len(items),
            depth,
            unit_cost,
        )

        payload = self._normalize_search(
            provider=self.provider_id,
            connector_id=self.provider_id,
            query=query,
            items=items,
        )
        return payload, cost_info
