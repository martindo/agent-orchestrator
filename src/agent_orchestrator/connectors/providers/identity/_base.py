"""Shared base for identity capability connector providers."""
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
from ...normalized import IdentityArtifact

logger = logging.getLogger(__name__)

_IDENTITY_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="get_user",
        description="Retrieve a user profile by ID or email",
        capability_type=CapabilityType.IDENTITY,
        read_only=True,
        required_parameters=["user_id"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="list_users",
        description="List or search users in the directory",
        capability_type=CapabilityType.IDENTITY,
        read_only=True,
        required_parameters=[],
        optional_parameters=["query", "limit"],
    ),
    ConnectorOperationDescriptor(
        operation="check_permission",
        description="Check whether a user holds a specific permission or role",
        capability_type=CapabilityType.IDENTITY,
        read_only=True,
        required_parameters=["user_id", "permission"],
        optional_parameters=["resource"],
    ),
    ConnectorOperationDescriptor(
        operation="list_groups",
        description="List groups or roles defined in the directory",
        capability_type=CapabilityType.IDENTITY,
        read_only=True,
        required_parameters=[],
        optional_parameters=["query", "limit"],
    ),
]


class IdentityProviderError(Exception):
    """Raised when an identity provider encounters an unrecoverable error."""


class BaseIdentityProvider(ABC):
    """Abstract base with common execute() dispatch for identity providers.

    Subclasses implement _get_user(), _list_users(), _check_permission(),
    and _list_groups(). Each must return a tuple of
    (dict, ConnectorCostInfo | None) where the dict is an ExternalArtifact
    model_dump().

    All operations are read_only=True — identity providers expose directory
    data but do not mutate it through this connector interface.
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.IDENTITY],
            operations=_IDENTITY_OPS,
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
        except IdentityProviderError as exc:
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
        if op == "get_user":
            return await self._get_user(user_id=params["user_id"])
        if op == "list_users":
            return await self._list_users(
                query=params.get("query"),
                limit=int(params.get("limit", 25)),
            )
        if op == "check_permission":
            return await self._check_permission(
                user_id=params["user_id"],
                permission=params["permission"],
                resource=params.get("resource"),
            )
        if op == "list_groups":
            return await self._list_groups(
                query=params.get("query"),
                limit=int(params.get("limit", 25)),
            )
        return None, None

    @abstractmethod
    async def _get_user(
        self,
        user_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _list_users(
        self,
        query: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _check_permission(
        self,
        user_id: str,
        permission: str,
        resource: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _list_groups(
        self,
        query: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @staticmethod
    def _make_user_artifact(
        provider: str,
        connector_id: str,
        principal_id: str,
        display_name: str | None,
        email: str | None,
        roles: list[str],
        groups: list[str],
        raw_payload: dict,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap a user principal in a platform-standard ExternalArtifact.

        The normalized_payload contains an IdentityArtifact-shaped dict.
        The raw_payload holds the provider's original response.

        Args:
            provider: Provider ID.
            connector_id: Connector ID (typically same as provider).
            principal_id: Provider-specific user/principal ID.
            display_name: Human-readable name for the user, or None.
            email: User email address, or None.
            roles: List of role names assigned to the user.
            groups: List of group names the user belongs to.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict (provider, domain, etc.).
            references: Optional list of ExternalReference for related resources.

        Returns:
            ExternalArtifact with normalized_payload containing IdentityArtifact
            fields.
        """
        normalized = IdentityArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.IDENTITY,
            principal_id=principal_id,
            display_name=display_name,
            email=email,
            roles=roles,
            groups=groups,
        )
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.IDENTITY,
            resource_type="user",
            raw_payload=raw_payload,
            normalized_payload=normalized.model_dump(mode="json"),
            references=references or [],
            provenance=provenance,
        )

    @staticmethod
    def _make_list_artifact(
        provider: str,
        connector_id: str,
        resource_type: str,
        items: list[dict],
        raw_payload: dict,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap a list of directory objects in a platform-standard ExternalArtifact.

        The raw_payload holds the full result set. normalized_payload is omitted
        because IdentityArtifact represents a single principal, not a list.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            resource_type: "users" for user lists, "groups" for group lists.
            items: List of item dicts summarising each directory object.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict.

        Returns:
            ExternalArtifact with the given resource_type.
        """
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.IDENTITY,
            resource_type=resource_type,
            raw_payload=raw_payload,
            normalized_payload=None,
            references=[],
            provenance=provenance,
        )
