"""Authentication routes for unified platform auth."""

from __future__ import annotations

from fastapi import APIRouter

from ..middleware.shared_auth import authenticate, create_token, register_user, verify_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(body: dict) -> dict:
    """Authenticate a user and return a JWT token."""
    username = body.get("username", "")
    password = body.get("password", "")
    user = authenticate(username, password)
    if not user:
        return {"success": False, "error": "Invalid credentials"}
    token = create_token(user)
    return {"success": True, "token": token, "user": user.__dict__}


@router.post("/register")
async def register(body: dict) -> dict:
    """Register a new user and return a JWT token."""
    user = register_user(
        username=body.get("username", ""),
        password=body.get("password", ""),
        role=body.get("role", "developer"),
        email=body.get("email", ""),
    )
    token = create_token(user)
    return {"success": True, "token": token, "user": user.__dict__}


@router.post("/verify")
async def verify(body: dict) -> dict:
    """Verify a JWT token and return the associated user."""
    token = body.get("token", "")
    user = verify_token(token)
    if not user:
        return {"success": False, "error": "Invalid or expired token"}
    return {"success": True, "user": user.__dict__}


@router.get("/me")
async def get_current_user() -> dict:
    """Get the current user. In production, extract from request header."""
    return {"user": {"id": "anonymous", "username": "anonymous", "role": "developer"}}
