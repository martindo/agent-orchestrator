"""Tests for configurable API authentication enforcement."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_orchestrator.api.app import create_app
from agent_orchestrator.exceptions import ConfigurationError
from agent_orchestrator.middleware import shared_auth
from agent_orchestrator.middleware.api_auth import resolve_auth_settings
from agent_orchestrator.middleware.shared_auth import (
    PlatformUser,
    create_token,
    hash_password,
    is_secret_secure,
    verify_password,
)

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate auth env + in-memory user store between tests."""
    for var in (
        "AGENT_ORCH_AUTH_ENABLED",
        "AGENT_ORCH_JWT_SECRET",
        "AGENT_ORCH_DEPLOYMENT_MODE",
        "AGENT_ORCH_SEED_DEFAULT_USERS",
    ):
        monkeypatch.delenv(var, raising=False)
    shared_auth._users.clear()
    yield
    shared_auth._users.clear()


# ---- Password hashing -------------------------------------------------------


def test_password_hash_roundtrip():
    stored = hash_password("s3cret")
    assert "$" in stored
    assert "s3cret" not in stored  # never plaintext
    assert verify_password("s3cret", stored) is True
    assert verify_password("wrong", stored) is False


def test_password_hash_salted():
    assert hash_password("x") != hash_password("x")  # random salt


# ---- Secret resolution ------------------------------------------------------


def test_default_secret_is_insecure():
    assert is_secret_secure() is False


def test_env_secret_is_secure(monkeypatch):
    monkeypatch.setenv("AGENT_ORCH_JWT_SECRET", "a-real-strong-secret")
    assert is_secret_secure() is True


# ---- Policy resolution ------------------------------------------------------


def test_lite_mode_defaults_off():
    assert resolve_auth_settings("lite").enabled is False


def test_enterprise_defaults_on_but_requires_secret():
    with pytest.raises(ConfigurationError):
        resolve_auth_settings("enterprise")  # no secure secret set


def test_enterprise_with_secret_enables(monkeypatch):
    monkeypatch.setenv("AGENT_ORCH_JWT_SECRET", "strong")
    assert resolve_auth_settings("enterprise").enabled is True


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("AGENT_ORCH_AUTH_ENABLED", "false")
    # Enterprise would default on, but explicit env override forces off.
    assert resolve_auth_settings("enterprise").enabled is False


def test_enable_without_secret_refuses(monkeypatch):
    with pytest.raises(ConfigurationError):
        resolve_auth_settings("lite", enabled=True)


# ---- Enforcement (disabled) -------------------------------------------------


def test_disabled_allows_unauthenticated():
    client = TestClient(create_app())  # lite, no env → disabled
    # Health is always open; a protected route must also be reachable when off.
    assert client.get(f"{API}/health").status_code != 401
    assert client.get(f"{API}/agents").status_code != 401


# ---- Enforcement (enabled) --------------------------------------------------


def _enabled_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AGENT_ORCH_JWT_SECRET", "unit-test-secret-that-is-long-enough-32b")
    return TestClient(create_app(auth_enabled=True))


def test_enabled_rejects_missing_token(monkeypatch):
    client = _enabled_client(monkeypatch)
    resp = client.get(f"{API}/agents")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_enabled_allows_valid_token(monkeypatch):
    client = _enabled_client(monkeypatch)
    token = create_token(PlatformUser(id="u1", username="u1", role="admin"))
    resp = client.get(f"{API}/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code != 401  # passed the auth gate


def test_enabled_rejects_garbage_token(monkeypatch):
    client = _enabled_client(monkeypatch)
    resp = client.get(f"{API}/agents", headers={"Authorization": "Bearer nonsense"})
    assert resp.status_code == 401


def test_enabled_allowlists_login_and_health(monkeypatch):
    client = _enabled_client(monkeypatch)
    assert client.get(f"{API}/health").status_code != 401
    # login is reachable without a token so users can obtain one
    assert client.post(f"{API}/auth/login", json={"username": "x", "password": "y"}).status_code != 401


# ---- Default-user seeding ---------------------------------------------------


def test_defaults_seeded_when_disabled():
    # auth off → convenience accounts available for local dev
    assert shared_auth.authenticate("admin", "admin") is not None


def test_defaults_not_seeded_when_enabled(monkeypatch):
    monkeypatch.setenv("AGENT_ORCH_AUTH_ENABLED", "true")
    monkeypatch.setenv("AGENT_ORCH_JWT_SECRET", "strong")
    assert shared_auth.authenticate("admin", "admin") is None


# ---- /auth/me ---------------------------------------------------------------


def test_me_anonymous_when_disabled():
    client = TestClient(create_app())
    body = client.get(f"{API}/auth/me").json()
    assert body["authenticated"] is False
    assert body["user"] is None


def test_me_returns_user_when_authenticated(monkeypatch):
    client = _enabled_client(monkeypatch)
    token = create_token(PlatformUser(id="u1", username="alice", role="admin"))
    body = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["authenticated"] is True
    assert body["user"]["username"] == "alice"
