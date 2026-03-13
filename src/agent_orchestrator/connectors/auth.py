"""Connector authentication abstraction.

Provides auth type declarations and credential reference configuration.
The platform core never stores or logs actual credentials.
Providers resolve credentials from environment variables or external secret stores.
"""
from __future__ import annotations
import logging
from enum import Enum
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuthType(str, Enum):
    """Authentication mechanism types for connector providers."""
    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    OAUTH2 = "oauth2"
    BASIC = "basic"
    CUSTOM = "custom"


class ConnectorAuthConfig(BaseModel, frozen=True):
    """Connector authentication configuration.

    Stores credential REFERENCES (e.g. environment variable names),
    never actual credential values. Providers resolve credentials at runtime.
    """
    auth_type: AuthType = AuthType.NONE
    credential_env_var: str | None = None    # env var name holding the credential
    token_endpoint: str | None = None        # OAuth2 token URL
    scopes: list[str] = Field(default_factory=list)
    credential_header: str = "Authorization" # header name for token/key injection
    metadata: dict = Field(default_factory=dict)


class ConnectorSessionContext(BaseModel, frozen=True):
    """Runtime session context passed to providers via invocation request context.

    Contains auth configuration metadata ONLY — no raw credentials.
    Providers use credential_env_var to look up secrets from environment.
    This model MUST NOT be logged in full (use summary fields only).
    """
    auth_type: AuthType = AuthType.NONE
    credential_env_var: str | None = None
    credential_header: str = "Authorization"
    scopes: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    def to_log_summary(self) -> dict:
        """Return a safe summary suitable for logging — no credentials."""
        return {
            "auth_type": self.auth_type.value,
            "has_credential_env_var": self.credential_env_var is not None,
            "scopes": self.scopes,
        }


def build_session_context(auth_config: ConnectorAuthConfig | None) -> ConnectorSessionContext | None:
    """Build a runtime session context from an auth config.

    Returns None if auth_config is None or auth_type is NONE.

    Args:
        auth_config: The connector's authentication configuration.

    Returns:
        ConnectorSessionContext suitable for passing in request context.
    """
    if auth_config is None or auth_config.auth_type == AuthType.NONE:
        return None
    return ConnectorSessionContext(
        auth_type=auth_config.auth_type,
        credential_env_var=auth_config.credential_env_var,
        credential_header=auth_config.credential_header,
        scopes=auth_config.scopes,
        metadata=auth_config.metadata,
    )
