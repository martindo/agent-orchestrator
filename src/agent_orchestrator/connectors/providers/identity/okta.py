"""Okta identity connector provider.

Implements get_user, list_users, check_permission, and list_groups against
the Okta API v1. Authenticates using an SSWS API token.
"""
from __future__ import annotations

import logging

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import BaseIdentityProvider, IdentityProviderError

logger = logging.getLogger(__name__)


class OktaIdentityProvider(BaseIdentityProvider):
    """Okta-backed identity connector provider.

    Authenticates via an SSWS API token sent in the Authorization header.

    Example::

        provider = OktaIdentityProvider(
            domain="myorg.okta.com",
            api_token="00abc123...",
        )
    """

    def __init__(
        self,
        domain: str,
        api_token: str,
    ) -> None:
        if not domain:
            raise ValueError("OktaIdentityProvider requires a non-empty domain")
        if not api_token:
            raise ValueError("OktaIdentityProvider requires a non-empty api_token")
        self._base_url = f"https://{domain.rstrip('/')}"
        self._api_token = api_token

    @classmethod
    def from_env(cls) -> "OktaIdentityProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``OKTA_DOMAIN``, ``OKTA_API_TOKEN``

        Returns None if any required env var is missing.
        """
        import os

        domain = os.environ.get("OKTA_DOMAIN", "")
        api_token = os.environ.get("OKTA_API_TOKEN", "")
        if not domain or not api_token:
            return None
        return cls(domain=domain, api_token=api_token)

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "identity.okta"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Okta Identity"

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the Okta API."""
        return {
            "Authorization": f"SSWS {self._api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _get_user(
        self,
        user_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve an Okta user profile and their group memberships.

        Args:
            user_id: Okta user ID or login (email).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        headers = self._auth_headers()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                user_resp = await client.get(
                    f"{self._base_url}/api/v1/users/{user_id}",
                    headers=headers,
                )
                user_resp.raise_for_status()
                user_data: dict = user_resp.json()

                groups_resp = await client.get(
                    f"{self._base_url}/api/v1/users/{user_id}/groups",
                    headers=headers,
                )
                groups_resp.raise_for_status()
                groups_data: list[dict] = groups_resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise IdentityProviderError(
                    f"Okta user not found: {user_id}"
                ) from exc
            raise IdentityProviderError(f"Okta HTTP error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Okta HTTP error: {exc}") from exc

        groups = [
            g.get("profile", {}).get("name", "") for g in groups_data
            if g.get("profile", {}).get("name")
        ]
        profile = user_data.get("profile", {})

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="okta_user",
                external_id=user_data.get("id", user_id),
                url=None,
                metadata={"base_url": self._base_url},
            )
        ]

        artifact = self._make_user_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            principal_id=user_data.get("id", user_id),
            display_name=f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or None,
            email=profile.get("email") or profile.get("login"),
            roles=[],
            groups=groups,
            raw_payload=user_data,
            provenance={"provider": "okta", "base_url": self._base_url},
            references=refs,
        )

        logger.info("Okta get_user: user_id=%r", user_id)
        return artifact.model_dump(mode="json"), None

    async def _list_users(
        self,
        query: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List or search users in the Okta directory.

        Args:
            query: Optional search expression for the ``search`` parameter.
            limit: Maximum number of results to return (default 25).

        Returns:
            Tuple of (ExternalArtifact dict with resource_type "users",
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        headers = self._auth_headers()
        params: dict = {"limit": limit}
        if query:
            params["search"] = query

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/users",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                users: list[dict] = response.json()
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Okta HTTP error: {exc}") from exc

        items = [_normalize_okta_user(u) for u in users]
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="users",
            items=items,
            raw_payload={"query": query, "total": len(users), "items": items},
            provenance={"provider": "okta", "base_url": self._base_url},
        )

        logger.info("Okta list_users: query=%r count=%d", query, len(users))
        return artifact.model_dump(mode="json"), None

    async def _check_permission(
        self,
        user_id: str,
        permission: str,
        resource: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Check whether an Okta user belongs to a group matching a permission name.

        Okta does not expose a direct permission model outside of app role
        assignments. This implementation checks whether any of the user's
        group names or profile fields match the requested permission string.

        Args:
            user_id: Okta user ID or login.
            permission: Group name or role to check membership for.
            resource: Optional resource scope hint (not used in Okta check).

        Returns:
            Tuple of (ExternalArtifact dict with metadata has_permission,
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        headers = self._auth_headers()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                user_resp = await client.get(
                    f"{self._base_url}/api/v1/users/{user_id}",
                    headers=headers,
                )
                user_resp.raise_for_status()
                user_data: dict = user_resp.json()

                groups_resp = await client.get(
                    f"{self._base_url}/api/v1/users/{user_id}/groups",
                    headers=headers,
                )
                groups_resp.raise_for_status()
                groups_data: list[dict] = groups_resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise IdentityProviderError(
                    f"Okta user not found: {user_id}"
                ) from exc
            raise IdentityProviderError(f"Okta HTTP error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Okta HTTP error: {exc}") from exc

        group_names = [
            g.get("profile", {}).get("name", "") for g in groups_data
        ]
        has_permission = permission in group_names or any(
            permission.lower() in name.lower() for name in group_names if name
        )
        profile = user_data.get("profile", {})

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="okta_user",
                external_id=user_data.get("id", user_id),
                url=None,
                metadata={
                    "base_url": self._base_url,
                    "permission_checked": permission,
                },
            )
        ]

        artifact = self._make_user_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            principal_id=user_data.get("id", user_id),
            display_name=f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or None,
            email=profile.get("email") or profile.get("login"),
            roles=[],
            groups=[n for n in group_names if n],
            raw_payload={
                "user": user_data,
                "groups": groups_data,
                "has_permission": has_permission,
                "permission_checked": permission,
            },
            provenance={"provider": "okta", "base_url": self._base_url},
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
            "Okta check_permission: user_id=%r permission=%r result=%s",
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
        """List groups defined in the Okta directory.

        Args:
            query: Optional name prefix filter (``q`` parameter).
            limit: Maximum number of results to return (default 25).

        Returns:
            Tuple of (ExternalArtifact dict with resource_type "groups",
            None — no tracked API cost).

        Raises:
            IdentityProviderError: On HTTP or API errors.
        """
        headers = self._auth_headers()
        params: dict = {"limit": limit}
        if query:
            params["q"] = query

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/groups",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                groups: list[dict] = response.json()
        except httpx.HTTPError as exc:
            raise IdentityProviderError(f"Okta HTTP error: {exc}") from exc

        items = [_normalize_okta_group(g) for g in groups]
        artifact = self._make_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            resource_type="groups",
            items=items,
            raw_payload={"query": query, "total": len(groups), "items": items},
            provenance={"provider": "okta", "base_url": self._base_url},
        )

        logger.info("Okta list_groups: query=%r count=%d", query, len(groups))
        return artifact.model_dump(mode="json"), None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _normalize_okta_user(user: dict) -> dict:
    """Convert a raw Okta user dict to a compact summary dict."""
    profile = user.get("profile", {})
    first = profile.get("firstName", "")
    last = profile.get("lastName", "")
    display_name = f"{first} {last}".strip() or None
    return {
        "principal_id": user.get("id", ""),
        "display_name": display_name,
        "email": profile.get("email") or profile.get("login"),
        "status": user.get("status"),
    }


def _normalize_okta_group(group: dict) -> dict:
    """Convert a raw Okta group dict to a compact summary dict."""
    profile = group.get("profile", {})
    return {
        "group_id": group.get("id", ""),
        "name": profile.get("name", ""),
        "description": profile.get("description"),
        "type": group.get("type"),
    }
