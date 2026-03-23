"""Tests for catalog REST API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agent_orchestrator.api.catalog_routes import catalog_router
from agent_orchestrator.catalog.models import (
    CapabilityRegistration,
    InvocationMode,
)
from agent_orchestrator.catalog.registry import TeamRegistry
from agent_orchestrator.contracts.models import LifecycleState
from agent_orchestrator.core.event_bus import EventBus


def _make_app(registry: TeamRegistry | None = None, engine: object | None = None) -> TestClient:
    """Create a test FastAPI app with catalog routes."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(catalog_router, prefix="/api/v1")

    if engine is not None:
        app.state.engine = engine
    elif registry is not None:
        mock_engine = MagicMock()
        mock_engine.team_registry = registry
        mock_engine.event_bus = EventBus()
        mock_engine.active_profile = None
        app.state.engine = mock_engine
    else:
        app.state.engine = None

    return TestClient(app)


def _make_reg(
    capability_id: str = "test.v1",
    *,
    profile_name: str = "test-profile",
    tags: list[str] | None = None,
    status: LifecycleState = LifecycleState.ACTIVE,
) -> CapabilityRegistration:
    now = datetime.now(timezone.utc)
    return CapabilityRegistration(
        capability_id=capability_id,
        display_name=capability_id,
        profile_name=profile_name,
        tags=tags or [],
        status=status,
        registered_at=now,
        updated_at=now,
    )


class TestListCapabilities:
    """Test GET /catalog/capabilities."""

    def test_list_empty(self) -> None:
        client = _make_app(TeamRegistry())
        resp = client.get("/api/v1/catalog/capabilities")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_all(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("a.v1"))
        registry.register(_make_reg("b.v1"))
        client = _make_app(registry)
        resp = client.get("/api/v1/catalog/capabilities")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_filter_by_tags(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("a.v1", tags=["ml"]))
        registry.register(_make_reg("b.v1", tags=["web"]))
        client = _make_app(registry)
        resp = client.get("/api/v1/catalog/capabilities", params={"tags": "ml"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["capability_id"] == "a.v1"

    def test_filter_by_status(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("a.v1", status=LifecycleState.ACTIVE))
        registry.register(_make_reg("b.v1", status=LifecycleState.DRAFT))
        client = _make_app(registry)
        resp = client.get("/api/v1/catalog/capabilities", params={"status": "draft"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_no_engine_returns_503(self) -> None:
        client = _make_app()
        resp = client.get("/api/v1/catalog/capabilities")
        assert resp.status_code == 503


class TestGetCapability:
    """Test GET /catalog/capabilities/{id}."""

    def test_get_existing(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("cap.v1"))
        client = _make_app(registry)
        resp = client.get("/api/v1/catalog/capabilities/cap.v1")
        assert resp.status_code == 200
        assert resp.json()["capability_id"] == "cap.v1"

    def test_get_not_found(self) -> None:
        client = _make_app(TeamRegistry())
        resp = client.get("/api/v1/catalog/capabilities/missing")
        assert resp.status_code == 404


class TestRegisterCapability:
    """Test POST /catalog/capabilities."""

    def test_register(self) -> None:
        registry = TeamRegistry()
        client = _make_app(registry)
        resp = client.post("/api/v1/catalog/capabilities", json={
            "capability_id": "new.v1",
            "display_name": "New Capability",
            "profile_name": "my-profile",
            "status": "active",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["capability_id"] == "new.v1"
        assert data["status"] == "active"
        assert registry.get("new.v1") is not None

    def test_register_invalid_status(self) -> None:
        client = _make_app(TeamRegistry())
        resp = client.post("/api/v1/catalog/capabilities", json={
            "capability_id": "bad.v1",
            "display_name": "Bad",
            "profile_name": "test",
            "status": "invalid_status",
        })
        assert resp.status_code == 400


class TestUpdateCapability:
    """Test PUT /catalog/capabilities/{id}."""

    def test_update(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("cap.v1"))
        client = _make_app(registry)
        resp = client.put("/api/v1/catalog/capabilities/cap.v1", json={
            "display_name": "Updated Name",
            "status": "deprecated",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Updated Name"
        assert data["status"] == "deprecated"

    def test_update_not_found(self) -> None:
        client = _make_app(TeamRegistry())
        resp = client.put("/api/v1/catalog/capabilities/missing", json={
            "display_name": "X",
        })
        assert resp.status_code == 404


class TestUnregisterCapability:
    """Test DELETE /catalog/capabilities/{id}."""

    def test_delete(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("cap.v1"))
        client = _make_app(registry)
        resp = client.delete("/api/v1/catalog/capabilities/cap.v1")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert registry.get("cap.v1") is None

    def test_delete_not_found(self) -> None:
        client = _make_app(TeamRegistry())
        resp = client.delete("/api/v1/catalog/capabilities/missing")
        assert resp.status_code == 404


class TestCatalogSummary:
    """Test GET /catalog/summary."""

    def test_summary(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("a.v1", status=LifecycleState.ACTIVE))
        registry.register(_make_reg("b.v1", status=LifecycleState.DRAFT))
        client = _make_app(registry)
        resp = client.get("/api/v1/catalog/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["by_status"]["active"] == 1
        assert data["by_status"]["draft"] == 1


class TestInvokeCapability:
    """Test POST /catalog/capabilities/{id}/invoke."""

    def test_invoke_no_engine(self) -> None:
        client = _make_app()
        resp = client.post("/api/v1/catalog/capabilities/cap.v1/invoke", json={})
        assert resp.status_code == 503

    def test_invoke_not_found(self) -> None:
        client = _make_app(TeamRegistry())
        resp = client.post("/api/v1/catalog/capabilities/missing/invoke", json={})
        assert resp.status_code == 404

    def test_invoke_success(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("cap.v1"))

        mock_engine = MagicMock()
        mock_engine.team_registry = registry
        mock_engine.event_bus = EventBus()
        mock_engine.active_profile = None
        mock_engine.submit_work = AsyncMock()

        client = _make_app(engine=mock_engine)
        resp = client.post("/api/v1/catalog/capabilities/cap.v1/invoke", json={
            "input": {"query": "test"},
            "title": "Test invocation",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["capability_id"] == "cap.v1"
        assert data["status"] == "submitted"
        assert "work_id" in data
        mock_engine.submit_work.assert_called_once()


class TestLifecycleTransitions:
    """Test capability lifecycle: DRAFT → ACTIVE → DEPRECATED."""

    def test_lifecycle(self) -> None:
        registry = TeamRegistry()
        client = _make_app(registry)

        # Register as DRAFT
        resp = client.post("/api/v1/catalog/capabilities", json={
            "capability_id": "lifecycle.v1",
            "display_name": "Lifecycle Test",
            "profile_name": "test",
            "status": "draft",
        })
        assert resp.status_code == 201
        assert resp.json()["status"] == "draft"

        # Update to ACTIVE
        resp = client.put("/api/v1/catalog/capabilities/lifecycle.v1", json={
            "status": "active",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

        # Update to DEPRECATED
        resp = client.put("/api/v1/catalog/capabilities/lifecycle.v1", json={
            "status": "deprecated",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "deprecated"
