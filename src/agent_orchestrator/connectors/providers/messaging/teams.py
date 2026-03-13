"""Microsoft Teams messaging connector provider.

Implements send_message, notify_user, and create_thread via an
Incoming Webhook URL. No OAuth is required — the webhook URL is the
full endpoint provided by Teams channel configuration.

Limitations:
    - Incoming webhooks post to a fixed channel; they cannot DM users directly.
    - notify_user falls back to posting to the configured webhook channel with
      an @mention prefix prepended to the content body.
    - There is no returned message ID from the Teams webhook; a UUID is generated.
"""
from __future__ import annotations

import logging
import uuid

import httpx

from ...models import ConnectorCostInfo
from ._base import BaseMessagingProvider, MessagingProviderError

logger = logging.getLogger(__name__)

_TEAMS_THEME_COLOR = "0076D7"
_TEAMS_CONTEXT = "http://schema.org/extensions"
_TEAMS_TYPE = "MessageCard"


class TeamsMessagingProvider(BaseMessagingProvider):
    """Microsoft Teams incoming webhook messaging connector provider.

    All operations post to the single webhook channel configured at construction
    time. The webhook URL is created in Teams via:
    Channel Settings > Connectors > Incoming Webhook > Configure.

    Note: notify_user cannot DM users directly via incoming webhooks.
    It prepends "@<user_id> " to the message content as a text mention.

    Example::

        provider = TeamsMessagingProvider(
            webhook_url="https://outlook.office.com/webhook/...",
            sender_name="My Agent",
        )
    """

    def __init__(
        self,
        webhook_url: str,
        sender_name: str = "Agent Orchestrator",
    ) -> None:
        if not webhook_url:
            raise ValueError("TeamsMessagingProvider requires a non-empty webhook_url")
        self._webhook_url = webhook_url
        self._sender_name = sender_name
        self._api_token = webhook_url  # satisfies is_available() check

    @classmethod
    def from_env(cls) -> "TeamsMessagingProvider | None":
        """Create an instance from environment variables.

        Required env var: ``TEAMS_WEBHOOK_URL``
        Optional env var: ``TEAMS_SENDER_NAME``

        Returns None if ``TEAMS_WEBHOOK_URL`` is not set.
        """
        import os
        webhook_url = os.environ.get("TEAMS_WEBHOOK_URL", "")
        if not webhook_url:
            return None
        return cls(
            webhook_url=webhook_url,
            sender_name=os.environ.get("TEAMS_SENDER_NAME", "Agent Orchestrator"),
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "messaging.teams"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Microsoft Teams Messaging"

    async def _post_to_webhook(self, payload: dict) -> str:
        """POST a MessageCard payload to the Teams webhook.

        Args:
            payload: MessageCard dict to serialize and POST.

        Returns:
            Response text from Teams (should be "1" on success).

        Raises:
            MessagingProviderError: When the HTTP request fails or response is not "1".
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._webhook_url,
                    json=payload,
                )
                response.raise_for_status()
                response_text: str = response.text
        except httpx.HTTPError as exc:
            raise MessagingProviderError(f"Teams HTTP error: {exc}") from exc

        if response_text.strip() != "1":
            raise MessagingProviderError(
                f"Teams webhook returned unexpected response: {response_text!r}"
            )

        return response_text

    async def _send_message(
        self,
        destination: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send a message to the Teams webhook channel.

        Args:
            destination: Logical destination label (used in card summary).
            content: Message text to send.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the Teams webhook returns an error.
        """
        card_payload = {
            "@type": _TEAMS_TYPE,
            "@context": _TEAMS_CONTEXT,
            "summary": destination,
            "themeColor": _TEAMS_THEME_COLOR,
            "text": content,
        }

        response_text = await self._post_to_webhook(card_payload)
        message_id = str(uuid.uuid4())

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=message_id,
            channel=destination,
            sender=self._sender_name,
            recipients=[destination],
            subject=None,
            body=content,
            raw_payload={"webhook_response": response_text},
            resource_type="message",
            provenance={"provider": "teams"},
        )

        logger.info(
            "Teams send_message: destination=%r message_id=%r",
            destination,
            message_id,
        )

        return artifact.model_dump(mode="json"), None

    async def _notify_user(
        self,
        user_id: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send a notification to a user via the Teams webhook channel.

        Note: Teams incoming webhooks cannot send DMs. This method falls back
        to posting to the configured webhook channel with an @mention prefix.

        Args:
            user_id: User identifier to @mention in the message.
            content: Notification text to send.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the Teams webhook returns an error.
        """
        mention_content = f"@{user_id} {content}"

        card_payload = {
            "@type": _TEAMS_TYPE,
            "@context": _TEAMS_CONTEXT,
            "summary": f"Notification for {user_id}",
            "themeColor": _TEAMS_THEME_COLOR,
            "text": mention_content,
        }

        response_text = await self._post_to_webhook(card_payload)
        message_id = str(uuid.uuid4())

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=message_id,
            channel="webhook",
            sender=self._sender_name,
            recipients=[user_id],
            subject=None,
            body=mention_content,
            raw_payload={"webhook_response": response_text},
            resource_type="notification",
            provenance={"provider": "teams"},
        )

        logger.info(
            "Teams notify_user: user_id=%r message_id=%r",
            user_id,
            message_id,
        )

        return artifact.model_dump(mode="json"), None

    async def _create_thread(
        self,
        destination: str,
        title: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Create a new message thread in the Teams webhook channel.

        Posts a MessageCard with a title and body text.

        Args:
            destination: Logical destination label (used in card summary).
            title: Thread title shown as the card title.
            content: Thread body text.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the Teams webhook returns an error.
        """
        card_payload = {
            "@type": _TEAMS_TYPE,
            "@context": _TEAMS_CONTEXT,
            "summary": title,
            "themeColor": _TEAMS_THEME_COLOR,
            "title": title,
            "text": content,
        }

        response_text = await self._post_to_webhook(card_payload)
        message_id = str(uuid.uuid4())

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=message_id,
            channel=destination,
            sender=self._sender_name,
            recipients=[destination],
            subject=title,
            body=content,
            raw_payload={"webhook_response": response_text},
            resource_type="thread",
            provenance={"provider": "teams"},
        )

        logger.info(
            "Teams create_thread: destination=%r title=%r message_id=%r",
            destination,
            title,
            message_id,
        )

        return artifact.model_dump(mode="json"), None
