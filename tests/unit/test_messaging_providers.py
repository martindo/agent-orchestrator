"""Tests for messaging capability connector providers."""

from __future__ import annotations

import smtplib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorStatus,
    ExternalArtifact,
)
from agent_orchestrator.connectors.providers.messaging import (
    EmailMessagingProvider,
    SlackMessagingProvider,
    TeamsMessagingProvider,
)
from agent_orchestrator.connectors.providers.messaging._base import (
    BaseMessagingProvider,
    MessagingProviderError,
    _MESSAGING_OPS,
)
from agent_orchestrator.connectors.registry import ConnectorProviderProtocol


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def slack_provider() -> SlackMessagingProvider:
    return SlackMessagingProvider(bot_token="xoxb-test-token")


@pytest.fixture
def teams_provider() -> TeamsMessagingProvider:
    return TeamsMessagingProvider(webhook_url="https://outlook.office.com/webhook/test")


@pytest.fixture
def email_provider() -> EmailMessagingProvider:
    return EmailMessagingProvider(
        smtp_host="smtp.example.com",
        username="agent@example.com",
        password="secret",
        from_address="agent@example.com",
    )


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructorValidation:
    def test_slack_empty_token_raises(self) -> None:
        with pytest.raises(ValueError, match="bot_token"):
            SlackMessagingProvider(bot_token="")

    def test_teams_empty_webhook_raises(self) -> None:
        with pytest.raises(ValueError, match="webhook_url"):
            TeamsMessagingProvider(webhook_url="")

    def test_email_empty_smtp_host_raises(self) -> None:
        with pytest.raises(ValueError, match="smtp_host"):
            EmailMessagingProvider(
                smtp_host="",
                username="u",
                password="p",
                from_address="f@f.com",
            )

    def test_email_empty_username_raises(self) -> None:
        with pytest.raises(ValueError, match="username"):
            EmailMessagingProvider(
                smtp_host="smtp.example.com",
                username="",
                password="p",
                from_address="f@f.com",
            )

    def test_email_empty_password_raises(self) -> None:
        with pytest.raises(ValueError, match="password"):
            EmailMessagingProvider(
                smtp_host="smtp.example.com",
                username="u",
                password="",
                from_address="f@f.com",
            )

    def test_email_empty_from_address_raises(self) -> None:
        with pytest.raises(ValueError, match="from_address"):
            EmailMessagingProvider(
                smtp_host="smtp.example.com",
                username="u",
                password="p",
                from_address="",
            )


# ---------------------------------------------------------------------------
# Descriptor shape
# ---------------------------------------------------------------------------


class TestDescriptorShape:
    def test_slack_descriptor(self, slack_provider: SlackMessagingProvider) -> None:
        desc = slack_provider.get_descriptor()
        assert CapabilityType.MESSAGING in desc.capability_types
        ops = {op.operation for op in desc.operations}
        assert ops == {"send_message", "notify_user", "create_thread"}
        assert all(not op.read_only for op in desc.operations)
        assert desc.provider_id == "messaging.slack"

    def test_teams_descriptor(self, teams_provider: TeamsMessagingProvider) -> None:
        desc = teams_provider.get_descriptor()
        assert CapabilityType.MESSAGING in desc.capability_types
        ops = {op.operation for op in desc.operations}
        assert ops == {"send_message", "notify_user", "create_thread"}
        assert all(not op.read_only for op in desc.operations)
        assert desc.provider_id == "messaging.teams"

    def test_email_descriptor(self, email_provider: EmailMessagingProvider) -> None:
        desc = email_provider.get_descriptor()
        assert CapabilityType.MESSAGING in desc.capability_types
        ops = {op.operation for op in desc.operations}
        assert ops == {"send_message", "notify_user", "create_thread"}
        assert all(not op.read_only for op in desc.operations)
        assert desc.provider_id == "messaging.email"

    def test_all_ops_read_only_false(self) -> None:
        for op in _MESSAGING_OPS:
            assert op.read_only is False


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------


class TestProtocolCheck:
    def test_slack_satisfies_protocol(self, slack_provider: SlackMessagingProvider) -> None:
        assert isinstance(slack_provider, ConnectorProviderProtocol)

    def test_teams_satisfies_protocol(self, teams_provider: TeamsMessagingProvider) -> None:
        assert isinstance(teams_provider, ConnectorProviderProtocol)

    def test_email_satisfies_protocol(self, email_provider: EmailMessagingProvider) -> None:
        assert isinstance(email_provider, ConnectorProviderProtocol)


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_slack_available_with_token(self, slack_provider: SlackMessagingProvider) -> None:
        assert slack_provider.is_available() is True

    def test_teams_available_with_webhook(self, teams_provider: TeamsMessagingProvider) -> None:
        assert teams_provider.is_available() is True

    def test_email_available_with_username(self, email_provider: EmailMessagingProvider) -> None:
        assert email_provider.is_available() is True

    def test_slack_unavailable_when_token_cleared(
        self, slack_provider: SlackMessagingProvider
    ) -> None:
        slack_provider._api_token = ""
        assert slack_provider.is_available() is False


