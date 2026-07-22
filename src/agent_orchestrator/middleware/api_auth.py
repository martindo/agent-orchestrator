"""Configurable API authentication enforcement.

Enforcement is **opt-in with secure defaults**, mirroring the platform's
deployment modes rather than being forced on every user:

* Resolution order for "is auth enabled":
  1. ``AGENT_ORCH_AUTH_ENABLED`` env var (explicit ``true``/``false``) — wins.
  2. Otherwise derived from the deployment mode: ``enterprise`` → on,
     ``lite``/``standard`` → off. (A single-user LITE profile is not forced
     into auth; an ENTERPRISE deployment is secured by default.)

When enabled, every request must carry ``Authorization: Bearer <jwt>`` except
for an allowlist (login/register, health, and the API docs). Requests without a
valid token get 401. When enabled, the app also refuses to run on the built-in
development JWT secret — set ``AGENT_ORCH_JWT_SECRET`` to a real secret.

WebSocket handshakes are not covered by this HTTP middleware yet; that is
tracked separately in the audit backlog.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_orchestrator.exceptions import ConfigurationError
from agent_orchestrator.middleware.shared_auth import (
    PlatformUser,
    is_secret_secure,
    verify_token,
)

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

# Path suffixes that never require auth even when enforcement is on. Compared
# against the request path so the API_PREFIX does not need to be hardcoded.
_ALLOWLIST_SUFFIXES = (
    "/auth/login",
    "/auth/register",
    "/auth/verify",
    "/health",
    "/healthz",
)
_ALLOWLIST_EXACT = {"/", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}


@dataclass(frozen=True)
class AuthSettings:
    """Resolved authentication policy for an app instance."""

    enabled: bool
    deployment_mode: str = "lite"


def _env_bool(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    logger.warning("Ignoring non-boolean value for %s: %r", name, raw)
    return None


def resolve_auth_settings(
    deployment_mode: str | None = None,
    *,
    enabled: bool | None = None,
) -> AuthSettings:
    """Resolve the effective auth policy.

    Args:
        deployment_mode: Deployment mode string ("lite"/"standard"/"enterprise").
        enabled: Explicit override; when None, resolved from env then mode.
    """
    mode = (deployment_mode or "lite").lower()

    if enabled is None:
        enabled = _env_bool("AGENT_ORCH_AUTH_ENABLED")
    if enabled is None:
        enabled = mode == "enterprise"

    if enabled and not is_secret_secure():
        raise ConfigurationError(
            "API authentication is enabled but AGENT_ORCH_JWT_SECRET is unset "
            "or still the built-in development secret. Set a strong secret "
            "before enabling auth — refusing to start on a forgeable secret.",
        )

    return AuthSettings(enabled=enabled, deployment_mode=mode)


def auth_is_enabled() -> bool:
    """Lightweight check used by peripheral modules (e.g. default-user seeding).

    Does not raise on an insecure secret; it only reports intent.
    """
    explicit = _env_bool("AGENT_ORCH_AUTH_ENABLED")
    if explicit is not None:
        return explicit
    return os.environ.get("AGENT_ORCH_DEPLOYMENT_MODE", "lite").lower() == "enterprise"


def _is_allowlisted(path: str) -> bool:
    if path in _ALLOWLIST_EXACT:
        return True
    return any(path.endswith(suffix) for suffix in _ALLOWLIST_SUFFIXES)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated requests when auth enforcement is enabled."""

    def __init__(self, app, settings: AuthSettings) -> None:  # noqa: ANN001
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        if not self._settings.enabled or _is_allowlisted(request.url.path):
            return await call_next(request)

        token = _bearer_token(request)
        user = verify_token(token) if token else None
        if user is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        request.state.user = user
        return await call_next(request)


def get_current_user(request: Request) -> PlatformUser | None:
    """FastAPI dependency: the authenticated user, or None when auth is off."""
    return getattr(request.state, "user", None)
