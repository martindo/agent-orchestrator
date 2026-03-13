"""Tests for the documents capability connector providers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorStatus,
    ExternalArtifact,
    ExternalReference,
)
from agent_orchestrator.connectors.providers.documents._base import (
    BaseDocumentsProvider,
    DocumentsProviderError,
)
from agent_orchestrator.connectors.providers.documents.confluence import (
    ConfluenceDocumentsProvider,
    _extract_section_from_storage,
)
from agent_orchestrator.connectors.registry import ConnectorProviderProtocol


# ---- Fixtures ----


@pytest.fixture
def confluence_provider() -> ConfluenceDocumentsProvider:
    return ConfluenceDocumentsProvider(
        base_url="https://example.atlassian.net",
        api_token="test-token",
        email="user@example.com",
    )


def _make_mock_client(response_json: dict) -> tuple[MagicMock, MagicMock]:
    """Build a mock httpx.AsyncClient and response for patching."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = response_json

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client, mock_response


_PATCH_TARGET = "agent_orchestrator.connectors.providers.documents.confluence.httpx.AsyncClient"

_FAKE_SEARCH_RESPONSE = {
    "results": [
        {
            "content": {
                "id": "111",
                "title": "Auth Flow",
                "type": "page",
                "space": {"key": "ENG"},
                "_links": {
                    "webui": "/wiki/spaces/ENG/pages/111",
                    "base": "https://example.atlassian.net",
                },
            },
            "excerpt": "This page describes the auth flow...",
        }
    ],
    "totalSize": 1,
}

_FAKE_DOCUMENT_RESPONSE = {
    "id": "123456",
    "title": "Architecture Guide",
    "type": "page",
    "body": {"storage": {"value": "<p>Hello world</p>"}},
    "space": {"key": "ARCH", "name": "Architecture"},
    "_links": {
        "webui": "/wiki/spaces/ARCH/pages/123456",
        "base": "https://example.atlassian.net",
    },
    "metadata": {"labels": {"results": []}},
}


# ---- 1. Constructor validation ----


def test_constructor_empty_api_token_raises():
    with pytest.raises(ValueError, match="api_token"):
        ConfluenceDocumentsProvider(
            base_url="https://example.atlassian.net",
            api_token="",
        )


def test_constructor_empty_base_url_raises():
    with pytest.raises(ValueError, match="base_url"):
        ConfluenceDocumentsProvider(
            base_url="",
            api_token="token",
        )


def test_constructor_valid_succeeds():
    provider = ConfluenceDocumentsProvider(
        base_url="https://example.atlassian.net",
        api_token="test-token",
    )
    assert provider.provider_id == "documents.confluence"


def test_constructor_strips_trailing_slash():
    provider = ConfluenceDocumentsProvider(
        base_url="https://example.atlassian.net/",
        api_token="test-token",
    )
    assert not provider._base_url.endswith("/")


# ---- 2. is_available() ----


def test_is_available_returns_true_when_token_set(confluence_provider):
    assert confluence_provider.is_available() is True


def test_is_available_returns_false_when_token_missing():
    provider = ConfluenceDocumentsProvider(
        base_url="https://example.atlassian.net",
        api_token="x",
    )
    # Forcibly clear the token to test the base logic
    object.__setattr__(provider, "_api_token", "")
    assert provider.is_available() is False


# ---- 3. Descriptor shape ----


def test_descriptor_shape(confluence_provider):
    descriptor = confluence_provider.get_descriptor()
    assert descriptor.provider_id == "documents.confluence"
    assert descriptor.display_name == "Confluence Documents"
    assert CapabilityType.DOCUMENTS in descriptor.capability_types
    ops = [op.operation for op in descriptor.operations]
    assert "search_documents" in ops
    assert "get_document" in ops
    assert "extract_section" in ops


def test_descriptor_auth_fields(confluence_provider):
    descriptor = confluence_provider.get_descriptor()
    assert descriptor.auth_required is True
    assert descriptor.auth_type == "api_key"
    assert descriptor.version == "1.0"


