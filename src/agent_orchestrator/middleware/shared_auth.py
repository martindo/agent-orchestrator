"""Shared JWT-based authentication for all platform components.

Secrets and default users are resolved at call time from the environment so
that a deployment can be secured without code changes:

* ``AGENT_ORCH_JWT_SECRET`` — HMAC signing secret. If unset, a well-known
  development default is used and :func:`is_secret_secure` returns ``False``.
  Enforced auth refuses to run on the default secret (see ``api_auth``).
* ``AGENT_ORCH_SEED_DEFAULT_USERS`` — when ``true`` (or when auth is disabled
  for local development), the ``admin``/``developer`` convenience accounts are
  seeded. In a secured deployment they are **not** created; provision users
  explicitly via :func:`register_user`.

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes, never plaintext.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

logger = logging.getLogger(__name__)

# Well-known development default. NEVER relied upon when auth is enforced —
# is_secret_secure() reports False and the API refuses to start on it.
_DEFAULT_SECRET = "platform-shared-secret-2026"
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24

_PBKDF2_ROUNDS = 240_000


def get_secret() -> str:
    """Resolve the JWT signing secret from the environment (or the dev default)."""
    return os.environ.get("AGENT_ORCH_JWT_SECRET") or _DEFAULT_SECRET


def is_secret_secure() -> bool:
    """True if a non-default signing secret has been configured."""
    secret = os.environ.get("AGENT_ORCH_JWT_SECRET")
    return bool(secret) and secret != _DEFAULT_SECRET


@dataclass
class PlatformUser:
    """Represents an authenticated platform user."""

    id: str
    username: str
    role: str  # admin, developer, viewer
    email: str = ""


def create_token(user: PlatformUser) -> str:
    """Create a JWT token for the given user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "exp": now + timedelta(hours=TOKEN_EXPIRY_HOURS),
        "iat": now,
    }
    return jwt.encode(payload, get_secret(), algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[PlatformUser]:
    """Verify a JWT token and return the associated user, or None."""
    try:
        payload = jwt.decode(token, get_secret(), algorithms=[ALGORITHM])
        return PlatformUser(
            id=payload["sub"],
            username=payload["username"],
            role=payload["role"],
            email=payload.get("email", ""),
        )
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Invalid token")
        return None


# ---- Password hashing (salted PBKDF2, stdlib only) ----


def hash_password(password: str, salt: str | None = None) -> str:
    """Return a ``salt$hash`` string for the given password."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS,
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against a stored ``salt$hash``."""
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


# ---- In-memory user store ----

_users: dict[str, dict] = {}


def _should_seed_defaults() -> bool:
    """Seed convenience accounts only when explicitly allowed or auth is off."""
    flag = os.environ.get("AGENT_ORCH_SEED_DEFAULT_USERS")
    if flag is not None:
        return flag.strip().lower() in {"1", "true", "yes", "on"}
    # No explicit flag: seed only when auth is not enforced (local dev). Imported
    # lazily to avoid a circular import with the api_auth resolver.
    from agent_orchestrator.middleware.api_auth import auth_is_enabled

    return not auth_is_enabled()


def _seed_default_users() -> None:
    """Populate the dev-only admin/developer accounts (hashed passwords)."""
    _users.update(
        {
            "admin": {
                "id": "admin",
                "username": "admin",
                "password_hash": hash_password("admin"),
                "role": "admin",
                "email": "admin@platform.local",
            },
            "developer": {
                "id": "dev1",
                "username": "developer",
                "password_hash": hash_password("dev"),
                "role": "developer",
                "email": "dev@platform.local",
            },
        }
    )
    logger.warning(
        "Seeded default admin/developer accounts — DEV ONLY. Do not use in a "
        "secured deployment (set AGENT_ORCH_SEED_DEFAULT_USERS=false).",
    )


def authenticate(username: str, password: str) -> Optional[PlatformUser]:
    """Authenticate a user by username and password."""
    if not _users and _should_seed_defaults():
        _seed_default_users()
    user = _users.get(username)
    if user and verify_password(password, user["password_hash"]):
        return PlatformUser(
            id=user["id"],
            username=user["username"],
            role=user["role"],
            email=user["email"],
        )
    return None


def register_user(
    username: str,
    password: str,
    role: str = "developer",
    email: str = "",
) -> PlatformUser:
    """Register a new user in the platform."""
    user_id = f"user-{len(_users) + 1}"
    _users[username] = {
        "id": user_id,
        "username": username,
        "password_hash": hash_password(password),
        "role": role,
        "email": email,
    }
    return PlatformUser(id=user_id, username=username, role=role, email=email)
