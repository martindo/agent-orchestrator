"""Webhook Adapter — Outbound webhook notifications.

Sends event notifications to configured webhook endpoints.
Supports retry logic and payload customization.

Thread-safe: Stateless send function.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookConfig:
    """Configuration for a webhook endpoint."""

    id: str
    url: str
    events: list[str] = field(default_factory=list)  # Event types to send
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    # Delivery reliability
    max_retries: int = 3                 # additional attempts after the first
    retry_backoff_seconds: float = 0.5   # base for exponential backoff
    secret: str = ""                     # if set, sign the body (HMAC-SHA256)


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
        """Send a webhook notification via HTTP POST with retry + backoff.

        Retries transient failures (connection errors, timeouts, HTTP 5xx, and
        429) with exponential backoff up to ``max_retries`` extra attempts. A
        4xx (other than 429) is a client error and is **not** retried. On final
        failure the exception is re-raised so the caller records the failure —
        the old code swallowed it and reported success.

        If ``secret`` is set, the exact request bytes are signed with
        HMAC-SHA256 and sent as the ``X-Webhook-Signature: sha256=<hex>`` header.
        """
        body = {"event_type": event_type, "payload": payload}
        body_bytes = json.dumps(body, sort_keys=True, default=str).encode()
        headers = {"Content-Type": "application/json", **webhook.headers}
        if webhook.secret:
            signature = hmac.new(
                webhook.secret.encode(), body_bytes, hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        attempts = max(1, webhook.max_retries + 1)
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        webhook.url, content=body_bytes, headers=headers,
                    )
                if response.status_code < 400:
                    logger.debug(
                        "Webhook sent: %s -> %s (status=%d, attempt=%d)",
                        webhook.id, webhook.url, response.status_code, attempt,
                    )
                    return
                # 4xx (except 429) is a client error — do not retry.
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    response.raise_for_status()
                last_exc = httpx.HTTPStatusError(
                    f"webhook returned status {response.status_code}",
                    request=response.request, response=response,
                )
            except httpx.TransportError as exc:  # connect/read/timeout — transient
                last_exc = exc

            if attempt < attempts:
                delay = webhook.retry_backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "Webhook '%s' attempt %d/%d failed (%s); retrying in %.2fs",
                    webhook.id, attempt, attempts, last_exc, delay,
                )
                await asyncio.sleep(delay)

        if last_exc is not None:
            raise last_exc

    def list_webhooks(self) -> list[WebhookConfig]:
        """List all registered webhooks."""
        return list(self._webhooks.values())