# ---------------------------------------------------------------------------
# Slack: send_message
# ---------------------------------------------------------------------------


class TestSlackSendMessage:
    async def test_send_message_success(self, slack_provider: SlackMessagingProvider) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "ok": True,
            "channel": "C12345",
            "ts": "1699000000.000100",
            "message": {"text": "Hello"},
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.slack.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="send_message",
                parameters={"destination": "C12345", "content": "Hello"},
            )
            result = await slack_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["capability_type"] == "messaging"
        assert result.payload["resource_type"] == "message"
        assert result.payload["provider"] == "messaging.slack"
        assert result.payload["normalized_payload"]["message_id"] == "1699000000.000100"
        assert result.payload["normalized_payload"]["channel"] == "C12345"
        assert result.payload["normalized_payload"]["body"] == "Hello"
        assert len(result.payload["references"]) == 1
        assert result.payload["references"][0]["external_id"] == "1699000000.000100"

    async def test_send_message_slack_api_error(
        self, slack_provider: SlackMessagingProvider
    ) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.slack.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="send_message",
                parameters={"destination": "CBAD", "content": "Hello"},
            )
            result = await slack_provider.execute(request)

        assert result.status == ConnectorStatus.FAILURE
        assert "channel_not_found" in result.error_message

    async def test_send_message_http_error(self, slack_provider: SlackMessagingProvider) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "500",
                request=MagicMock(),
                response=MagicMock(),
            )
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.slack.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="send_message",
                parameters={"destination": "C12345", "content": "Hello"},
            )
            result = await slack_provider.execute(request)

        assert result.status == ConnectorStatus.FAILURE


# ---------------------------------------------------------------------------
# Slack: notify_user
# ---------------------------------------------------------------------------


class TestSlackNotifyUser:
    async def test_notify_user_success(self, slack_provider: SlackMessagingProvider) -> None:
        open_response = MagicMock()
        open_response.raise_for_status = MagicMock()
        open_response.json.return_value = {"ok": True, "channel": {"id": "D99999"}}

        post_response = MagicMock()
        post_response.raise_for_status = MagicMock()
        post_response.json.return_value = {
            "ok": True,
            "channel": "D99999",
            "ts": "1699000001.000200",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=[open_response, post_response])

        with patch(
            "agent_orchestrator.connectors.providers.messaging.slack.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="notify_user",
                parameters={"user_id": "U12345", "content": "Hey there"},
            )
            result = await slack_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "notification"
        assert result.payload["normalized_payload"]["recipients"] == ["U12345"]
        assert result.payload["normalized_payload"]["channel"] == "D99999"


# ---------------------------------------------------------------------------
# Slack: create_thread
# ---------------------------------------------------------------------------


class TestSlackCreateThread:
    async def test_create_thread_success(self, slack_provider: SlackMessagingProvider) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "ok": True,
            "channel": "C12345",
            "ts": "1699000002.000300",
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.slack.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="create_thread",
                parameters={
                    "destination": "C12345",
                    "title": "My Thread Title",
                    "content": "Thread body",
                },
            )
            result = await slack_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "thread"
        assert result.payload["normalized_payload"]["subject"] == "My Thread Title"

    async def test_create_thread_posts_bold_title(
        self, slack_provider: SlackMessagingProvider
    ) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "ok": True,
            "channel": "C12345",
            "ts": "1699000003.000400",
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.slack.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="create_thread",
                parameters={
                    "destination": "C12345",
                    "title": "Incident Alert",
                    "content": "Something happened",
                },
            )
            await slack_provider.execute(request)

        call_kwargs = mock_client.post.call_args
        posted_json = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
        assert "*Incident Alert*" in posted_json["text"]


# ---------------------------------------------------------------------------
# Slack: unknown operation
# ---------------------------------------------------------------------------


class TestSlackUnknownOperation:
    async def test_unknown_operation_returns_not_found(
        self, slack_provider: SlackMessagingProvider
    ) -> None:
        request = ConnectorInvocationRequest(
            capability_type=CapabilityType.MESSAGING,
            operation="delete_message",
            parameters={},
        )
        result = await slack_provider.execute(request)
        assert result.status == ConnectorStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# Teams: send_message
# ---------------------------------------------------------------------------