# ---- 4. Protocol structural check ----


def test_protocol_structural_check(confluence_provider):
    assert isinstance(confluence_provider, ConnectorProviderProtocol)


# ---- 5. search_documents normalization ----


@pytest.mark.asyncio
async def test_search_documents_normalization(confluence_provider):
    mock_client, _ = _make_mock_client(_FAKE_SEARCH_RESPONSE)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "auth flow"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["query"] == "auth flow"
    assert result.payload["total_count"] == 1
    assert isinstance(result.payload["items"], list)
    assert len(result.payload["items"]) == 1

    item = result.payload["items"][0]
    assert item["resource_type"] == "document"
    assert item["capability_type"] == "documents"
    assert item["provider"] == "documents.confluence"
    assert item["normalized_payload"]["document_id"] == "111"
    assert item["normalized_payload"]["title"] == "Auth Flow"
    assert item["normalized_payload"]["content"] == "This page describes the auth flow..."
    assert isinstance(item["references"], list)
    assert len(item["references"]) == 1


@pytest.mark.asyncio
async def test_search_documents_artifact_id_present(confluence_provider):
    mock_client, _ = _make_mock_client(_FAKE_SEARCH_RESPONSE)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "auth flow"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    item = result.payload["items"][0]
    assert item.get("artifact_id") is not None


# ---- 6. search_documents with scope ----


@pytest.mark.asyncio
async def test_search_documents_with_scope_includes_cql_filter(confluence_provider):
    mock_client, _ = _make_mock_client({"results": [], "totalSize": 0})

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "deployment", "scope": "ENG"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        await confluence_provider.execute(request)

    call_kwargs = mock_client.get.call_args.kwargs
    cql = call_kwargs["params"]["cql"]
    assert 'space.key = "ENG"' in cql


# ---- 7. search_documents with default_space ----


@pytest.mark.asyncio
async def test_search_documents_default_space_used_when_no_scope():
    provider = ConfluenceDocumentsProvider(
        base_url="https://example.atlassian.net",
        api_token="test-token",
        default_space="TEAM",
    )
    mock_client, _ = _make_mock_client({"results": [], "totalSize": 0})

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "release notes"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        await provider.execute(request)

    call_kwargs = mock_client.get.call_args.kwargs
    cql = call_kwargs["params"]["cql"]
    assert 'space.key = "TEAM"' in cql


@pytest.mark.asyncio
async def test_search_documents_scope_overrides_default_space():
    provider = ConfluenceDocumentsProvider(
        base_url="https://example.atlassian.net",
        api_token="test-token",
        default_space="TEAM",
    )
    mock_client, _ = _make_mock_client({"results": [], "totalSize": 0})

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "release notes", "scope": "ENG"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        await provider.execute(request)

    call_kwargs = mock_client.get.call_args.kwargs
    cql = call_kwargs["params"]["cql"]
    assert 'space.key = "ENG"' in cql
    assert 'space.key = "TEAM"' not in cql


# ---- 8. get_document normalization ----


