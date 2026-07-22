"""Authentication routes for unified platform auth."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..middleware.api_auth import get_current_user
from ..middleware.shared_auth import authenticate, create_token, register_user, verify_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role: str = "developer"
    email: str = ""


class VerifyRequest(BaseModel):
    token: str = Field(..., min_length=1)


@router.post("/login")
async def login(body: LoginRequest) -> dict:
    """Authenticate a user and return a JWT token."""
    user = authenticate(body.username, body.password)
    if not user:
        return {"success": False, "error": "Invalid credentials"}
    token = create_token(user)
    return {"success": True, "token": token, "user": user.__dict__}


@router.post("/register")
async def register(body: RegisterRequest) -> dict:
    """Register a new user and return a JWT token."""
    user = register_user(
        username=body.username,
        password=body.password,
        role=body.role,
        email=body.email,
    )
    token = create_token(user)
    return {"success": True, "token": token, "user": user.__dict__}


@router.post("/verify")
async def verify(body: VerifyRequest) -> dict:
    """Verify a JWT token and return the associated user."""
    user = verify_token(body.token)
    if not user:
        return {"success": False, "error": "Invalid or expired token"}
    return {"success": True, "user": user.__dict__}


@router.get("/me")
async def get_current_user_route(request: Request) -> dict:
    """Return the authenticated user.

    When auth enforcement is enabled the middleware has already attached the
    verified user to ``request.state``. When it is disabled there is no
    authenticated principal, so this reports an anonymous session rather than
    inventing a fake identity.
    """
    user = get_current_user(request)
    if user is None:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user.__dict__}