class TestTeamsSendMessage:
    async def test_send_message_success(self, teams_provider: TeamsMessagingProvider) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.text = "1"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.teams.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="send_message",
                parameters={"destination": "general", "content": "Hello Teams"},
            )
            result = await teams_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "message"
        assert result.payload["normalized_payload"]["body"] == "Hello Teams"
        assert result.payload["normalized_payload"]["message_id"] is not None

    async def test_send_message_non_one_response_fails(
        self, teams_provider: TeamsMessagingProvider
    ) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.text = "Invalid webhook URL"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.teams.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="send_message",
                parameters={"destination": "general", "content": "Hello"},
            )
            result = await teams_provider.execute(request)

        assert result.status == ConnectorStatus.FAILURE


# ---------------------------------------------------------------------------
# Teams: notify_user
# ---------------------------------------------------------------------------


class TestTeamsNotifyUser:
    async def test_notify_user_success(self, teams_provider: TeamsMessagingProvider) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.text = "1"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.teams.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="notify_user",
                parameters={"user_id": "user@example.com", "content": "Alert!"},
            )
            result = await teams_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "notification"
        assert result.payload["normalized_payload"]["recipients"] == ["user@example.com"]

    async def test_notify_user_at_mention_in_body(
        self, teams_provider: TeamsMessagingProvider
    ) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.text = "1"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.teams.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="notify_user",
                parameters={"user_id": "user@example.com", "content": "Alert!"},
            )
            await teams_provider.execute(request)

        call_kwargs = mock_client.post.call_args
        posted_json = call_kwargs.kwargs["json"]
        assert "user@example.com" in posted_json["text"]


# ---------------------------------------------------------------------------
# Teams: create_thread
# ---------------------------------------------------------------------------


class TestTeamsCreateThread:
    async def test_create_thread_success(self, teams_provider: TeamsMessagingProvider) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.text = "1"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.teams.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="create_thread",
                parameters={
                    "destination": "general",
                    "title": "Incident Alert",
                    "content": "Details here",
                },
            )
            result = await teams_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "thread"
        assert result.payload["normalized_payload"]["subject"] == "Incident Alert"

    async def test_create_thread_posts_title_field(
        self, teams_provider: TeamsMessagingProvider
    ) -> None:
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.text = "1"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.messaging.teams.httpx.AsyncClient",
            return_value=mock_client,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="create_thread",
                parameters={
                    "destination": "general",
                    "title": "Incident Alert",
                    "content": "Details here",
                },
            )
            await teams_provider.execute(request)

        call_kwargs = mock_client.post.call_args
        posted_json = call_kwargs.kwargs["json"]
        assert posted_json["title"] == "Incident Alert"


# ---------------------------------------------------------------------------
# Teams: unknown operation
# ---------------------------------------------------------------------------


class TestTeamsUnknownOperation:
    async def test_unknown_operation_returns_not_found(
        self, teams_provider: TeamsMessagingProvider
    ) -> None:
        request = ConnectorInvocationRequest(
            capability_type=CapabilityType.MESSAGING,
            operation="delete_message",
            parameters={},
        )
        result = await teams_provider.execute(request)
        assert result.status == ConnectorStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# Email: send_message
# ---------------------------------------------------------------------------


class TestEmailSendMessage:
    async def test_send_message_success(self, email_provider: EmailMessagingProvider) -> None:
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.sendmail = MagicMock()

        with patch(
            "agent_orchestrator.connectors.providers.messaging.email.smtplib.SMTP",
            return_value=mock_smtp_instance,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="send_message",
                parameters={"destination": "to@example.com", "content": "Test content"},
            )
            result = await email_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "message"
        assert result.payload["normalized_payload"]["sender"] == "agent@example.com"
        assert result.payload["normalized_payload"]["recipients"] == ["to@example.com"]
        assert result.payload["normalized_payload"]["body"] == "Test content"
        assert result.payload["normalized_payload"]["message_id"] is not None

    async def test_send_message_smtp_error(self, email_provider: EmailMessagingProvider) -> None:
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.sendmail = MagicMock(
            side_effect=smtplib.SMTPException("auth failed")
        )

        with patch(
            "agent_orchestrator.connectors.providers.messaging.email.smtplib.SMTP",
            return_value=mock_smtp_instance,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="send_message",
                parameters={"destination": "to@example.com", "content": "Test"},
            )
            result = await email_provider.execute(request)

        assert result.status == ConnectorStatus.FAILURE
        assert "SMTP error" in result.error_message


# ---------------------------------------------------------------------------
# Email: notify_user
# ---------------------------------------------------------------------------


class TestEmailNotifyUser:
    async def test_notify_user_success(self, email_provider: EmailMessagingProvider) -> None:
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.sendmail = MagicMock()

        with patch(
            "agent_orchestrator.connectors.providers.messaging.email.smtplib.SMTP",
            return_value=mock_smtp_instance,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="notify_user",
                parameters={"user_id": "user@example.com", "content": "You have a notification"},
            )
            result = await email_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "notification"
        assert result.payload["normalized_payload"]["recipients"] == ["user@example.com"]


