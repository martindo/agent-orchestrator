"""Tests for web search connector providers: Tavily, SerpAPI, Brave."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorStatus,
)
from agent_orchestrator.connectors.registry import ConnectorProviderProtocol
from agent_orchestrator.connectors.providers.web_search.tavily import TavilySearchProvider
from agent_orchestrator.connectors.providers.web_search.serpapi import SerpAPISearchProvider
from agent_orchestrator.connectors.providers.web_search.brave import BraveSearchProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tavily_provider() -> TavilySearchProvider:
    return TavilySearchProvider(api_key="test-tavily-key")


@pytest.fixture
def serpapi_provider() -> SerpAPISearchProvider:
    return SerpAPISearchProvider(api_key="test-serpapi-key")


@pytest.fixture
def brave_provider() -> BraveSearchProvider:
    return BraveSearchProvider(api_key="test-brave-key")


def _make_search_request(query: str = "test query", limit: int = 2) -> ConnectorInvocationRequest:
    return ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="search",
        parameters={"query": query, "limit": limit},
    )


def _make_fetch_request(url: str = "https://example.com/page") -> ConnectorInvocationRequest:
    return ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="fetch_page",
        parameters={"url": url},
    )


def _make_extract_request(url: str = "https://example.com/page") -> ConnectorInvocationRequest:
    return ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="extract_content",
        parameters={"url": url},
    )


def _make_unknown_request() -> ConnectorInvocationRequest:
    return ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="nonexistent_op",
        parameters={},
    )


def _make_mock_http_client(post_response=None, get_response=None) -> AsyncMock:
    """Build an async context-manager mock for httpx.AsyncClient."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    if post_response is not None:
        mock_client.post = AsyncMock(return_value=post_response)
    if get_response is not None:
        mock_client.get = AsyncMock(return_value=get_response)
    return mock_client


def _make_search_response(json_data: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data
    return response


def _make_fetch_response(text: str = "<html>hello</html>") -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.text = text
    response.headers = {"content-type": "text/html"}
    return response


def _make_error_response() -> MagicMock:
    response = MagicMock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        message="500 Server Error",
        request=MagicMock(),
        response=MagicMock(),
    )
    response.json.return_value = {}
    response.text = ""
    response.headers = {}
    return response


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_tavily_implements_protocol(tavily_provider: TavilySearchProvider) -> None:
    assert isinstance(tavily_provider, ConnectorProviderProtocol)


def test_serpapi_implements_protocol(serpapi_provider: SerpAPISearchProvider) -> None:
    assert isinstance(serpapi_provider, ConnectorProviderProtocol)


def test_brave_implements_protocol(brave_provider: BraveSearchProvider) -> None:
    assert isinstance(brave_provider, ConnectorProviderProtocol)


# ---------------------------------------------------------------------------
# Provider IDs
# ---------------------------------------------------------------------------


def test_tavily_provider_id(tavily_provider: TavilySearchProvider) -> None:
    assert tavily_provider.provider_id == "web_search.tavily"


def test_serpapi_provider_id(serpapi_provider: SerpAPISearchProvider) -> None:
    assert serpapi_provider.provider_id == "web_search.serpapi"


def test_brave_provider_id(brave_provider: BraveSearchProvider) -> None:
    assert brave_provider.provider_id == "web_search.brave"


# ---------------------------------------------------------------------------
# Constructor validation — empty api_key
# ---------------------------------------------------------------------------


def test_tavily_raises_on_empty_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        TavilySearchProvider(api_key="")


def test_serpapi_raises_on_empty_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        SerpAPISearchProvider(api_key="")


def test_brave_raises_on_empty_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        BraveSearchProvider(api_key="")


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


def test_tavily_is_available_with_key(tavily_provider: TavilySearchProvider) -> None:
    assert tavily_provider.is_available() is True


def test_serpapi_is_available_with_key(serpapi_provider: SerpAPISearchProvider) -> None:
    assert serpapi_provider.is_available() is True


def test_brave_is_available_with_key(brave_provider: BraveSearchProvider) -> None:
    assert brave_provider.is_available() is True


# ---------------------------------------------------------------------------
# Descriptor shape
# ---------------------------------------------------------------------------


def test_tavily_descriptor_shape(tavily_provider: TavilySearchProvider) -> None:
    desc = tavily_provider.get_descriptor()
    assert desc.provider_id == "web_search.tavily"
    assert desc.display_name == "Tavily Web Search"
    assert CapabilityType.SEARCH in desc.capability_types
    assert desc.auth_required is True
    assert desc.auth_type == "api_key"
    assert desc.version == "1.0"
    ops = [op.operation for op in desc.operations]
    assert "search" in ops
    assert "fetch_page" in ops
    assert "extract_content" in ops


