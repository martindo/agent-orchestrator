"""Shared base for messaging capability connector providers."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from ...models import (
    CapabilityType,
    ConnectorCostInfo,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorStatus,
    ExternalArtifact,
    ExternalReference,
)
from ...normalized import MessageArtifact

logger = logging.getLogger(__name__)

_MESSAGING_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="send_message",
        description="Send a message to a channel, room, or address",
        capability_type=CapabilityType.MESSAGING,
        read_only=False,
        required_parameters=["destination", "content"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="notify_user",
        description="Send a direct notification to a specific user",
        capability_type=CapabilityType.MESSAGING,
        read_only=False,
        required_parameters=["user_id", "content"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="create_thread",
        description="Create a new message thread with a title and initial content",
        capability_type=CapabilityType.MESSAGING,
        read_only=False,
        required_parameters=["destination", "title", "content"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="send_notification",
        description="Send a rich notification with title, message, and optional fields",
        capability_type=CapabilityType.MESSAGING,
        read_only=False,
        required_parameters=["destination", "title", "content"],
        optional_parameters=["color", "fields"],
    ),
    ConnectorOperationDescriptor(
        operation="list_channels",
        description="List available channels or rooms",
        capability_type=CapabilityType.MESSAGING,
        read_only=True,
        required_parameters=[],
        optional_parameters=["limit"],
    ),
    ConnectorOperationDescriptor(
        operation="upload_file",
        description="Upload file content to a channel",
        capability_type=CapabilityType.MESSAGING,
        read_only=False,
        required_parameters=["destination", "content", "filename"],
        optional_parameters=["title"],
    ),
]


class MessagingProviderError(Exception):
    """Raised when a messaging provider encounters an unrecoverable error."""


class BaseMessagingProvider(ABC):
    """Abstract base with common execute() dispatch for messaging providers.

    Subclasses implement _send_message(), _notify_user(), and
    _create_thread(). All three must return a tuple of (dict, ConnectorCostInfo | None)
    where the dict is an ExternalArtifact model_dump().
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.MESSAGING],
            operations=_MESSAGING_OPS,
            enabled=self.is_available(),
            auth_required=True,
            auth_type="api_key",
            version="1.0",
        )

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    def is_available(self) -> bool:
        """Return True if the provider has credentials configured."""
        return bool(getattr(self, "_api_token", None))

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        """Dispatch the request to the appropriate handler and return a result.

        Args:
            request: Connector invocation request with operation and parameters.

        Returns:
            ConnectorInvocationResult with status, payload as ExternalArtifact dict,
            and optional cost info.
        """
        start = time.monotonic()
        op = request.operation
        params = request.parameters

        try:
            if op == "send_message":
                payload, cost_info = await self._send_message(
                    destination=params["destination"],
                    content=params["content"],
                )
            elif op == "notify_user":
                payload, cost_info = await self._notify_user(
                    user_id=params["user_id"],
                    content=params["content"],
                )
            elif op == "create_thread":
                payload, cost_info = await self._create_thread(
                    destination=params["destination"],
                    title=params["title"],
                    content=params["content"],
                )
            elif op == "send_notification":
                payload, cost_info = await self._send_notification(
                    destination=params["destination"],
                    title=params["title"],
                    content=params["content"],
                    color=params.get("color", "#36a64f"),
                    fields=params.get("fields"),
                )
            elif op == "list_channels":
                payload, cost_info = await self._list_channels(
                    limit=int(params.get("limit", 100)),
                )
            elif op == "upload_file":
                payload, cost_info = await self._upload_file(
                    destination=params["destination"],
                    content=params["content"],
                    filename=params["filename"],
                    title=params.get("title", ""),
                )
            else:
                return ConnectorInvocationResult(
                    request_id=request.request_id,
                    connector_id=self.provider_id,
                    provider=self.provider_id,
                    capability_type=request.capability_type,
                    operation=op,
                    status=ConnectorStatus.NOT_FOUND,
                    error_message=f"Unknown operation: {op!r}",
                )
        except MessagingProviderError as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self.provider_id,
                provider=self.provider_id,
                capability_type=request.capability_type,
                operation=op,
                status=ConnectorStatus.FAILURE,
                error_message=str(exc),
                duration_ms=duration_ms,
            )

        duration_ms = (time.monotonic() - start) * 1000
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id=self.provider_id,
            provider=self.provider_id,
            capability_type=request.capability_type,
            operation=op,
            status=ConnectorStatus.SUCCESS,
            payload=payload,
            cost_info=cost_info,
            duration_ms=duration_ms,
        )

    @abstractmethod
    async def _send_message(
        self,
        destination: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _notify_user(
        self,
        user_id: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _create_thread(
        self,
        destination: str,
        title: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    async def _send_notification(
        self,
        destination: str,
        title: str,
        content: str,
        color: str,
        fields: list[dict] | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send a rich notification. Optional -- subclasses may override."""
        raise MessagingProviderError(
            f"{self.provider_id} does not support send_notification"
        )

    async def _list_channels(
        self,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List available channels. Optional -- subclasses may override."""
        raise MessagingProviderError(
            f"{self.provider_id} does not support list_channels"
        )

    async def _upload_file(
        self,
        destination: str,
        content: str,
        filename: str,
        title: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Upload file content to a channel. Optional -- subclasses may override."""
        raise MessagingProviderError(
            f"{self.provider_id} does not support upload_file"
        )

    @staticmethod
    def _make_message_artifact(
        provider: str,
        connector_id: str,
        message_id: str | None,
        channel: str | None,
        sender: str | None,
        recipients: list[str],
        subject: str | None,
        body: str | None,
        raw_payload: dict,
        resource_type: str,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap a message in a platform-standard ExternalArtifact.

        The normalized_payload contains a MessageArtifact-shaped dict.
        The raw_payload holds the provider's original response.

        Args:
            provider: Provider ID.
            connector_id: Connector ID (typically same as provider).
            message_id: Provider-specific message ID, or None.
            channel: Channel, room, or address the message was sent to.
            sender: Sender identifier, or None.
            recipients: List of recipient identifiers.
            subject: Message subject or thread title, or None.
            body: Message body text, or None.
            raw_payload: Raw provider API response dict.
            resource_type: "message", "notification", or "thread".
            provenance: Provenance dict (provider, channel, etc.).
            references: Optional list of ExternalReference for related resources.

        Returns:
            ExternalArtifact with normalized_payload containing MessageArtifact fields.
        """
        normalized = MessageArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.MESSAGING,
            message_id=message_id,
            channel=channel,
            sender=sender,
            recipients=recipients,
            subject=subject,
            body=body,
        )
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.MESSAGING,
            resource_type=resource_type,
            raw_payload=raw_payload,
            normalized_payload=normalized.model_dump(mode="json"),
            references=references or [],
            provenance=provenance,
        )
