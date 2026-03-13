"""Azure Active Directory (Microsoft Entra ID) identity connector provider.

Implements get_user, list_users, check_permission, and list_groups against
the Microsoft Graph API v1.0. Uses an OAuth2 client credentials grant to
obtain an access token scoped to ``https://graph.microsoft.com/.default``.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import BaseIdentityProvider, IdentityProviderError

logger = logging.getLogger(__name__)

_GRAPH_URL = "https://graph.microsoft.com/v1.0"


class AzureADIdentityProvider(BaseIdentityProvider):
    """Azure Active Directory-backed identity connector provider.

    Authenticates via an OAuth2 client credentials grant against
    ``https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token``.
    The access token is cached in memory and re-fetched on 401 responses.

    Example::

        provider = AzureADIdentityProvider(
            tenant_id="00000000-0000-0000-0000-000000000000",
            client_id="app-client-id",
            client_secret="app-client-secret",
        )
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        if not tenant_id:
            raise ValueError("AzureADIdentityProvider requires a non-empty tenant_id")
        if not client_id:
            raise ValueError("AzureADIdentityProvider requires a non-empty client_id")
        if not client_secret:
            raise ValueError(
                "AzureADIdentityProvider requires a non-empty client_secret"
            )
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        # Satisfies is_available() check in BaseIdentityProvider.
        self._api_token: str | None = client_id
        self._access_token: str | None = None
        self._token_lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "AzureADIdentityProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``,
        ``AZURE_CLIENT_SECRET``

        Returns None if any required env var is missing.
        """
        import os

        tenant_id = os.environ.get("AZURE_TENANT_ID", "")
        client_id = os.environ.get("AZURE_CLIENT_ID", "")
        client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")
        if not tenant_id or not client_id or not client_secret:
            return None
        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "identity.azure_ad"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Azure Active Directory"

    async def _get_access_token(self) -> str:
        """Fetch a Graph API access token via the client credentials grant.

        The token is cached in ``self._access_token``. Callers that receive
        a 401 should clear ``self._access_token`` and retry once.

        Returns:
            Access token string.

        Raises:
            IdentityProviderError: On HTTP or JSON errors.
        """
        async with self._token_lock:
            if self._access_token:
                return self._access_token

            url = (
                f"https://login.microsoftonline.com/{self._tenant_id}"
                "/oauth2/v2.0/token"
            )
            data = {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, data=data)
                    response.raise_for_status()
                    payload: dict = response.json()
            except httpx.HTTPError as exc:
                raise IdentityProviderError(
                    f"Azure AD token fetch HTTP error: {exc}"
                ) from exc

            token: str | None = payload.get("access_token")
            if not token:
                raise IdentityProviderError(
                    "Azure AD token response did not contain an access_token"
                )
            self._access_token = token
            return token

    async def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the Microsoft Graph API."""
        token = await self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _get_user(
        self,
        user_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve an Azure AD user profile, group memberships, and role assignments.

        Args:
            user_id: Azure AD user object ID or UPN (e.g. ``user@domain.com``).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        headers = await self._auth_headers()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                user_resp = await client.get(
                    f"{_GRAPH_URL}/users/{user_id}", headers=headers
                )
                if user_resp.status_code == 401:
                    self._access_token = None
                    headers = await self._auth_headers()
                    user_resp = await client.get(
                        f"{_GRAPH_URL}/users/{user_id}", headers=headers
                    )
                user_resp.raise_for_status()
                user_data: dict = user_resp.json()

                member_resp = await client.get(
                    f"{_GRAPH_URL}/users/{user_id}/memberOf", headers=headers
                )
                member_resp.raise_for_status()
                member_data: dict = member_resp.json()

                roles_resp = await client.get(
                    f"{_GRAPH_URL}/users/{user_id}/appRoleAssignments",
                    headers=headers,
                )
                roles_resp.raise_for_status()
                roles_data: dict = roles_resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise IdentityProviderError(
                    f"Azure AD user not found: {user_id}"
                ) from exc
            raise IdentityProviderError(f"Azure AD HTTP error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Azure AD HTTP error: {exc}") from exc

        groups = [
            m.get("displayName", "") for m in member_data.get("value", [])
            if m.get("displayName")
        ]
        roles = [
            r.get("principalDisplayName") or r.get("resourceDisplayName", "")
            for r in roles_data.get("value", [])
            if r.get("principalDisplayName") or r.get("resourceDisplayName")
        ]

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="azure_ad_user",
                external_id=user_data.get("id", user_id),
                url=None,
                metadata={"tenant_id": self._tenant_id},
            )
        ]

        artifact = self._make_user_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            principal_id=user_data.get("id", user_id),
            display_name=user_data.get("displayName"),
            email=user_data.get("mail") or user_data.get("userPrincipalName"),
            roles=roles,
            groups=groups,
            raw_payload=user_data,
            provenance={"provider": "azure_ad", "tenant_id": self._tenant_id},
            references=refs,
        )

        logger.info("Azure AD get_user: user_id=%r", user_id)
        return artifact.model_dump(mode="json"), None

    async def _list_users(
        self,
        query: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List or search users in the Azure AD directory.

        Uses ``$search`` with ``ConsistencyLevel: eventual`` when a query is
        provided, otherwise lists users with ``$top``.

        Args:
            query: Optional display name or UPN search string.
            limit: Maximum number of results to return (default 25).

        Returns:
            Tuple of (ExternalArtifact dict with resource_type "users",
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        headers = await self._auth_headers()
        params: dict = {"$top": limit}
        if query:
            headers = {**headers, "ConsistencyLevel": "eventual"}
            params["$search"] = (
                f'"displayName:{query}" OR "userPrincipalName:{query}"'
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_GRAPH_URL}/users", headers=headers, params=params
                )
                if response.status_code == 401:
                    self._access_token = None
                    headers = await self._auth_headers()
                    if query:
                        headers = {**headers, "ConsistencyLevel": "eventual"}
                    response = await client.get(
                        f"{_GRAPH_URL}/users", headers=headers, params=params
                    )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Azure AD HTTP error: {exc}") from exc

        users: list[dict] = data.get("value", [])
        items = [_normalize_azure_user(u) for u in users]
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="users",
            items=items,
            raw_payload={"query": query, "total": len(users), "items": items},
            provenance={"provider": "azure_ad", "tenant_id": self._tenant_id},
        )

        logger.info("Azure AD list_users: query=%r count=%d", query, len(users))
        return artifact.model_dump(mode="json"), None

    async def _check_permission(
        self,
        user_id: str,
        permission: str,
        resource: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Check whether an Azure AD user is a member of a group matching a permission.

        Fetches the user's group memberships and app role assignments, then
        checks whether the permission name appears in any group display name
        or role display name.

        Args:
            user_id: Azure AD user object ID or UPN.
            permission: Group or role name to check membership for.
            resource: Optional resource scope hint (not used in the check).

        Returns:
            Tuple of (ExternalArtifact dict with metadata has_permission,
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        headers = await self._auth_headers()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                user_resp = await client.get(
                    f"{_GRAPH_URL}/users/{user_id}", headers=headers
                )
                if user_resp.status_code == 401:
                    self._access_token = None
                    headers = await self._auth_headers()
                    user_resp = await client.get(
                        f"{_GRAPH_URL}/users/{user_id}", headers=headers
                    )
                user_resp.raise_for_status()
                user_data: dict = user_resp.json()

                member_resp = await client.get(
                    f"{_GRAPH_URL}/users/{user_id}/memberOf", headers=headers
                )
                member_resp.raise_for_status()
                member_data: dict = member_resp.json()

                roles_resp = await client.get(
                    f"{_GRAPH_URL}/users/{user_id}/appRoleAssignments",
                    headers=headers,
                )
                roles_resp.raise_for_status()
                roles_data: dict = roles_resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise IdentityProviderError(
                    f"Azure AD user not found: {user_id}"
                ) from exc
            raise IdentityProviderError(f"Azure AD HTTP error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Azure AD HTTP error: {exc}") from exc

        group_names = [
            m.get("displayName", "") for m in member_data.get("value", [])
        ]
        role_names = [
            r.get("principalDisplayName") or r.get("resourceDisplayName", "")
            for r in roles_data.get("value", [])
        ]
        all_names = group_names + role_names
        has_permission = permission in all_names or any(
            permission.lower() in name.lower() for name in all_names if name
        )

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="azure_ad_user",
                external_id=user_data.get("id", user_id),
                url=None,
                metadata={
                    "tenant_id": self._tenant_id,
                    "permission_checked": permission,
                },
            )
        ]

        artifact = self._make_user_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            principal_id=user_data.get("id", user_id),
            display_name=user_data.get("displayName"),
            email=user_data.get("mail") or user_data.get("userPrincipalName"),
            roles=[n for n in role_names if n],
            groups=[n for n in group_names if n],
            raw_payload={
                "user": user_data,
                "memberOf": member_data.get("value", []),
                "appRoleAssignments": roles_data.get("value", []),
                "has_permission": has_permission,
                "permission_checked": permission,
            },
            provenance={"provider": "azure_ad", "tenant_id": self._tenant_id},
            references=refs,
        )

        artifact_dict = artifact.model_dump(mode="json")
        if isinstance(artifact_dict.get("normalized_payload"), dict):
            artifact_dict["normalized_payload"]["metadata"] = {
                "has_permission": has_permission,
                "permission_checked": permission,
                "resource": resource,
            }

        logger.info(
            "Azure AD check_permission: user_id=%r permission=%r result=%s",
            user_id,
            permission,
            has_permission,
        )
        return artifact_dict, None

    async def _list_groups(
        self,
        query: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List groups defined in the Azure AD directory.

        Args:
            query: Optional display name filter using ``$search``.
            limit: Maximum number of results to return (default 25).

        Returns:
            Tuple of (ExternalArtifact dict with resource_type "groups",
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        headers = await self._auth_headers()
        params: dict = {"$top": limit}
        if query:
            headers = {**headers, "ConsistencyLevel": "eventual"}
            params["$search"] = f'"displayName:{query}"'

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_GRAPH_URL}/groups", headers=headers, params=params
                )
                if response.status_code == 401:
                    self._access_token = None
                    headers = await self._auth_headers()
                    if query:
                        headers = {**headers, "ConsistencyLevel": "eventual"}
                    response = await client.get(
                        f"{_GRAPH_URL}/groups", headers=headers, params=params
                    )
                response.raise_for_status()
                data: dict = response.json()
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Azure AD HTTP error: {exc}") from exc

        groups: list[dict] = data.get("value", [])
        items = [_normalize_azure_group(g) for g in groups]
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="groups",
            items=items,
            raw_payload={"query": query, "total": len(groups), "items": items},
            provenance={"provider": "azure_ad", "tenant_id": self._tenant_id},
        )

        logger.info("Azure AD list_groups: query=%r count=%d", query, len(groups))
        return artifact.model_dump(mode="json"), None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _normalize_azure_user(user: dict) -> dict:
    """Convert a raw Azure AD user dict to a compact summary dict."""
    return {
        "principal_id": user.get("id", ""),
        "display_name": user.get("displayName"),
        "email": user.get("mail") or user.get("userPrincipalName"),
        "job_title": user.get("jobTitle"),
        "department": user.get("department"),
    }


def _normalize_azure_group(group: dict) -> dict:
    """Convert a raw Azure AD group dict to a compact summary dict."""
    return {
        "group_id": group.get("id", ""),
        "name": group.get("displayName", ""),
        "description": group.get("description"),
        "mail": group.get("mail"),
        "group_types": group.get("groupTypes", []),
    }
