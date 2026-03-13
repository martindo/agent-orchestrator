"""SerpAPI (Google/Bing-backed) connector provider.

Uses SerpAPI to access Google, Bing, and other search engines.
Secondary / fallback provider.
"""
from __future__ import annotations

import logging

import httpx

from ...models import ConnectorCostInfo
from ...normalized import SearchResultItem
from ._base import BaseWebSearchProvider, WebSearchProviderError

logger = logging.getLogger(__name__)

_SERPAPI_SEARCH_URL = "https://serpapi.com/search"
_COST_PER_SEARCH = 0.005


class SerpAPISearchProvider(BaseWebSearchProvider):
    """SerpAPI-backed web search connector provider.

    Supports search(), fetch_page(), and extract_content() operations.
    Secondary provider — Google-backed results via SerpAPI.
    """

    def __init__(self, api_key: str, engine: str = "google") -> None:
        if not api_key:
            raise ValueError("SerpAPISearchProvider requires a non-empty api_key")
        self._api_key = api_key
        self._engine = engine

    @classmethod
    def from_env(cls) -> "SerpAPISearchProvider | None":
        """Create an instance from environment variables.

        Required env var: ``SERPAPI_API_KEY``
        Optional env var: ``SERPAPI_ENGINE`` (default: ``google``)

        Returns None if ``SERPAPI_API_KEY`` is not set.
        """
        import os
        api_key = os.environ.get("SERPAPI_API_KEY", "")
        if not api_key:
            return None
        engine = os.environ.get("SERPAPI_ENGINE", "google")
        return cls(api_key=api_key, engine=engine)

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "web_search.serpapi"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "SerpAPI Web Search"

    async def _search(
        self,
        query: str,
        limit: int,
        filters: dict,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Execute a SerpAPI search and return a normalized SearchResultArtifact dict.

        Args:
            query: Search query string.
            limit: Maximum number of results (capped at 100 by SerpAPI).
            filters: Optional filters including engine, gl (country), hl (language).

        Returns:
            Tuple of (SearchResultArtifact dict, ConnectorCostInfo).

        Raises:
            WebSearchProviderError: When the SerpAPI request fails.
        """
        params: dict = {
            "api_key": self._api_key,
            "q": query,
            "num": min(limit, 100),
            "engine": filters.get("engine", self._engine),
        }
        if "gl" in filters:
            params["gl"] = filters["gl"]
        if "hl" in filters:
            params["hl"] = filters["hl"]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(_SERPAPI_SEARCH_URL, params=params)
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise WebSearchProviderError(f"SerpAPI error: {exc}") from exc

        organic: list[dict] = data.get("organic_results", [])
        items = [
            SearchResultItem(
                rank=r.get("position", i + 1) - 1,
                title=r.get("title", ""),
                snippet=r.get("snippet", ""),
                url=r.get("link"),
                score=None,
                metadata={"displayed_link": r.get("displayed_link")},
            )
            for i, r in enumerate(organic)
        ]

        cost_info = ConnectorCostInfo(
            estimated_cost=_COST_PER_SEARCH,
            usage_units=float(len(items)),
            currency="USD",
            unit_label="results",
        )

        logger.info(
            "SerpAPI search: query=%r results=%d engine=%s",
            query,
            len(items),
            params["engine"],
        )

        payload = self._normalize_search(
            provider=self.provider_id,
            connector_id=self.provider_id,
            query=query,
            items=items,
        )
        return payload, cost_info
