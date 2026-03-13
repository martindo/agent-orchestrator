"""Tests for ticketing capability connector providers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorStatus,
    ExternalArtifact,
)
from agent_orchestrator.connectors.providers.ticketing import (
    JiraTicketingProvider,
    LinearTicketingProvider,
)
from agent_orchestrator.connectors.providers.ticketing._base import (
    BaseTicketingProvider,
    TicketingProviderError,
    _TICKETING_OPS,
)
from agent_orchestrator.connectors.registry import ConnectorProviderProtocol


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def jira_provider() -> JiraTicketingProvider:
    return JiraTicketingProvider(
        base_url="https://myorg.atlassian.net",
        api_token="ATATT3xFfGF0test",
        email="user@example.com",
        default_project="PROJ",
    )


@pytest.fixture
def jira_provider_pat() -> JiraTicketingProvider:
    """Jira provider using Bearer (PAT) auth — no email."""
    return JiraTicketingProvider(
        base_url="https://jira.internal.example.com",
        api_token="personal-access-token",
    )


@pytest.fixture
def linear_provider() -> LinearTicketingProvider:
    return LinearTicketingProvider(
        api_key="lin_api_testtoken",
        default_team_id="team-uuid-1234",
    )


def _mock_http_client(json_response: dict | None = None, status_code: int = 200):
    """Build an AsyncMock httpx.AsyncClient that returns a canned response."""
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    if json_response is not None:
        fake_response.json.return_value = json_response
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, fake_response


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructorValidation:
    def test_jira_empty_base_url_raises(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            JiraTicketingProvider(base_url="", api_token="tok")

    def test_jira_empty_api_token_raises(self) -> None:
        with pytest.raises(ValueError, match="api_token"):
            JiraTicketingProvider(base_url="https://org.atlassian.net", api_token="")

    def test_linear_empty_api_key_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            LinearTicketingProvider(api_key="")

    def test_jira_strips_trailing_slash(self) -> None:
        p = JiraTicketingProvider(
            base_url="https://org.atlassian.net/", api_token="tok"
        )
        assert not p._base_url.endswith("/")


# ---------------------------------------------------------------------------
# Descriptor shape
# ---------------------------------------------------------------------------


class TestDescriptorShape:
    def test_jira_descriptor(self, jira_provider: JiraTicketingProvider) -> None:
        desc = jira_provider.get_descriptor()
        assert CapabilityType.TICKETING in desc.capability_types
        ops = {op.operation for op in desc.operations}
        assert ops == {"create_ticket", "update_ticket", "get_ticket", "search_tickets"}
        assert desc.provider_id == "ticketing.jira"
        assert desc.auth_required is True

    def test_linear_descriptor(self, linear_provider: LinearTicketingProvider) -> None:
        desc = linear_provider.get_descriptor()
        assert CapabilityType.TICKETING in desc.capability_types
        ops = {op.operation for op in desc.operations}
        assert ops == {"create_ticket", "update_ticket", "get_ticket", "search_tickets"}
        assert desc.provider_id == "ticketing.linear"

    def test_write_ops_are_not_read_only(self) -> None:
        write_ops = {"create_ticket", "update_ticket"}
        for op in _TICKETING_OPS:
            if op.operation in write_ops:
                assert op.read_only is False, f"{op.operation} should be read_only=False"

    def test_read_ops_are_read_only(self) -> None:
        read_ops = {"get_ticket", "search_tickets"}
        for op in _TICKETING_OPS:
            if op.operation in read_ops:
                assert op.read_only is True, f"{op.operation} should be read_only=True"


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------


class TestProtocolCheck:
    def test_jira_satisfies_protocol(self, jira_provider: JiraTicketingProvider) -> None:
        assert isinstance(jira_provider, ConnectorProviderProtocol)

    def test_linear_satisfies_protocol(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        assert isinstance(linear_provider, ConnectorProviderProtocol)


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_jira_available_with_token(self, jira_provider: JiraTicketingProvider) -> None:
        assert jira_provider.is_available() is True

    def test_linear_available_with_key(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        assert linear_provider.is_available() is True

    def test_jira_unavailable_when_token_cleared(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        jira_provider._api_token = ""
        assert jira_provider.is_available() is False


# ---------------------------------------------------------------------------
# Jira: create_ticket
# ---------------------------------------------------------------------------


class TestJiraCreateTicket:
    async def test_create_ticket_success(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client(
            {"id": "10001", "key": "PROJ-42", "self": "https://myorg.atlassian.net/rest/api/3/issue/10001"}
        )
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.TICKETING,
                operation="create_ticket",
                parameters={
                    "summary": "Fix login bug",
                    "description": "Users cannot log in",
                    "priority": "High",
                },
            )
            result = await jira_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["capability_type"] == "ticketing"
        assert result.payload["resource_type"] == "ticket"
        assert result.payload["provider"] == "ticketing.jira"
        assert result.payload["normalized_payload"]["ticket_id"] == "PROJ-42"
        assert result.payload["normalized_payload"]["title"] == "Fix login bug"
        assert result.payload["normalized_payload"]["priority"] == "High"
        assert len(result.payload["references"]) == 1
        assert result.payload["references"][0]["external_id"] == "PROJ-42"

    async def test_create_ticket_uses_default_project(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client({"key": "PROJ-1"})
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="create_ticket",
                    parameters={"summary": "Task"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        posted = mock_client.post.call_args.kwargs["json"]
        assert posted["fields"]["project"]["key"] == "PROJ"

    async def test_create_ticket_no_project_raises(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        jira_provider._default_project = None
        request = ConnectorInvocationRequest(
            capability_type=CapabilityType.TICKETING,
            operation="create_ticket",
            parameters={"summary": "No project"},
        )
        result = await jira_provider.execute(request)
        assert result.status == ConnectorStatus.FAILURE
        assert "project" in result.error_message

    async def test_create_ticket_http_error(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client()
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "400", request=MagicMock(), response=MagicMock()
            )
        )
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="create_ticket",
                    parameters={"summary": "Fail", "project": "PROJ"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE

    async def test_create_ticket_uses_bearer_for_pat(
        self, jira_provider_pat: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client({"key": "INT-7"})
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await jira_provider_pat.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="create_ticket",
                    parameters={"summary": "PAT test", "project": "INT"},
                )
            )

        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["Authorization"].startswith("Bearer ")


# ---------------------------------------------------------------------------
# Jira: update_ticket
# ---------------------------------------------------------------------------


class TestJiraUpdateTicket:
    async def test_update_ticket_success(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client()
        fake_response.json.return_value = {}
        mock_client.put = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="update_ticket",
                    parameters={
                        "ticket_id": "PROJ-42",
                        "changes": {"summary": "Updated title", "priority": {"name": "Low"}},
                    },
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["normalized_payload"]["ticket_id"] == "PROJ-42"
        assert result.payload["normalized_payload"]["priority"] == "Low"

    async def test_update_ticket_http_error(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client()
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock()
            )
        )
        mock_client.put = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="update_ticket",
                    parameters={"ticket_id": "PROJ-999", "changes": {}},
                )
            )

        assert result.status == ConnectorStatus.FAILURE


# ---------------------------------------------------------------------------
# Jira: get_ticket
# ---------------------------------------------------------------------------


class TestJiraGetTicket:
    async def test_get_ticket_success(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client(
            {
                "key": "PROJ-42",
                "fields": {
                    "summary": "Fix login bug",
                    "description": None,
                    "status": {"name": "In Progress"},
                    "priority": {"name": "High"},
                    "assignee": {"displayName": "Alice"},
                },
            }
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="get_ticket",
                    parameters={"ticket_id": "PROJ-42"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        normalized = result.payload["normalized_payload"]
        assert normalized["ticket_id"] == "PROJ-42"
        assert normalized["title"] == "Fix login bug"
        assert normalized["status"] == "In Progress"
        assert normalized["priority"] == "High"
        assert normalized["assignee"] == "Alice"
        assert result.payload["normalized_payload"]["url"] is not None

    async def test_get_ticket_not_found(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client, fake_response = _mock_http_client()
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=mock_response
            )
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="get_ticket",
                    parameters={"ticket_id": "PROJ-9999"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE
        assert "PROJ-9999" in result.error_message

    async def test_get_ticket_adf_description_extracted(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        adf = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Hello world"}],
                }
            ],
        }
        mock_client, fake_response = _mock_http_client(
            {"key": "PROJ-1", "fields": {"summary": "T", "description": adf}}
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="get_ticket",
                    parameters={"ticket_id": "PROJ-1"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["normalized_payload"]["description"] == "Hello world"


# ---------------------------------------------------------------------------
# Jira: search_tickets
# ---------------------------------------------------------------------------


class TestJiraSearchTickets:
    async def test_search_tickets_success(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client(
            {
                "total": 2,
                "issues": [
                    {
                        "key": "PROJ-1",
                        "fields": {
                            "summary": "Bug one",
                            "status": {"name": "Open"},
                            "priority": {"name": "High"},
                            "assignee": None,
                        },
                    },
                    {
                        "key": "PROJ-2",
                        "fields": {
                            "summary": "Bug two",
                            "status": {"name": "Closed"},
                            "priority": None,
                            "assignee": {"displayName": "Bob"},
                        },
                    },
                ],
            }
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="search_tickets",
                    parameters={"query": "project = PROJ AND status = Open"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "ticket_list"
        raw = result.payload["raw_payload"]
        assert raw["total"] == 2
        assert len(raw["items"]) == 2
        assert raw["items"][0]["ticket_id"] == "PROJ-1"
        assert raw["items"][1]["assignee"] == "Bob"

    async def test_search_tickets_empty_results(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client({"total": 0, "issues": []})
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="search_tickets",
                    parameters={"query": "project = EMPTY"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["raw_payload"]["total"] == 0
        assert result.payload["raw_payload"]["items"] == []

    async def test_search_tickets_passes_limit(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client({"total": 0, "issues": []})
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.jira.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await jira_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="search_tickets",
                    parameters={"query": "project = PROJ", "limit": "10"},
                )
            )

        params = mock_client.get.call_args.kwargs["params"]
        assert params["maxResults"] == 10


# ---------------------------------------------------------------------------
# Jira: unknown operation
# ---------------------------------------------------------------------------


class TestJiraUnknownOperation:
    async def test_unknown_operation_returns_not_found(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        result = await jira_provider.execute(
            ConnectorInvocationRequest(
                capability_type=CapabilityType.TICKETING,
                operation="delete_ticket",
                parameters={},
            )
        )
        assert result.status == ConnectorStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# Jira: Basic vs Bearer auth headers
# ---------------------------------------------------------------------------


class TestJiraAuth:
    def test_basic_auth_when_email_provided(
        self, jira_provider: JiraTicketingProvider
    ) -> None:
        headers = jira_provider._auth_headers()
        assert headers["Authorization"].startswith("Basic ")

    def test_bearer_auth_when_no_email(
        self, jira_provider_pat: JiraTicketingProvider
    ) -> None:
        headers = jira_provider_pat._auth_headers()
        assert headers["Authorization"].startswith("Bearer ")


# ---------------------------------------------------------------------------
# Linear: create_ticket
# ---------------------------------------------------------------------------


class TestLinearCreateTicket:
    async def test_create_ticket_success(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        graphql_response = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "uuid-issue-1",
                        "identifier": "ENG-101",
                        "title": "Implement feature X",
                        "description": "Details here",
                        "state": {"name": "Todo"},
                        "priorityLabel": "High",
                        "assignee": None,
                        "url": "https://linear.app/team/issue/ENG-101",
                    },
                }
            }
        }
        mock_client, fake_response = _mock_http_client(graphql_response)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="create_ticket",
                    parameters={
                        "summary": "Implement feature X",
                        "description": "Details here",
                        "priority": "high",
                    },
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        normalized = result.payload["normalized_payload"]
        assert normalized["ticket_id"] == "ENG-101"
        assert normalized["title"] == "Implement feature X"
        assert normalized["status"] == "Todo"
        assert normalized["priority"] == "High"
        assert result.payload["references"][0]["url"] is not None

    async def test_create_ticket_no_team_raises(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        linear_provider._default_team_id = None
        result = await linear_provider.execute(
            ConnectorInvocationRequest(
                capability_type=CapabilityType.TICKETING,
                operation="create_ticket",
                parameters={"summary": "No team"},
            )
        )
        assert result.status == ConnectorStatus.FAILURE
        assert "team" in result.error_message.lower()

    async def test_create_ticket_graphql_error(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client(
            {"errors": [{"message": "Unauthorized"}]}
        )
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="create_ticket",
                    parameters={"summary": "Test"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE
        assert "Unauthorized" in result.error_message

    async def test_create_ticket_priority_mapped_to_int(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client(
            {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "u1",
                            "identifier": "ENG-1",
                            "title": "T",
                            "description": None,
                            "state": None,
                            "priorityLabel": "Urgent",
                            "assignee": None,
                            "url": None,
                        },
                    }
                }
            }
        )
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="create_ticket",
                    parameters={"summary": "T", "priority": "urgent"},
                )
            )

        body = mock_client.post.call_args.kwargs["json"]
        assert body["variables"]["input"]["priority"] == 1


# ---------------------------------------------------------------------------
# Linear: update_ticket
# ---------------------------------------------------------------------------


class TestLinearUpdateTicket:
    async def test_update_ticket_success(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        graphql_response = {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {
                        "id": "uuid-1",
                        "identifier": "ENG-101",
                        "title": "Updated title",
                        "description": None,
                        "state": {"name": "In Progress"},
                        "priorityLabel": "Medium",
                        "url": "https://linear.app/team/issue/ENG-101",
                    },
                }
            }
        }
        mock_client, fake_response = _mock_http_client(graphql_response)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="update_ticket",
                    parameters={
                        "ticket_id": "uuid-issue-1",
                        "changes": {"title": "Updated title", "priority": "medium"},
                    },
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["normalized_payload"]["ticket_id"] == "ENG-101"
        assert result.payload["normalized_payload"]["status"] == "In Progress"


# ---------------------------------------------------------------------------
# Linear: get_ticket
# ---------------------------------------------------------------------------


class TestLinearGetTicket:
    async def test_get_ticket_success(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        graphql_response = {
            "data": {
                "issue": {
                    "id": "uuid-1",
                    "identifier": "ENG-42",
                    "title": "Deploy service",
                    "description": "Deploy to prod",
                    "state": {"name": "In Review"},
                    "priorityLabel": "Medium",
                    "assignee": {"displayName": "Carol"},
                    "url": "https://linear.app/team/issue/ENG-42",
                }
            }
        }
        mock_client, fake_response = _mock_http_client(graphql_response)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="get_ticket",
                    parameters={"ticket_id": "ENG-42"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        normalized = result.payload["normalized_payload"]
        assert normalized["ticket_id"] == "ENG-42"
        assert normalized["assignee"] == "Carol"
        assert normalized["status"] == "In Review"

    async def test_get_ticket_not_found(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client({"data": {"issue": None}})
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="get_ticket",
                    parameters={"ticket_id": "ENG-9999"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE
        assert "ENG-9999" in result.error_message


# ---------------------------------------------------------------------------
# Linear: search_tickets
# ---------------------------------------------------------------------------


class TestLinearSearchTickets:
    async def test_search_tickets_success(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        graphql_response = {
            "data": {
                "issues": {
                    "nodes": [
                        {
                            "id": "uuid-1",
                            "identifier": "ENG-1",
                            "title": "Fix auth",
                            "description": None,
                            "state": {"name": "Todo"},
                            "priorityLabel": "High",
                            "assignee": {"displayName": "Dave"},
                            "url": "https://linear.app/team/issue/ENG-1",
                        }
                    ],
                    "totalCount": 1,
                }
            }
        }
        mock_client, fake_response = _mock_http_client(graphql_response)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="search_tickets",
                    parameters={"query": "auth"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "ticket_list"
        raw = result.payload["raw_payload"]
        assert raw["total"] == 1
        assert raw["items"][0]["ticket_id"] == "ENG-1"
        assert raw["items"][0]["assignee"] == "Dave"

    async def test_search_tickets_empty_results(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        graphql_response = {"data": {"issues": {"nodes": [], "totalCount": 0}}}
        mock_client, fake_response = _mock_http_client(graphql_response)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="search_tickets",
                    parameters={"query": "xyz-not-found"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["raw_payload"]["items"] == []

    async def test_search_tickets_passes_limit(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        graphql_response = {"data": {"issues": {"nodes": [], "totalCount": 0}}}
        mock_client, fake_response = _mock_http_client(graphql_response)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.ticketing.linear.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await linear_provider.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.TICKETING,
                    operation="search_tickets",
                    parameters={"query": "auth", "limit": "5"},
                )
            )

        body = mock_client.post.call_args.kwargs["json"]
        assert body["variables"]["first"] == 5


# ---------------------------------------------------------------------------
# Linear: unknown operation
# ---------------------------------------------------------------------------


class TestLinearUnknownOperation:
    async def test_unknown_operation_returns_not_found(
        self, linear_provider: LinearTicketingProvider
    ) -> None:
        result = await linear_provider.execute(
            ConnectorInvocationRequest(
                capability_type=CapabilityType.TICKETING,
                operation="close_ticket",
                parameters={},
            )
        )
        assert result.status == ConnectorStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# _make_ticket_artifact static helper
# ---------------------------------------------------------------------------


class TestMakeTicketArtifact:
    def test_produces_external_artifact(self) -> None:
        from agent_orchestrator.connectors.models import ExternalReference

        artifact = BaseTicketingProvider._make_ticket_artifact(
            provider="ticketing.jira",
            connector_id="ticketing.jira",
            ticket_id="PROJ-42",
            title="Fix login bug",
            description="Users cannot log in via SSO",
            status="In Progress",
            priority="High",
            assignee="alice",
            url="https://myorg.atlassian.net/browse/PROJ-42",
            raw_payload={"key": "PROJ-42"},
            resource_type="ticket",
            provenance={"provider": "jira", "project": "PROJ"},
            references=[
                ExternalReference(
                    provider="ticketing.jira",
                    resource_type="jira_issue",
                    external_id="PROJ-42",
                    url="https://myorg.atlassian.net/browse/PROJ-42",
                )
            ],
        )

        assert isinstance(artifact, ExternalArtifact)
        assert artifact.capability_type == CapabilityType.TICKETING
        assert artifact.resource_type == "ticket"
        normalized = artifact.normalized_payload
        assert normalized["ticket_id"] == "PROJ-42"
        assert normalized["title"] == "Fix login bug"
        assert normalized["description"] == "Users cannot log in via SSO"
        assert normalized["status"] == "In Progress"
        assert normalized["priority"] == "High"
        assert normalized["assignee"] == "alice"
        assert normalized["url"] == "https://myorg.atlassian.net/browse/PROJ-42"
        assert len(artifact.references) == 1

    def test_optional_fields_default_to_none(self) -> None:
        artifact = BaseTicketingProvider._make_ticket_artifact(
            provider="ticketing.linear",
            connector_id="ticketing.linear",
            ticket_id="ENG-1",
            title="Simple ticket",
            description=None,
            status=None,
            priority=None,
            assignee=None,
            url=None,
            raw_payload={},
            resource_type="ticket",
            provenance={"provider": "linear"},
        )

        normalized = artifact.normalized_payload
        assert normalized["description"] is None
        assert normalized["status"] is None
        assert normalized["priority"] is None
        assert normalized["assignee"] is None

    def test_ticket_list_artifact_has_no_normalized_payload(self) -> None:
        artifact = BaseTicketingProvider._make_ticket_list_artifact(
            provider="ticketing.jira",
            connector_id="ticketing.jira",
            query="project = PROJ",
            items=[{"ticket_id": "PROJ-1", "title": "T"}],
            total=1,
            provenance={"provider": "jira"},
        )

        assert artifact.resource_type == "ticket_list"
        assert artifact.normalized_payload is None
        assert artifact.raw_payload["total"] == 1
        assert len(artifact.raw_payload["items"]) == 1


# ---------------------------------------------------------------------------
# Package exports
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_ticketing_providers_exported_from_ticketing(self) -> None:
        from agent_orchestrator.connectors.providers.ticketing import (
            JiraTicketingProvider,
            LinearTicketingProvider,
        )

        assert JiraTicketingProvider is not None
        assert LinearTicketingProvider is not None

    def test_ticketing_providers_exported_from_providers(self) -> None:
        from agent_orchestrator.connectors.providers import (
            JiraTicketingProvider,
            LinearTicketingProvider,
        )

        assert JiraTicketingProvider is not None
        assert LinearTicketingProvider is not None

    def test_provider_ids(self) -> None:
        jira = JiraTicketingProvider(
            base_url="https://org.atlassian.net", api_token="tok"
        )
        linear = LinearTicketingProvider(api_key="lin_api_test")

        assert jira.provider_id == "ticketing.jira"
        assert linear.provider_id == "ticketing.linear"


# ---------------------------------------------------------------------------
# Permission hook integration: write operations respect read_only=False
# ---------------------------------------------------------------------------


class TestPermissionHookIntegration:
    def test_write_ops_trigger_requires_approval(self) -> None:
        """Verify that create_ticket and update_ticket are not read-only ops,
        which causes ConnectorService to route through the approval path when
        a policy has requires_approval=True."""
        from agent_orchestrator.connectors.permissions import (
            PermissionOutcome,
            evaluate_permission_detailed,
        )
        from agent_orchestrator.connectors.models import (
            ConnectorPermissionPolicy,
            ConnectorInvocationRequest,
            CapabilityType,
        )

        policy = ConnectorPermissionPolicy(
            description="Require approval for ticket writes",
            allowed_capability_types=[CapabilityType.TICKETING],
            requires_approval=True,
        )

        for write_op in ("create_ticket", "update_ticket"):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.TICKETING,
                operation=write_op,
                parameters={},
            )
            result = evaluate_permission_detailed(request, [policy])
            assert result.outcome == PermissionOutcome.REQUIRES_APPROVAL, (
                f"Expected REQUIRES_APPROVAL for {write_op!r}, got {result.outcome}"
            )

    def test_read_ops_do_not_trigger_approval(self) -> None:
        """Verify that get_ticket and search_tickets pass through without
        approval even when a policy has requires_approval=True."""
        from agent_orchestrator.connectors.permissions import (
            PermissionOutcome,
            evaluate_permission_detailed,
        )
        from agent_orchestrator.connectors.models import (
            ConnectorPermissionPolicy,
            ConnectorInvocationRequest,
            CapabilityType,
        )

        policy = ConnectorPermissionPolicy(
            description="Require approval for ticket writes",
            allowed_capability_types=[CapabilityType.TICKETING],
            requires_approval=True,
        )

        for read_op in ("get_ticket", "search_tickets"):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.TICKETING,
                operation=read_op,
                parameters={},
            )
            result = evaluate_permission_detailed(request, [policy])
            assert result.outcome == PermissionOutcome.ALLOW, (
                f"Expected ALLOW for {read_op!r}, got {result.outcome}"
            )
