"""Slack messaging connector provider.

Implements send_message, notify_user, and create_thread against the
Slack Web API using a bot token (Bearer auth).
"""
from __future__ import annotations

import logging

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import BaseMessagingProvider, MessagingProviderError

logger = logging.getLogger(__name__)

_SLACK_API_BASE = "https://slack.com/api"


class SlackMessagingProvider(BaseMessagingProvider):
    """Slack-backed messaging connector provider.

    Uses the Slack Web API with a bot token. The bot must have the following
    OAuth scopes: chat:write, im:write, channels:read.

    Example::

        provider = SlackMessagingProvider(
            bot_token="xoxb-...",
            default_channel="#general",
        )
    """

    def __init__(
        self,
        bot_token: str,
        default_channel: str | None = None,
    ) -> None:
        if not bot_token:
            raise ValueError("SlackMessagingProvider requires a non-empty bot_token")
        self._api_token = bot_token
        self._default_channel = default_channel

    @classmethod
    def from_env(cls) -> "SlackMessagingProvider | None":
        """Create an instance from environment variables.

        Required env var: ``SLACK_BOT_TOKEN``
        Optional env var: ``SLACK_DEFAULT_CHANNEL``

        Returns None if ``SLACK_BOT_TOKEN`` is not set.
        """
        import os
        token = os.environ.get("SLACK_BOT_TOKEN", "")
        if not token:
            return None
        return cls(
            bot_token=token,
            default_channel=os.environ.get("SLACK_DEFAULT_CHANNEL") or None,
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "messaging.slack"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Slack Messaging"

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the Slack API."""
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

    def _api_url(self, method: str) -> str:
        """Build a full Slack API URL for the given method."""
        return f"{_SLACK_API_BASE}/{method}"

    async def _send_message(
        self,
        destination: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send a message to a Slack channel.

        Args:
            destination: Slack channel ID (e.g. "C12345") or channel name.
            content: Message text to send.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the Slack API returns an error.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._api_url("chat.postMessage"),
                    headers=self._auth_headers(),
                    json={"channel": destination, "text": content},
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise MessagingProviderError(f"Slack HTTP error: {exc}") from exc

        if not data.get("ok"):
            raise MessagingProviderError(
                f"Slack error: {data.get('error', 'unknown')}"
            )

        ts: str = data.get("ts", "")
        channel: str = data.get("channel", destination)

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="slack_message",
                external_id=ts,
                url=None,
                metadata={"channel": channel},
            )
        ]

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=ts,
            channel=channel,
            sender="bot",
            recipients=[destination],
            subject=None,
            body=content,
            raw_payload=data,
            resource_type="message",
            provenance={"provider": "slack"},
            references=refs,
        )

        logger.info(
            "Slack send_message: channel=%r ts=%r",
            channel,
            ts,
        )

        return artifact.model_dump(mode="json"), None

    async def _notify_user(
        self,
        user_id: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send a direct message notification to a Slack user.

        Opens a DM channel via conversations.open, then posts the message.

        Args:
            user_id: Slack user ID (e.g. "U12345").
            content: Notification text to send.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the Slack API returns an error.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                open_response = await client.post(
                    self._api_url("conversations.open"),
                    headers=self._auth_headers(),
                    json={"users": user_id},
                )
                open_response.raise_for_status()
                open_data: dict = open_response.json()

                if not open_data.get("ok"):
                    raise MessagingProviderError(
                        f"Slack conversations.open error: {open_data.get('error', 'unknown')}"
                    )

                dm_channel: str = open_data["channel"]["id"]

                post_response = await client.post(
                    self._api_url("chat.postMessage"),
                    headers=self._auth_headers(),
                    json={"channel": dm_channel, "text": content},
                )
                post_response.raise_for_status()
                post_data: dict = post_response.json()
        except httpx.HTTPError as exc:
            raise MessagingProviderError(f"Slack HTTP error: {exc}") from exc

        if not post_data.get("ok"):
            raise MessagingProviderError(
                f"Slack error: {post_data.get('error', 'unknown')}"
            )

        ts: str = post_data.get("ts", "")

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="slack_message",
                external_id=ts,
                url=None,
                metadata={"channel": dm_channel},
            )
        ]

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=ts,
            channel=dm_channel,
            sender="bot",
            recipients=[user_id],
            subject=None,
            body=content,
            raw_payload=post_data,
            resource_type="notification",
            provenance={"provider": "slack"},
            references=refs,
        )

        logger.info(
            "Slack notify_user: user_id=%r dm_channel=%r ts=%r",
            user_id,
            dm_channel,
            ts,
        )

        return artifact.model_dump(mode="json"), None

    async def _create_thread(
        self,
        destination: str,
        title: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Create a new message thread in a Slack channel.

        Posts the initial message that acts as the thread parent. Subsequent
        replies can reference the returned message ts as thread_ts.

        Args:
            destination: Slack channel ID or name.
            title: Thread title shown as bold header in the message.
            content: Thread body text.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the Slack API returns an error.
        """
        thread_text = f"*{title}*\n{content}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._api_url("chat.postMessage"),
                    headers=self._auth_headers(),
                    json={"channel": destination, "text": thread_text},
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise MessagingProviderError(f"Slack HTTP error: {exc}") from exc

        if not data.get("ok"):
            raise MessagingProviderError(
                f"Slack error: {data.get('error', 'unknown')}"
            )

        ts: str = data.get("ts", "")
        channel: str = data.get("channel", destination)

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="slack_message",
                external_id=ts,
                url=None,
                metadata={"channel": channel},
            )
        ]

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=ts,
            channel=channel,
            sender="bot",
            recipients=[destination],
            subject=title,
            body=content,
            raw_payload=data,
            resource_type="thread",
            provenance={"provider": "slack"},
            references=refs,
        )

        logger.info(
            "Slack create_thread: channel=%r title=%r ts=%r",
            channel,
            title,
            ts,
        )

        return artifact.model_dump(mode="json"), None

    async def _send_notification(
        self,
        destination: str,
        title: str,
        content: str,
        color: str,
        fields: list[dict] | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send a rich Block Kit notification to a Slack channel.

        Composes a message with a header block, a section block for the
        message body, and optional field blocks.

        Args:
            destination: Slack channel ID or name.
            title: Notification title (rendered as a Block Kit header).
            content: Notification body text (rendered as mrkdwn).
            color: Hex color string (used in fallback text only).
            fields: Optional list of dicts with ``label`` and ``value`` keys.

        Returns:
            Tuple of (ExternalArtifact dict, None -- no API cost).

        Raises:
            MessagingProviderError: When the Slack API returns an error.
        """
        blocks: list[dict] = [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": content}},
        ]
        if fields:
            field_elements = [
                {"type": "mrkdwn", "text": f"*{f['label']}:*\n{f['value']}"}
                for f in fields
            ]
            blocks.append({"type": "section", "fields": field_elements})

        fallback_text = f"{title}: {content}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._api_url("chat.postMessage"),
                    headers=self._auth_headers(),
                    json={
                        "channel": destination,
                        "text": fallback_text,
                        "blocks": blocks,
                    },
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise MessagingProviderError(f"Slack HTTP error: {exc}") from exc

        if not data.get("ok"):
            raise MessagingProviderError(
                f"Slack error: {data.get('error', 'unknown')}"
            )

        ts: str = data.get("ts", "")
        channel: str = data.get("channel", destination)

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="slack_message",
                external_id=ts,
                url=None,
                metadata={"channel": channel},
            )
        ]

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=ts,
            channel=channel,
            sender="bot",
            recipients=[destination],
            subject=title,
            body=content,
            raw_payload=data,
            resource_type="notification",
            provenance={"provider": "slack"},
            references=refs,
        )

        logger.info(
            "Slack send_notification: channel=%r title=%r ts=%r",
            channel,
            title,
            ts,
        )
        return artifact.model_dump(mode="json"), None

    async def _list_channels(
        self,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List public and private channels the bot has access to.

        Args:
            limit: Maximum number of channels to return.

        Returns:
            Tuple of (ExternalArtifact dict with channel list, None -- no API cost).

        Raises:
            MessagingProviderError: When the Slack API returns an error.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url("conversations.list"),
                    headers=self._auth_headers(),
                    params={
                        "types": "public_channel,private_channel",
                        "limit": min(limit, 1000),
                    },
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise MessagingProviderError(f"Slack HTTP error: {exc}") from exc

        if not data.get("ok"):
            raise MessagingProviderError(
                f"Slack error: {data.get('error', 'unknown')}"
            )

        channels = data.get("channels", [])
        items = [
            {
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "is_private": c.get("is_private", False),
            }
            for c in channels
        ]

        from ...models import ExternalArtifact, CapabilityType
        artifact = ExternalArtifact(
            source_connector=self.provider_id,
            provider=self.provider_id,
            capability_type=CapabilityType.MESSAGING,
            resource_type="channel_list",
            raw_payload={"total": len(items), "channels": items},
            normalized_payload=None,
            references=[],
            provenance={"provider": "slack"},
        )

        logger.info("Slack list_channels: count=%d", len(items))
        return artifact.model_dump(mode="json"), None

    async def _upload_file(
        self,
        destination: str,
        content: str,
        filename: str,
        title: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Upload text content as a file to a Slack channel.

        Args:
            destination: Slack channel ID or name.
            content: File content string.
            filename: Filename for the upload.
            title: File title displayed in Slack.

        Returns:
            Tuple of (ExternalArtifact dict, None -- no API cost).

        Raises:
            MessagingProviderError: When the Slack API returns an error.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._api_url("files.upload"),
                    headers={"Authorization": f"Bearer {self._api_token}"},
                    data={
                        "channels": destination,
                        "content": content,
                        "filename": filename,
                        "title": title or filename,
                    },
                )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise MessagingProviderError(f"Slack HTTP error: {exc}") from exc

        if not data.get("ok"):
            raise MessagingProviderError(
                f"Slack error: {data.get('error', 'unknown')}"
            )

        file_info = data.get("file", {})
        file_id: str = file_info.get("id", "")

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="slack_file",
                external_id=file_id,
                url=file_info.get("permalink"),
                metadata={"channel": destination, "filename": filename},
            )
        ]

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=file_id,
            channel=destination,
            sender="bot",
            recipients=[destination],
            subject=title or filename,
            body=None,
            raw_payload=data,
            resource_type="file_upload",
            provenance={"provider": "slack"},
            references=refs,
        )

        logger.info(
            "Slack upload_file: channel=%r filename=%r file_id=%r",
            destination,
            filename,
            file_id,
        )
        return artifact.model_dump(mode="json"), None
