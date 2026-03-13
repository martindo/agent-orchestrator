"""Generic HTTP external API connector provider.

Connects to any REST API via configurable base URL and auth.
Supports api_key, bearer, basic, and no-auth modes.
"""
from __future__ import annotations

import json
import logging

import httpx

from ...models import ConnectorCostInfo
from ._base import BaseExternalApiProvider, ExternalApiProviderError

logger = logging.getLogger(__name__)

_SUPPORTED_AUTH_TYPES = ("none", "api_key", "bearer", "basic")


class GenericHttpProvider(BaseExternalApiProvider):
    """Configurable HTTP connector that can target any REST API.

    Auth modes:
    - none: No authentication headers added
    - api_key: Adds X-API-Key header (or custom header via api_key_header)
    - bearer: Adds Authorization: Bearer {token}
    - basic: HTTP Basic auth with username:password

    Example::

        provider = GenericHttpProvider(
            base_url="https://api.example.com",
            auth_type="bearer",
            bearer_token="my-token",
        )
    """

    def __init__(
        self,
        base_url: str,
        auth_type: str = "none",
        api_key: str = "",
        api_key_header: str = "X-API-Key",
        bearer_token: str = "",
        username: str = "",
        password: str = "",
        extra_headers: dict | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not base_url:
            raise ValueError("GenericHttpProvider requires a non-empty base_url")
        if auth_type not in _SUPPORTED_AUTH_TYPES:
            raise ValueError(f"auth_type must be one of {_SUPPORTED_AUTH_TYPES}")
        self._base_url = base_url.rstrip("/")
        self._auth_type = auth_type
        self._api_key_value = api_key
        self._api_key_header = api_key_header
        self._bearer_token = bearer_token
        self._username = username
        self._password = password
        self._extra_headers = extra_headers or {}
        self._timeout = timeout_seconds

    @classmethod
    def from_env(cls) -> "GenericHttpProvider | None":
        """Create an instance from environment variables.

        Required: EXTERNAL_API_BASE_URL
        Optional:
          EXTERNAL_API_AUTH_TYPE (default: none)
          EXTERNAL_API_API_KEY
          EXTERNAL_API_API_KEY_HEADER (default: X-API-Key)
          EXTERNAL_API_BEARER_TOKEN
          EXTERNAL_API_USERNAME
          EXTERNAL_API_PASSWORD
          EXTERNAL_API_HEADERS (JSON string of extra headers)
          EXTERNAL_API_TIMEOUT (seconds, default: 30)
        """
        import os
        base_url = os.environ.get("EXTERNAL_API_BASE_URL", "")
        if not base_url:
            return None
        auth_type = os.environ.get("EXTERNAL_API_AUTH_TYPE", "none")
        extra_headers: dict = {}
        raw_headers = os.environ.get("EXTERNAL_API_HEADERS", "")
        if raw_headers:
            try:
                extra_headers = json.loads(raw_headers)
            except (json.JSONDecodeError, ValueError):
                logger.warning("EXTERNAL_API_HEADERS is not valid JSON — ignoring")
        timeout_str = os.environ.get("EXTERNAL_API_TIMEOUT", "30")
        try:
            timeout = float(timeout_str)
        except ValueError:
            timeout = 30.0
        return cls(
            base_url=base_url,
            auth_type=auth_type,
            api_key=os.environ.get("EXTERNAL_API_API_KEY", ""),
            api_key_header=os.environ.get("EXTERNAL_API_API_KEY_HEADER", "X-API-Key"),
            bearer_token=os.environ.get("EXTERNAL_API_BEARER_TOKEN", ""),
            username=os.environ.get("EXTERNAL_API_USERNAME", ""),
            password=os.environ.get("EXTERNAL_API_PASSWORD", ""),
            extra_headers=extra_headers,
            timeout_seconds=timeout,
        )

    @property
    def provider_id(self) -> str:
        return "external_api.generic_http"

    @property
    def display_name(self) -> str:
        return "Generic HTTP API"

    def _build_headers(self, extra: dict | None = None) -> dict:
        """Build request headers combining auth + extra_headers + per-request headers."""
        headers: dict = {}
        if self._auth_type == "api_key" and self._api_key_value:
            headers[self._api_key_header] = self._api_key_value
        elif self._auth_type == "bearer" and self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        headers.update(self._extra_headers)
        if extra:
            headers.update(extra)
        return headers

    def _build_auth(self) -> httpx.BasicAuth | None:
        if self._auth_type == "basic" and self._username:
            return httpx.BasicAuth(self._username, self._password)
        return None

    async def _make_request(
        self,
        method: str,
        path: str,
        body: dict | None,
        headers: dict | None,
        params: dict | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Execute an HTTP request and return a response artifact.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            path: URL path relative to base_url (must start with /).
            body: Request body dict (JSON-serialized).
            headers: Per-request headers merged over defaults.
            params: URL query parameters.

        Returns:
            Tuple of (response artifact dict, None — no tracked API cost).

        Raises:
            ExternalApiProviderError: On HTTP or network errors.
        """
        url = f"{self._base_url}{path if path.startswith('/') else '/' + path}"
        request_headers = self._build_headers(headers)
        auth = self._build_auth()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method=method.upper(),
                    url=url,
                    json=body if body else None,
                    params=params,
                    headers=request_headers,
                    auth=auth,
                )
        except httpx.HTTPError as exc:
            raise ExternalApiProviderError(f"HTTP error calling {method} {url}: {exc}") from exc

        # Parse response body — try JSON first, fall back to text
        try:
            response_body: dict | str = response.json()
        except (ValueError, httpx.DecodingError):
            response_body = response.text

        response_headers_dict = dict(response.headers)

        logger.info(
            "External API: method=%s url=%s status=%d",
            method.upper(), url, response.status_code,
        )

        artifact = self._make_response_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            method=method.upper(),
            path=path,
            status_code=response.status_code,
            response_body=response_body,
            response_headers=response_headers_dict,
            raw_payload={
                "method": method.upper(),
                "url": url,
                "status_code": response.status_code,
                "response": response_body,
                "response_headers": response_headers_dict,
            },
            provenance={"base_url": self._base_url, "auth_type": self._auth_type},
        )
        return artifact.model_dump(mode="json"), None