def test_serpapi_descriptor_shape(serpapi_provider: SerpAPISearchProvider) -> None:
    desc = serpapi_provider.get_descriptor()
    assert desc.provider_id == "web_search.serpapi"
    assert desc.display_name == "SerpAPI Web Search"
    assert CapabilityType.SEARCH in desc.capability_types
    assert desc.auth_required is True
    ops = [op.operation for op in desc.operations]
    assert "search" in ops
    assert "fetch_page" in ops
    assert "extract_content" in ops


def test_brave_descriptor_shape(brave_provider: BraveSearchProvider) -> None:
    desc = brave_provider.get_descriptor()
    assert desc.provider_id == "web_search.brave"
    assert desc.display_name == "Brave Web Search"
    assert CapabilityType.SEARCH in desc.capability_types
    assert desc.auth_required is True
    ops = [op.operation for op in desc.operations]
    assert "search" in ops
    assert "fetch_page" in ops
    assert "extract_content" in ops


# ---------------------------------------------------------------------------
# Tavily — search normalization and cost tracking
# ---------------------------------------------------------------------------


async def test_tavily_search_normalizes(tavily_provider: TavilySearchProvider) -> None:
    fake_response = _make_search_response({
        "query": "test query",
        "results": [
            {"title": "Result 1", "url": "https://example.com/1", "content": "snippet 1", "score": 0.9},
            {"title": "Result 2", "url": "https://example.com/2", "content": "snippet 2", "score": 0.8},
        ],
    })
    mock_client = _make_mock_http_client(post_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.tavily.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(_make_search_request("test query", limit=2))

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload is not None
    assert result.payload["query"] == "test query"
    assert len(result.payload["results"]) == 2
    assert result.payload["total_count"] == 2


def test_tavily_result_items_shape(tavily_provider: TavilySearchProvider) -> None:
    """Ensure result items expose rank, title, url, snippet keys after normalization."""
    from agent_orchestrator.connectors.normalized import SearchResultItem

    item = SearchResultItem(rank=0, title="T", snippet="S", url="https://x.com", score=0.9)
    d = item.model_dump(mode="json")
    assert "rank" in d
    assert "title" in d
    assert "url" in d
    assert "snippet" in d


async def test_tavily_cost_info_basic(tavily_provider: TavilySearchProvider) -> None:
    fake_response = _make_search_response({
        "results": [
            {"title": "R1", "url": "https://x.com/1", "content": "s1", "score": 0.5},
        ],
    })
    mock_client = _make_mock_http_client(post_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.tavily.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(_make_search_request("query"))

    assert result.cost_info is not None
    assert result.cost_info.estimated_cost == 0.004
    assert result.cost_info.currency == "USD"
    assert result.cost_info.unit_label == "results"


async def test_tavily_cost_info_advanced() -> None:
    provider = TavilySearchProvider(api_key="key", search_depth="advanced")
    fake_response = _make_search_response({"results": []})
    mock_client = _make_mock_http_client(post_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.tavily.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await provider.execute(_make_search_request("query"))

    assert result.cost_info is not None
    assert result.cost_info.estimated_cost == 0.008


async def test_tavily_search_empty_results(tavily_provider: TavilySearchProvider) -> None:
    fake_response = _make_search_response({"results": []})
    mock_client = _make_mock_http_client(post_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.tavily.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(_make_search_request("noresults"))

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["results"] == []
    assert result.payload["total_count"] == 0


# ---------------------------------------------------------------------------
# SerpAPI — search normalization and cost tracking
# ---------------------------------------------------------------------------


async def test_serpapi_search_normalizes(serpapi_provider: SerpAPISearchProvider) -> None:
    fake_response = _make_search_response({
        "organic_results": [
            {"title": "Page A", "link": "https://a.com", "snippet": "about a", "position": 1, "displayed_link": "a.com"},
            {"title": "Page B", "link": "https://b.com", "snippet": "about b", "position": 2, "displayed_link": "b.com"},
        ],
    })
    mock_client = _make_mock_http_client(get_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.serpapi.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await serpapi_provider.execute(_make_search_request("test", limit=2))

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload is not None
    assert result.payload["query"] == "test"
    assert len(result.payload["results"]) == 2
    assert result.payload["total_count"] == 2
    assert result.payload["results"][0]["title"] == "Page A"
    assert result.payload["results"][0]["url"] == "https://a.com"


async def test_serpapi_cost_info(serpapi_provider: SerpAPISearchProvider) -> None:
    fake_response = _make_search_response({
        "organic_results": [
            {"title": "R", "link": "https://r.com", "snippet": "s", "position": 1},
        ],
    })
    mock_client = _make_mock_http_client(get_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.serpapi.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await serpapi_provider.execute(_make_search_request("query"))

    assert result.cost_info is not None
    assert result.cost_info.estimated_cost == 0.005
    assert result.cost_info.currency == "USD"


async def test_serpapi_search_empty_results(serpapi_provider: SerpAPISearchProvider) -> None:
    fake_response = _make_search_response({"organic_results": []})
    mock_client = _make_mock_http_client(get_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.serpapi.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await serpapi_provider.execute(_make_search_request("nothing"))

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["results"] == []


# ---------------------------------------------------------------------------
# Brave — search normalization and cost tracking
# ---------------------------------------------------------------------------


async def test_brave_search_normalizes(brave_provider: BraveSearchProvider) -> None:
    fake_response = _make_search_response({
        "web": {
            "results": [
                {"title": "Alpha", "url": "https://alpha.com", "description": "desc a"},
                {"title": "Beta", "url": "https://beta.com", "description": "desc b"},
            ]
        }
    })
    mock_client = _make_mock_http_client(get_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.brave.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await brave_provider.execute(_make_search_request("brave query", limit=2))

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload is not None
    assert result.payload["query"] == "brave query"
    assert len(result.payload["results"]) == 2
    assert result.payload["total_count"] == 2
    assert result.payload["results"][0]["title"] == "Alpha"
    assert result.payload["results"][0]["url"] == "https://alpha.com"


async def test_brave_cost_info(brave_provider: BraveSearchProvider) -> None:
    fake_response = _make_search_response({
        "web": {"results": [{"title": "X", "url": "https://x.com", "description": "d"}]}
    })
    mock_client = _make_mock_http_client(get_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.brave.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await brave_provider.execute(_make_search_request("query"))

    assert result.cost_info is not None
    assert result.cost_info.estimated_cost == 0.003
    assert result.cost_info.currency == "USD"


async def test_brave_search_missing_web_key(brave_provider: BraveSearchProvider) -> None:
    """Brave response without 'web' key should yield empty results gracefully."""
    fake_response = _make_search_response({})
    mock_client = _make_mock_http_client(get_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.brave.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await brave_provider.execute(_make_search_request("empty"))

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["results"] == []


# ---------------------------------------------------------------------------
# fetch_page — DocumentArtifact shape
# ---------------------------------------------------------------------------


async def test_tavily_fetch_page_returns_document_shape(
    tavily_provider: TavilySearchProvider,
) -> None:
    mock_response = _make_fetch_response("<html>content</html>")
    mock_client = _make_mock_http_client(get_response=mock_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search._base.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(
            _make_fetch_request("https://example.com/page")
        )

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload is not None
    assert result.payload["url"] == "https://example.com/page"
    assert "content" in result.payload
    assert "content_type" in result.payload


async def test_serpapi_fetch_page_returns_document_shape(
    serpapi_provider: SerpAPISearchProvider,
) -> None:
    mock_response = _make_fetch_response("<html>serpapi page</html>")
    mock_client = _make_mock_http_client(get_response=mock_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search._base.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await serpapi_provider.execute(
            _make_fetch_request("https://example.com/serp")
        )

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["url"] == "https://example.com/serp"
    assert "content" in result.payload
    assert "content_type" in result.payload


async def test_brave_fetch_page_returns_document_shape(
    brave_provider: BraveSearchProvider,
) -> None:
    mock_response = _make_fetch_response("<html>brave page</html>")
    mock_client = _make_mock_http_client(get_response=mock_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search._base.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await brave_provider.execute(
            _make_fetch_request("https://example.com/brave")
        )

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["url"] == "https://example.com/brave"
    assert "content" in result.payload


# ---------------------------------------------------------------------------
# extract_content — same DocumentArtifact shape as fetch_page
# ---------------------------------------------------------------------------


async def test_tavily_extract_content_returns_document_shape(
    tavily_provider: TavilySearchProvider,
) -> None:
    mock_response = _make_fetch_response("<article>text</article>")
    mock_client = _make_mock_http_client(get_response=mock_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search._base.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(
            _make_extract_request("https://example.com/article")
        )

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload is not None
    assert result.payload["url"] == "https://example.com/article"
    assert "content" in result.payload
    assert "content_type" in result.payload


async def test_serpapi_extract_content_returns_document_shape(
    serpapi_provider: SerpAPISearchProvider,
) -> None:
    mock_response = _make_fetch_response("<article>serpapi text</article>")
    mock_client = _make_mock_http_client(get_response=mock_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search._base.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await serpapi_provider.execute(
            _make_extract_request("https://example.com/serp-article")
        )

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["url"] == "https://example.com/serp-article"
    assert "content" in result.payload


async def test_brave_extract_content_returns_document_shape(
    brave_provider: BraveSearchProvider,
) -> None:
    mock_response = _make_fetch_response("<p>brave text</p>")
    mock_client = _make_mock_http_client(get_response=mock_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search._base.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await brave_provider.execute(
            _make_extract_request("https://example.com/brave-article")
        )

    assert result.status == ConnectorStatus.SUCCESS
    assert "content" in result.payload


# ---------------------------------------------------------------------------
# Unknown operation → NOT_FOUND
# ---------------------------------------------------------------------------


async def test_tavily_unknown_op_returns_not_found(
    tavily_provider: TavilySearchProvider,
) -> None:
    result = await tavily_provider.execute(_make_unknown_request())
    assert result.status == ConnectorStatus.NOT_FOUND
    assert result.error_message is not None
    assert "nonexistent_op" in result.error_message


async def test_serpapi_unknown_op_returns_not_found(
    serpapi_provider: SerpAPISearchProvider,
) -> None:
    result = await serpapi_provider.execute(_make_unknown_request())
    assert result.status == ConnectorStatus.NOT_FOUND


async def test_brave_unknown_op_returns_not_found(
    brave_provider: BraveSearchProvider,
) -> None:
    result = await brave_provider.execute(_make_unknown_request())
    assert result.status == ConnectorStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# HTTP errors → FAILURE
# ---------------------------------------------------------------------------


async def test_tavily_http_error_returns_failure(
    tavily_provider: TavilySearchProvider,
) -> None:
    error_response = _make_error_response()
    mock_client = _make_mock_http_client(post_response=error_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.tavily.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(_make_search_request("error"))

    assert result.status == ConnectorStatus.FAILURE
    assert result.error_message is not None


async def test_serpapi_http_error_returns_failure(
    serpapi_provider: SerpAPISearchProvider,
) -> None:
    error_response = _make_error_response()
    mock_client = _make_mock_http_client(get_response=error_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.serpapi.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await serpapi_provider.execute(_make_search_request("error"))

    assert result.status == ConnectorStatus.FAILURE
    assert result.error_message is not None


async def test_brave_http_error_returns_failure(
    brave_provider: BraveSearchProvider,
) -> None:
    error_response = _make_error_response()
    mock_client = _make_mock_http_client(get_response=error_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.brave.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await brave_provider.execute(_make_search_request("error"))

    assert result.status == ConnectorStatus.FAILURE
    assert result.error_message is not None


async def test_fetch_page_http_error_returns_failure(
    tavily_provider: TavilySearchProvider,
) -> None:
    error_response = _make_error_response()
    mock_client = _make_mock_http_client(get_response=error_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search._base.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(
            _make_fetch_request("https://broken.example.com")
        )

    assert result.status == ConnectorStatus.FAILURE


# ---------------------------------------------------------------------------
# Result duration is set
# ---------------------------------------------------------------------------


async def test_result_has_duration_ms(tavily_provider: TavilySearchProvider) -> None:
    fake_response = _make_search_response({"results": []})
    mock_client = _make_mock_http_client(post_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.tavily.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(_make_search_request("query"))

    assert result.duration_ms is not None
    assert result.duration_ms >= 0.0


# ---------------------------------------------------------------------------
# Provider and connector_id are set in results
# ---------------------------------------------------------------------------


async def test_result_provider_and_connector_id(
    tavily_provider: TavilySearchProvider,
) -> None:
    fake_response = _make_search_response({"results": []})
    mock_client = _make_mock_http_client(post_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.tavily.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await tavily_provider.execute(_make_search_request("q"))

    assert result.provider == "web_search.tavily"
    assert result.connector_id == "web_search.tavily"


async def test_brave_result_provider_and_connector_id(
    brave_provider: BraveSearchProvider,
) -> None:
    fake_response = _make_search_response({"web": {"results": []}})
    mock_client = _make_mock_http_client(get_response=fake_response)

    with patch(
        "agent_orchestrator.connectors.providers.web_search.brave.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await brave_provider.execute(_make_search_request("q"))

    assert result.provider == "web_search.brave"
    assert result.connector_id == "web_search.brave"


# ---------------------------------------------------------------------------
# Import from top-level providers package
# ---------------------------------------------------------------------------


def test_providers_package_exports() -> None:
    from agent_orchestrator.connectors.providers import (
        TavilySearchProvider,
        SerpAPISearchProvider,
        BraveSearchProvider,
    )

    assert TavilySearchProvider is not None
    assert SerpAPISearchProvider is not None
    assert BraveSearchProvider is not None