# ---------------------------------------------------------------------------
# Email: create_thread
# ---------------------------------------------------------------------------


class TestEmailCreateThread:
    async def test_create_thread_success(self, email_provider: EmailMessagingProvider) -> None:
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)
        mock_smtp_instance.sendmail = MagicMock()

        with patch(
            "agent_orchestrator.connectors.providers.messaging.email.smtplib.SMTP",
            return_value=mock_smtp_instance,
        ):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.MESSAGING,
                operation="create_thread",
                parameters={
                    "destination": "to@example.com",
                    "title": "Thread Title",
                    "content": "Thread body",
                },
            )
            result = await email_provider.execute(request)

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "thread"
        assert result.payload["normalized_payload"]["subject"] == "Thread Title"


# ---------------------------------------------------------------------------
# Email: unknown operation
# ---------------------------------------------------------------------------


class TestEmailUnknownOperation:
    async def test_unknown_operation_returns_not_found(
        self, email_provider: EmailMessagingProvider
    ) -> None:
        request = ConnectorInvocationRequest(
            capability_type=CapabilityType.MESSAGING,
            operation="delete_message",
            parameters={},
        )
        result = await email_provider.execute(request)
        assert result.status == ConnectorStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# _make_message_artifact static helper
# ---------------------------------------------------------------------------


class TestMakeMessageArtifact:
    def test_produces_external_artifact(self) -> None:
        from agent_orchestrator.connectors.models import ExternalReference

        artifact = BaseMessagingProvider._make_message_artifact(
            provider="messaging.slack",
            connector_id="messaging.slack",
            message_id="ts-123",
            channel="C12345",
            sender="bot",
            recipients=["U99999"],
            subject="Test Subject",
            body="Test body",
            raw_payload={"raw": "data"},
            resource_type="message",
            provenance={"provider": "slack"},
            references=[
                ExternalReference(
                    provider="messaging.slack",
                    resource_type="slack_message",
                    external_id="ts-123",
                )
            ],
        )

        assert isinstance(artifact, ExternalArtifact)
        assert artifact.capability_type == CapabilityType.MESSAGING
        assert artifact.resource_type == "message"
        assert artifact.raw_payload == {"raw": "data"}
        normalized = artifact.normalized_payload
        assert normalized["message_id"] == "ts-123"
        assert normalized["channel"] == "C12345"
        assert normalized["sender"] == "bot"
        assert normalized["recipients"] == ["U99999"]
        assert normalized["subject"] == "Test Subject"
        assert normalized["body"] == "Test body"
        assert len(artifact.references) == 1

    def test_produces_notification_resource_type(self) -> None:
        artifact = BaseMessagingProvider._make_message_artifact(
            provider="messaging.email",
            connector_id="messaging.email",
            message_id="<abc@agent-orchestrator>",
            channel="user@example.com",
            sender="from@example.com",
            recipients=["user@example.com"],
            subject=None,
            body="Notification body",
            raw_payload={},
            resource_type="notification",
            provenance={"provider": "email"},
        )

        assert artifact.resource_type == "notification"
        assert artifact.normalized_payload["subject"] is None

    def test_produces_thread_resource_type(self) -> None:
        artifact = BaseMessagingProvider._make_message_artifact(
            provider="messaging.teams",
            connector_id="messaging.teams",
            message_id="uuid-thread",
            channel="general",
            sender="Agent Orchestrator",
            recipients=["general"],
            subject="Thread Title",
            body="Thread body",
            raw_payload={},
            resource_type="thread",
            provenance={"provider": "teams"},
        )

        assert artifact.resource_type == "thread"
        assert artifact.normalized_payload["subject"] == "Thread Title"


# ---------------------------------------------------------------------------
# Package exports test
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_messaging_providers_exported(self) -> None:
        from agent_orchestrator.connectors.providers import (
            EmailMessagingProvider,
            SlackMessagingProvider,
            TeamsMessagingProvider,
        )

        assert SlackMessagingProvider is not None
        assert TeamsMessagingProvider is not None
        assert EmailMessagingProvider is not None

    def test_provider_ids_are_correct(self) -> None:
        slack = SlackMessagingProvider(bot_token="xoxb-test")
        teams = TeamsMessagingProvider(webhook_url="https://example.com/webhook")
        email = EmailMessagingProvider(
            smtp_host="smtp.example.com",
            username="u",
            password="p",
            from_address="u@example.com",
        )

        assert slack.provider_id == "messaging.slack"
        assert teams.provider_id == "messaging.teams"
        assert email.provider_id == "messaging.email"
