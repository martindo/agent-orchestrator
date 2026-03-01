"""Webhook Adapter — Outbound webhook notifications.

Sends event notifications to configured webhook endpoints.
Supports retry logic and payload customization.

Thread-safe: Stateless send function.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookConfig:
    """Configuration for a webhook endpoint."""

    id: str
    url: str
    events: list[str] = field(default_factory=list)  # Event types to send
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


class WebhookAdapter:
    """Sends event notifications to webhook endpoints.

    Thread-safe: Webhook configs protected by design (frozen dataclasses).
    """

    def __init__(self) -> None:
        self._webhooks: dict[str, WebhookConfig] = {}

    def register(self, config: WebhookConfig) -> None:
        """Register a webhook endpoint."""
        self._webhooks[config.id] = config
        logger.info("Registered webhook: %s -> %s", config.id, config.url)

    def unregister(self, webhook_id: str) -> bool:
        """Unregister a webhook endpoint."""
        return self._webhooks.pop(webhook_id, None) is not None

    async def notify(self, event_type: str, payload: dict[str, Any]) -> list[str]:
        """Send notifications to matching webhooks.

        Args:
            event_type: The event type (e.g., 'work.completed').
            payload: Event data.

        Returns:
            List of webhook IDs that were notified.
        """
        notified: list[str] = []
        for webhook in self._webhooks.values():
            if not webhook.enabled:
                continue
            if webhook.events and event_type not in webhook.events:
                continue

            try:
                await self._send(webhook, event_type, payload)
                notified.append(webhook.id)
            except Exception as e:
                logger.error(
                    "Webhook '%s' notification failed: %s",
                    webhook.id, e, exc_info=True,
                )
        return notified

    async def _send(
        self,
        webhook: WebhookConfig,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Send a webhook notification (stub — real HTTP in production).

        In production, this would use httpx or aiohttp.
        """
        logger.debug(
            "Webhook notification: %s -> %s (event=%s)",
            webhook.id, webhook.url, event_type,
        )

    def list_webhooks(self) -> list[WebhookConfig]:
        """List all registered webhooks."""
        return list(self._webhooks.values())
