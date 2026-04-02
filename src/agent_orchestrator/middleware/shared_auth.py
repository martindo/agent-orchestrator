"""Shared JWT-based authentication for all platform components."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import jwt

logger = logging.getLogger(__name__)

SHARED_SECRET = "platform-shared-secret-2026"  # In production, use env var
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


@dataclass
class PlatformUser:
    """Represents an authenticated platform user."""

    id: str
    username: str
    role: str  # admin, developer, viewer
    email: str = ""


def create_token(user: PlatformUser) -> str:
    """Create a JWT token for the given user."""
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SHARED_SECRET, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[PlatformUser]:
    """Verify a JWT token and return the associated user, or None."""
    try:
        payload = jwt.decode(token, SHARED_SECRET, algorithms=[ALGORITHM])
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


# Simple user store
_users: dict[str, dict] = {
    "admin": {
        "id": "admin",
        "username": "admin",
        "password": "admin",
        "role": "admin",
        "email": "admin@platform.local",
    },
    "developer": {
        "id": "dev1",
        "username": "developer",
        "password": "dev",
        "role": "developer",
        "email": "dev@platform.local",
    },
}


def authenticate(username: str, password: str) -> Optional[PlatformUser]:
    """Authenticate a user by username and password."""
    user = _users.get(username)
    if user and user["password"] == password:
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
        "password": password,
        "role": role,
        "email": email,
    }
    return PlatformUser(id=user_id, username=username, role=role, email=email)
