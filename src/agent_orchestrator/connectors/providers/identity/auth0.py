"""Auth0 identity connector provider.

Implements get_user, list_users, check_permission, and list_groups against
the Auth0 Management API v2. Uses an M2M client credentials grant to obtain
a short-lived management API token.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import BaseIdentityProvider, IdentityProviderError

logger = logging.getLogger(__name__)


class Auth0IdentityProvider(BaseIdentityProvider):
    """Auth0-backed identity connector provider.

    Authenticates via the client credentials grant against
    ``https://{domain}/oauth/token`` to obtain a Management API token.
    The token is cached in memory and re-fetched on 401 responses.

    Example::

        provider = Auth0IdentityProvider(
            domain="myorg.auth0.com",
            client_id="abc123",
            client_secret="supersecret",
        )
    """

    def __init__(
        self,
        domain: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        if not domain:
            raise ValueError("Auth0IdentityProvider requires a non-empty domain")
        if not client_id:
            raise ValueError("Auth0IdentityProvider requires a non-empty client_id")
        if not client_secret:
            raise ValueError("Auth0IdentityProvider requires a non-empty client_secret")
        self._domain = domain.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        # Satisfies is_available() check in BaseIdentityProvider.
        self._api_token: str | None = client_id
        self._mgmt_token: str | None = None
        self._token_lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "Auth0IdentityProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``AUTH0_DOMAIN``, ``AUTH0_CLIENT_ID``,
        ``AUTH0_CLIENT_SECRET``

        Returns None if any required env var is missing.
        """
        import os

        domain = os.environ.get("AUTH0_DOMAIN", "")
        client_id = os.environ.get("AUTH0_CLIENT_ID", "")
        client_secret = os.environ.get("AUTH0_CLIENT_SECRET", "")
        if not domain or not client_id or not client_secret:
            return None
        return cls(domain=domain, client_id=client_id, client_secret=client_secret)

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "identity.auth0"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Auth0 Identity"

    async def _get_mgmt_token(self) -> str:
        """Fetch a Management API token via the client credentials grant.

        The token is cached in ``self._mgmt_token``. Call this method before
        every Management API request; callers that receive a 401 should clear
        ``self._mgmt_token`` and retry once.

        Returns:
            Access token string.

        Raises:
            IdentityProviderError: On HTTP or JSON errors.
        """
        async with self._token_lock:
            if self._mgmt_token:
                return self._mgmt_token

            url = f"https://{self._domain}/oauth/token"
            payload = {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "audience": f"https://{self._domain}/api/v2/",
                "grant_type": "client_credentials",
            }
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data: dict = response.json()
            except httpx.HTTPError as exc:
                raise IdentityProviderError(
                    f"Auth0 token fetch HTTP error: {exc}"
                ) from exc

            token: str | None = data.get("access_token")
            if not token:
                raise IdentityProviderError(
                    "Auth0 token response did not contain an access_token"
                )
            self._mgmt_token = token
            return token

    async def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the Management API."""
        token = await self._get_mgmt_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _get_user(
        self,
        user_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve an Auth0 user profile and their assigned roles.

        Args:
            user_id: Auth0 user ID (e.g. ``auth0|abc123``).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        base = f"https://{self._domain}/api/v2"
        headers = await self._auth_headers()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                user_resp = await client.get(
                    f"{base}/users/{user_id}", headers=headers
                )
                if user_resp.status_code == 401:
                    self._mgmt_token = None
                    headers = await self._auth_headers()
                    user_resp = await client.get(
                        f"{base}/users/{user_id}", headers=headers
                    )
                user_resp.raise_for_status()
                user_data: dict = user_resp.json()

                roles_resp = await client.get(
                    f"{base}/users/{user_id}/roles", headers=headers
                )
                roles_resp.raise_for_status()
                roles_data: list[dict] = roles_resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise IdentityProviderError(
                    f"Auth0 user not found: {user_id}"
                ) from exc
            raise IdentityProviderError(f"Auth0 HTTP error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Auth0 HTTP error: {exc}") from exc

        roles = [r.get("name", "") for r in roles_data if r.get("name")]
        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="auth0_user",
                external_id=user_id,
                url=None,
                metadata={"domain": self._domain},
            )
        ]

        artifact = self._make_user_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            principal_id=user_data.get("user_id", user_id),
            display_name=user_data.get("name"),
            email=user_data.get("email"),
            roles=roles,
            groups=[],
            raw_payload=user_data,
            provenance={"provider": "auth0", "domain": self._domain},
            references=refs,
        )

        logger.info("Auth0 get_user: user_id=%r", user_id)
        return artifact.model_dump(mode="json"), None

    async def _list_users(
        self,
        query: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List or search users in the Auth0 directory.

        Args:
            query: Optional Lucene search query (e.g. ``email:*example.com``).
            limit: Maximum number of results to return (default 25).

        Returns:
            Tuple of (ExternalArtifact dict with resource_type "users",
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        base = f"https://{self._domain}/api/v2"
        headers = await self._auth_headers()
        params: dict = {"per_page": limit}
        if query:
            params["q"] = query

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{base}/users", headers=headers, params=params
                )
                if response.status_code == 401:
                    self._mgmt_token = None
                    headers = await self._auth_headers()
                    response = await client.get(
                        f"{base}/users", headers=headers, params=params
                    )
                response.raise_for_status()
                users: list[dict] = response.json()
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Auth0 HTTP error: {exc}") from exc

        items = [_normalize_auth0_user(u) for u in users]
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="users",
            items=items,
            raw_payload={"query": query, "total": len(users), "items": items},
            provenance={"provider": "auth0", "domain": self._domain},
        )

        logger.info("Auth0 list_users: query=%r count=%d", query, len(users))
        return artifact.model_dump(mode="json"), None

    async def _check_permission(
        self,
        user_id: str,
        permission: str,
        resource: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Check whether an Auth0 user holds a specific permission.

        Fetches the user's assigned permissions and checks for a match by
        ``permission_name``. The ``resource`` argument is accepted for
        interface compatibility but is not used in the permission lookup.

        Args:
            user_id: Auth0 user ID.
            permission: Permission name to check (e.g. ``read:users``).
            resource: Optional resource scope hint (not used by Auth0 check).

        Returns:
            Tuple of (ExternalArtifact dict with metadata has_permission,
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        base = f"https://{self._domain}/api/v2"
        headers = await self._auth_headers()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                user_resp = await client.get(
                    f"{base}/users/{user_id}", headers=headers
                )
                if user_resp.status_code == 401:
                    self._mgmt_token = None
                    headers = await self._auth_headers()
                    user_resp = await client.get(
                        f"{base}/users/{user_id}", headers=headers
                    )
                user_resp.raise_for_status()
                user_data: dict = user_resp.json()

                perms_resp = await client.get(
                    f"{base}/users/{user_id}/permissions", headers=headers
                )
                perms_resp.raise_for_status()
                perms_data: list[dict] = perms_resp.json()

                roles_resp = await client.get(
                    f"{base}/users/{user_id}/roles", headers=headers
                )
                roles_resp.raise_for_status()
                roles_data: list[dict] = roles_resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise IdentityProviderError(
                    f"Auth0 user not found: {user_id}"
                ) from exc
            raise IdentityProviderError(f"Auth0 HTTP error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Auth0 HTTP error: {exc}") from exc

        perm_names = {p.get("permission_name", "") for p in perms_data}
        has_permission = permission in perm_names
        roles = [r.get("name", "") for r in roles_data if r.get("name")]

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="auth0_user",
                external_id=user_id,
                url=None,
                metadata={"domain": self._domain, "permission_checked": permission},
            )
        ]

        artifact = self._make_user_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            principal_id=user_data.get("user_id", user_id),
            display_name=user_data.get("name"),
            email=user_data.get("email"),
            roles=roles,
            groups=[],
            raw_payload={
                "user": user_data,
                "permissions": perms_data,
                "has_permission": has_permission,
                "permission_checked": permission,
            },
            provenance={"provider": "auth0", "domain": self._domain},
            references=refs,
        )

        # Attach has_permission to normalized_payload metadata by post-processing
        # the artifact dict so we do not mutate the frozen Pydantic model.
        artifact_dict = artifact.model_dump(mode="json")
        if isinstance(artifact_dict.get("normalized_payload"), dict):
            artifact_dict["normalized_payload"]["metadata"] = {
                "has_permission": has_permission,
                "permission_checked": permission,
                "resource": resource,
            }

        logger.info(
            "Auth0 check_permission: user_id=%r permission=%r result=%s",
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
        """List Auth0 roles (used as groups in the identity abstraction).

        Args:
            query: Optional name filter (not natively supported; post-filtered).
            limit: Maximum number of results to return (default 25).

        Returns:
            Tuple of (ExternalArtifact dict with resource_type "groups",
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        base = f"https://{self._domain}/api/v2"
        headers = await self._auth_headers()
        params: dict = {"per_page": limit}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{base}/roles", headers=headers, params=params
                )
                if response.status_code == 401:
                    self._mgmt_token = None
                    headers = await self._auth_headers()
                    response = await client.get(
                        f"{base}/roles", headers=headers, params=params
                    )
                response.raise_for_status()
                roles: list[dict] = response.json()
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Auth0 HTTP error: {exc}") from exc

        if query:
            q_lower = query.lower()
            roles = [
                r for r in roles if q_lower in r.get("name", "").lower()
            ]

        items = [_normalize_auth0_role(r) for r in roles]
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="groups",
            items=items,
            raw_payload={"query": query, "total": len(roles), "items": items},
            provenance={"provider": "auth0", "domain": self._domain},
        )

        logger.info("Auth0 list_groups: query=%r count=%d", query, len(roles))
        return artifact.model_dump(mode="json"), None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _normalize_auth0_user(user: dict) -> dict:
    """Convert a raw Auth0 user dict to a compact summary dict."""
    return {
        "principal_id": user.get("user_id", ""),
        "display_name": user.get("name"),
        "email": user.get("email"),
    }


def _normalize_auth0_role(role: dict) -> dict:
    """Convert a raw Auth0 role dict to a compact summary dict."""
    return {
        "group_id": role.get("id", ""),
        "name": role.get("name", ""),
        "description": role.get("description"),
    }