@pytest.mark.asyncio
async def test_get_document_normalization(confluence_provider):
    mock_client, _ = _make_mock_client(_FAKE_DOCUMENT_RESPONSE)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="get_document",
        parameters={"document_id": "123456"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["resource_type"] == "document"
    assert result.payload["normalized_payload"]["document_id"] == "123456"
    assert result.payload["normalized_payload"]["title"] == "Architecture Guide"
    assert result.payload["normalized_payload"]["content"] == "<p>Hello world</p>"
    assert result.payload["normalized_payload"]["content_type"] == "text/html"
    assert result.payload["raw_payload"]["id"] == "123456"

    refs = result.payload["references"]
    assert any(r["external_id"] == "123456" for r in refs)

    assert result.payload["provenance"]["space_key"] == "ARCH"
    assert result.payload.get("artifact_id") is not None
    assert result.cost_info is None


@pytest.mark.asyncio
async def test_get_document_duration_ms_set(confluence_provider):
    mock_client, _ = _make_mock_client(_FAKE_DOCUMENT_RESPONSE)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="get_document",
        parameters={"document_id": "123456"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.duration_ms is not None
    assert result.duration_ms >= 0.0


# ---- 9. get_document URL construction ----


@pytest.mark.asyncio
async def test_get_document_url_contains_content_id(confluence_provider):
    mock_client, _ = _make_mock_client(_FAKE_DOCUMENT_RESPONSE)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="get_document",
        parameters={"document_id": "123456"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        await confluence_provider.execute(request)

    call_args = mock_client.get.call_args
    url_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
    assert "/wiki/rest/api/content/123456" in url_arg


# ---- 10. extract_section normalization ----


@pytest.mark.asyncio
async def test_extract_section_normalization(confluence_provider):
    mock_client, _ = _make_mock_client(_FAKE_DOCUMENT_RESPONSE)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="extract_section",
        parameters={"document_id": "123456", "selector": "Deployment"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["resource_type"] == "document_section"
    assert result.payload["provenance"]["selector"] == "Deployment"
    assert result.payload["provenance"]["document_id"] == "123456"
    assert "§ Deployment" in result.payload["normalized_payload"]["title"]


@pytest.mark.asyncio
async def test_extract_section_provenance_fields(confluence_provider):
    mock_client, _ = _make_mock_client(_FAKE_DOCUMENT_RESPONSE)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="extract_section",
        parameters={"document_id": "123456", "selector": "Overview"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    prov = result.payload["provenance"]
    assert prov["provider"] == "confluence"
    assert prov["space_key"] == "ARCH"


# ---- 11. _extract_section_from_storage direct tests ----


def test_extract_section_finds_heading():
    body = (
        "<h1>Overview</h1><p>Intro text</p>"
        "<h2>Deployment</h2><p>Deploy steps</p>"
        "<h2>Rollback</h2><p>Rollback text</p>"
    )
    result = _extract_section_from_storage(body, "Deployment")
    assert result is not None
    assert "Deploy steps" in result
    assert "Rollback" not in result


def test_extract_section_not_found_returns_none():
    body = (
        "<h1>Overview</h1><p>Intro text</p>"
        "<h2>Deployment</h2><p>Deploy steps</p>"
    )
    result = _extract_section_from_storage(body, "NonExistent")
    assert result is None


def test_extract_section_case_insensitive():
    body = "<h2>Deployment</h2><p>Deploy steps</p>"
    result = _extract_section_from_storage(body, "deployment")
    assert result is not None
    assert "Deploy steps" in result


def test_extract_section_returns_remainder_when_no_next_heading():
    body = "<h1>Introduction</h1><p>All the intro content here.</p>"
    result = _extract_section_from_storage(body, "Introduction")
    assert result is not None
    assert "intro content" in result


def test_extract_section_empty_body_returns_none():
    result = _extract_section_from_storage("", "Anything")
    assert result is None


def test_extract_section_partial_selector_match():
    body = "<h2>Deployment Guide</h2><p>Steps here</p><h2>Other</h2><p>more</p>"
    result = _extract_section_from_storage(body, "Deployment")
    assert result is not None
    assert "Steps here" in result


def test_extract_section_higher_level_heading_ends_section():
    body = (
        "<h1>Chapter</h1><p>Chapter intro</p>"
        "<h2>Section</h2><p>Section body</p>"
        "<h1>Next Chapter</h1><p>Next content</p>"
    )
    result = _extract_section_from_storage(body, "Section")
    assert result is not None
    assert "Section body" in result
    assert "Next Chapter" not in result


def test_extract_section_anchor_fallback():
    body = '<ac:anchor ac:name="deployment">text after anchor</ac:anchor>'
    # ac:name="deployment" contains 'name=' so the anchor fallback will match
    result = _extract_section_from_storage(body, "deployment")
    assert result is not None  # name= attribute is matched by the fallback pattern


def test_extract_section_anchor_id_attr():
    body = '<p id="deployment">Some content after</p><p>More content</p>'
    result = _extract_section_from_storage(body, "deployment")
    assert result is not None


# ---- 12. Unknown operation -> NOT_FOUND ----


@pytest.mark.asyncio
async def test_unknown_operation_returns_not_found(confluence_provider):
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="delete_document",
        parameters={"document_id": "123"},
    )
    result = await confluence_provider.execute(request)
    assert result.status == ConnectorStatus.NOT_FOUND
    assert "delete_document" in result.error_message


# ---- 13. HTTP error -> FAILURE ----


@pytest.mark.asyncio
async def test_search_documents_http_error_returns_failure(confluence_provider):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            message="404 Not Found",
            request=MagicMock(),
            response=MagicMock(),
        )
    )
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "test"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.status == ConnectorStatus.FAILURE
    assert result.error_message
    assert result.duration_ms is not None


@pytest.mark.asyncio
async def test_get_document_http_error_returns_failure(confluence_provider):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            message="500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock(),
        )
    )
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="get_document",
        parameters={"document_id": "999"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.status == ConnectorStatus.FAILURE
    assert result.error_message
    assert result.duration_ms is not None


@pytest.mark.asyncio
async def test_extract_section_http_error_returns_failure(confluence_provider):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            message="403 Forbidden",
            request=MagicMock(),
            response=MagicMock(),
        )
    )
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="extract_section",
        parameters={"document_id": "456", "selector": "Overview"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.status == ConnectorStatus.FAILURE
    assert result.error_message


# ---- 14. Basic auth header ----


def test_basic_auth_header():
    provider = ConfluenceDocumentsProvider(
        base_url="https://example.atlassian.net",
        api_token="secret",
        email="user@example.com",
    )
    headers = provider._auth_headers()
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")


def test_basic_auth_header_encodes_credentials():
    import base64

    provider = ConfluenceDocumentsProvider(
        base_url="https://example.atlassian.net",
        api_token="mytoken",
        email="test@example.com",
    )
    headers = provider._auth_headers()
    encoded_part = headers["Authorization"].split(" ", 1)[1]
    decoded = base64.b64decode(encoded_part).decode()
    assert decoded == "test@example.com:mytoken"


# ---- 15. Bearer auth header ----


def test_bearer_auth_header():
    provider = ConfluenceDocumentsProvider(
        base_url="https://confluence.internal",
        api_token="my-pat-token",
    )
    headers = provider._auth_headers()
    assert headers["Authorization"] == "Bearer my-pat-token"


def test_bearer_auth_no_email():
    provider = ConfluenceDocumentsProvider(
        base_url="https://confluence.internal",
        api_token="secret",
    )
    headers = provider._auth_headers()
    assert "Basic" not in headers["Authorization"]
    assert "Bearer" in headers["Authorization"]


# ---- 16. _make_document_artifact static helper ----


def test_make_document_artifact_shape():
    artifact = BaseDocumentsProvider._make_document_artifact(
        provider="documents.confluence",
        connector_id="documents.confluence",
        document_id="doc-1",
        title="My Document",
        content="Some content here",
        url="https://example.atlassian.net/wiki/page/1",
        content_type="text/html",
        raw_payload={"id": "doc-1", "title": "My Document"},
        resource_type="document",
        provenance={"space_key": "ENG", "provider": "confluence"},
    )
    assert isinstance(artifact, ExternalArtifact)
    assert artifact.capability_type == CapabilityType.DOCUMENTS
    assert artifact.resource_type == "document"
    assert artifact.provider == "documents.confluence"
    assert artifact.raw_payload == {"id": "doc-1", "title": "My Document"}
    assert artifact.provenance["space_key"] == "ENG"
    assert artifact.normalized_payload["document_id"] == "doc-1"
    assert artifact.normalized_payload["title"] == "My Document"
    assert artifact.normalized_payload["content"] == "Some content here"
    assert artifact.normalized_payload["content_type"] == "text/html"
    assert artifact.normalized_payload["capability_type"] == "documents"


def test_make_document_artifact_size_bytes_computed():
    content = "Hello, world!"
    artifact = BaseDocumentsProvider._make_document_artifact(
        provider="documents.confluence",
        connector_id="documents.confluence",
        document_id=None,
        title=None,
        content=content,
        url=None,
        content_type="text/plain",
        raw_payload={},
        resource_type="document",
        provenance={},
    )
    assert artifact.normalized_payload["size_bytes"] == len(content.encode())


def test_make_document_artifact_none_content_size_bytes_none():
    artifact = BaseDocumentsProvider._make_document_artifact(
        provider="documents.confluence",
        connector_id="documents.confluence",
        document_id="x",
        title="Title",
        content=None,
        url=None,
        content_type="text/plain",
        raw_payload={},
        resource_type="document",
        provenance={},
    )
    assert artifact.normalized_payload["size_bytes"] is None


def test_make_document_artifact_with_references():
    ref = ExternalReference(
        provider="documents.confluence",
        resource_type="confluence_page",
        external_id="doc-1",
        url="https://example.atlassian.net/wiki/page/1",
    )
    artifact = BaseDocumentsProvider._make_document_artifact(
        provider="documents.confluence",
        connector_id="documents.confluence",
        document_id="doc-1",
        title="Title",
        content="body",
        url="https://example.atlassian.net/wiki/page/1",
        content_type="text/html",
        raw_payload={},
        resource_type="document",
        provenance={},
        references=[ref],
    )
    assert len(artifact.references) == 1
    assert artifact.references[0].external_id == "doc-1"


# ---- Additional edge cases ----


@pytest.mark.asyncio
async def test_search_documents_empty_results(confluence_provider):
    mock_client, _ = _make_mock_client({"results": [], "totalSize": 0})

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "nothing here"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload["total_count"] == 0
    assert result.payload["items"] == []


@pytest.mark.asyncio
async def test_search_documents_no_webui_link(confluence_provider):
    """Documents without _links.webui should not create ExternalReference."""
    response = {
        "results": [
            {
                "content": {
                    "id": "222",
                    "title": "No Link Page",
                    "type": "page",
                    "space": {"key": "TEST"},
                    "_links": {},
                },
                "excerpt": "excerpt",
            }
        ],
        "totalSize": 1,
    }
    mock_client, _ = _make_mock_client(response)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "no link"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    item = result.payload["items"][0]
    assert item["references"] == []


@pytest.mark.asyncio
async def test_get_document_no_webui_link(confluence_provider):
    """get_document with no webui link should have empty references."""
    response = {
        "id": "789",
        "title": "No Link Doc",
        "type": "page",
        "body": {"storage": {"value": "content"}},
        "space": {"key": "TEST"},
        "_links": {},
        "metadata": {"labels": {"results": []}},
    }
    mock_client, _ = _make_mock_client(response)

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="get_document",
        parameters={"document_id": "789"},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        result = await confluence_provider.execute(request)

    assert result.payload["references"] == []


def test_provider_id_and_display_name(confluence_provider):
    assert confluence_provider.provider_id == "documents.confluence"
    assert confluence_provider.display_name == "Confluence Documents"


@pytest.mark.asyncio
async def test_search_documents_limit_passed_to_api(confluence_provider):
    mock_client, _ = _make_mock_client({"results": [], "totalSize": 0})

    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.DOCUMENTS,
        operation="search_documents",
        parameters={"query": "test", "limit": 5},
    )

    with patch(_PATCH_TARGET, return_value=mock_client):
        await confluence_provider.execute(request)

    call_kwargs = mock_client.get.call_args.kwargs
    assert call_kwargs["params"]["limit"] == 5
