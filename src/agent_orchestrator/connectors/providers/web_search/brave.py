"""Brave Search connector provider.

Uses Brave's independent search index.
Tertiary / privacy-preserving fallback provider.
"""
from __future__ import annotations

import logging

import httpx

from ...models import ConnectorCostInfo
from ...normalized import SearchResultItem
from ._base import BaseWebSearchProvider, WebSearchProviderError

logger = logging.getLogger(__name__)

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_COST_PER_SEARCH = 0.003
_MAX_COUNT = 20  # Brave API max per request


class BraveSearchProvider(BaseWebSearchProvider):
    """Brave-backed web search connector provider.

    Supports search(), fetch_page(), and extract_content() operations.
    Tertiary provider — independent index, privacy-focused.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("BraveSearchProvider requires a non-empty api_key")
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "BraveSearchProvider | None":
        """Create an instance from environment variables.

        Required env var: ``BRAVE_API_KEY``

        Returns None if ``BRAVE_API_KEY`` is not set.
        """
        import os
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return None
        return cls(api_key=api_key)

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "web_search.brave"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Brave Web Search"

    async def _search(
        self,
        query: str,
        limit: int,
        filters: dict,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Execute a Brave Search query and return a normalized SearchResultArtifact dict.

        Args:
            query: Search query string.
            limit: Maximum number of results (capped at 20 by Brave API).
            filters: Optional filters including offset, country, search_lang, safesearch.

        Returns:
            Tuple of (SearchResultArtifact dict, ConnectorCostInfo).

        Raises:
            WebSearchProviderError: When the Brave API request fails.
        """
        params: dict = {
            "q": query,
            "count": min(limit, _MAX_COUNT),
        }
        for field in ("offset", "country", "search_lang", "safesearch"):
            if field in filters:
                params[field] = filters[field]

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    _BRAVE_SEARCH_URL, params=params, headers=headers
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise WebSearchProviderError(f"Brave Search API error: {exc}") from exc

        web: dict = data.get("web", {})
        raw_results: list[dict] = web.get("results", [])
        items = [
            SearchResultItem(
                rank=i,
                title=r.get("title", ""),
                snippet=r.get("description", ""),
                url=r.get("url"),
                score=None,
                metadata={
                    "age": r.get("age"),
                    "language": r.get("language"),
                    "page_age": r.get("page_age"),
                },
            )
            for i, r in enumerate(raw_results)
        ]

        cost_info = ConnectorCostInfo(
            estimated_cost=_COST_PER_SEARCH,
            usage_units=float(len(items)),
            currency="USD",
            unit_label="results",
        )

        logger.info(
            "Brave search: query=%r results=%d",
            query,
            len(items),
        )

        payload = self._normalize_search(
            provider=self.provider_id,
            connector_id=self.provider_id,
            query=query,
            items=items,
        )
        return payload, cost_info
