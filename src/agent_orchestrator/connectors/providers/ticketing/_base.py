"""Shared base for ticketing capability connector providers."""
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
from ...normalized import TicketArtifact

logger = logging.getLogger(__name__)

_TICKETING_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="create_ticket",
        description="Create a new ticket or issue in the tracking system",
        capability_type=CapabilityType.TICKETING,
        read_only=False,
        required_parameters=["summary"],
        optional_parameters=["project", "description", "issue_type", "priority", "assignee"],
    ),
    ConnectorOperationDescriptor(
        operation="update_ticket",
        description="Update an existing ticket or issue by ID",
        capability_type=CapabilityType.TICKETING,
        read_only=False,
        required_parameters=["ticket_id", "changes"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="get_ticket",
        description="Retrieve a single ticket or issue by ID",
        capability_type=CapabilityType.TICKETING,
        read_only=True,
        required_parameters=["ticket_id"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="search_tickets",
        description="Search tickets or issues using a provider query string",
        capability_type=CapabilityType.TICKETING,
        read_only=True,
        required_parameters=["query"],
        optional_parameters=["limit"],
    ),
]


class TicketingProviderError(Exception):
    """Raised when a ticketing provider encounters an unrecoverable error."""


class BaseTicketingProvider(ABC):
    """Abstract base with common execute() dispatch for ticketing providers.

    Subclasses implement _create_ticket(), _update_ticket(), _get_ticket(),
    and _search_tickets(). Each must return a tuple of
    (dict, ConnectorCostInfo | None) where the dict is an ExternalArtifact
    model_dump().

    Write operations (create_ticket, update_ticket) are flagged read_only=False
    in the descriptor, ensuring that permission policies with
    requires_approval=True gate them through the REQUIRES_APPROVAL path.
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.TICKETING],
            operations=_TICKETING_OPS,
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
            ConnectorInvocationResult with status, payload as ExternalArtifact
            dict, and optional cost info.
        """
        start = time.monotonic()
        op = request.operation
        params = request.parameters

        try:
            payload, cost_info = await self._dispatch(op, params)
        except TicketingProviderError as exc:
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

        if payload is None:
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self.provider_id,
                provider=self.provider_id,
                capability_type=request.capability_type,
                operation=op,
                status=ConnectorStatus.NOT_FOUND,
                error_message=f"Unknown operation: {op!r}",
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

    async def _dispatch(
        self, op: str, params: dict
    ) -> tuple[dict, ConnectorCostInfo | None] | tuple[None, None]:
        """Route an operation name to the corresponding handler method."""
        if op == "create_ticket":
            return await self._create_ticket(
                summary=params["summary"],
                project=params.get("project"),
                description=params.get("description"),
                issue_type=params.get("issue_type"),
                priority=params.get("priority"),
                assignee=params.get("assignee"),
            )
        if op == "update_ticket":
            return await self._update_ticket(
                ticket_id=params["ticket_id"],
                changes=params["changes"],
            )
        if op == "get_ticket":
            return await self._get_ticket(ticket_id=params["ticket_id"])
        if op == "search_tickets":
            return await self._search_tickets(
                query=params["query"],
                limit=int(params.get("limit", 25)),
            )
        return None, None

    @abstractmethod
    async def _create_ticket(
        self,
        summary: str,
        project: str | None,
        description: str | None,
        issue_type: str | None,
        priority: str | None,
        assignee: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _update_ticket(
        self,
        ticket_id: str,
        changes: dict,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _get_ticket(
        self,
        ticket_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _search_tickets(
        self,
        query: str,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @staticmethod
    def _make_ticket_artifact(
        provider: str,
        connector_id: str,
        ticket_id: str,
        title: str,
        description: str | None,
        status: str | None,
        priority: str | None,
        assignee: str | None,
        url: str | None,
        raw_payload: dict,
        resource_type: str,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap a ticket in a platform-standard ExternalArtifact.

        The normalized_payload contains a TicketArtifact-shaped dict.
        The raw_payload holds the provider's original response.

        Args:
            provider: Provider ID.
            connector_id: Connector ID (typically same as provider).
            ticket_id: Provider-specific ticket/issue ID.
            title: Ticket title or summary.
            description: Ticket description body, or None.
            status: Ticket workflow status, or None.
            priority: Ticket priority label, or None.
            assignee: Assignee identifier or display name, or None.
            url: Web URL to the ticket, or None.
            raw_payload: Raw provider API response dict.
            resource_type: "ticket" for single tickets.
            provenance: Provenance dict (provider, project, etc.).
            references: Optional list of ExternalReference for related resources.

        Returns:
            ExternalArtifact with normalized_payload containing TicketArtifact
            fields.
        """
        normalized = TicketArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.TICKETING,
            ticket_id=ticket_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            assignee=assignee,
            url=url,
        )
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.TICKETING,
            resource_type=resource_type,
            raw_payload=raw_payload,
            normalized_payload=normalized.model_dump(mode="json"),
            references=references or [],
            provenance=provenance,
        )

    @staticmethod
    def _make_ticket_list_artifact(
        provider: str,
        connector_id: str,
        query: str,
        items: list[dict],
        total: int,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap a list of ticket search results in a platform-standard ExternalArtifact.

        The raw_payload holds the full result set. normalized_payload is omitted
        because TicketArtifact represents a single ticket, not a list.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            query: Original search query.
            items: List of ticket dicts with keys ticket_id, title, status,
                priority, assignee, url.
            total: Total result count reported by the provider.
            provenance: Provenance dict.

        Returns:
            ExternalArtifact with resource_type "ticket_list".
        """
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.TICKETING,
            resource_type="ticket_list",
            raw_payload={"query": query, "total": total, "items": items},
            normalized_payload=None,
            references=[],
            provenance=provenance,
        )
