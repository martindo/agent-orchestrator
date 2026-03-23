"""Tests for Studio API endpoints."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio.app import create_app
from studio.config import StudioConfig


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a test client with a temp workspace."""
    config = StudioConfig(
        workspace_dir=tmp_path,
        runtime_api_url="http://localhost:9999",  # Not running
    )
    app = create_app(config)
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/api/studio/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["team_loaded"] is False


class TestTeamEndpoints:
    def test_create_team(self, client: TestClient) -> None:
        response = client.post("/api/studio/teams", json={
            "name": "Test Team",
            "description": "A test team",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Team"

    def test_get_current_team_404(self, client: TestClient) -> None:
        response = client.get("/api/studio/teams/current")
        assert response.status_code == 404

    def test_create_then_get(self, client: TestClient) -> None:
        client.post("/api/studio/teams", json={"name": "Test"})
        response = client.get("/api/studio/teams/current")
        assert response.status_code == 200
        assert response.json()["name"] == "Test"

    def test_update_team(self, client: TestClient) -> None:
        client.post("/api/studio/teams", json={"name": "Original"})
        response = client.put("/api/studio/teams/current", json={
            "name": "Updated",
            "description": "Updated description",
        })
        assert response.status_code == 200
        assert response.json()["name"] == "Updated"

    def test_import_from_template(self, client: TestClient) -> None:
        response = client.post("/api/studio/teams/from-template", json={
            "template_path": str(Path("profiles/content-moderation").resolve()),
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Content Moderation Pipeline"
        assert len(data["agents"]) == 3


class TestValidationEndpoints:
    def test_validate_empty_team(self, client: TestClient) -> None:
        client.post("/api/studio/teams", json={"name": "Test"})
        response = client.post("/api/studio/validate")
        assert response.status_code == 200
        data = response.json()
        assert "is_valid" in data

    def test_validate_condition(self, client: TestClient) -> None:
        response = client.post("/api/studio/validate/condition", json={
            "expression": "confidence >= 0.8",
        })
        assert response.status_code == 200
        assert response.json()["is_valid"] is True

    def test_validate_bad_condition(self, client: TestClient) -> None:
        response = client.post("/api/studio/validate/condition", json={
            "expression": "",
        })
        assert response.status_code == 200
        assert response.json()["is_valid"] is False


class TestPreviewEndpoints:
    def test_preview_all(self, client: TestClient) -> None:
        # Load a team first
        client.post("/api/studio/teams/from-template", json={
            "template_path": str(Path("profiles/content-moderation").resolve()),
        })
        response = client.get("/api/studio/preview")
        assert response.status_code == 200
        data = response.json()
        assert "agents.yaml" in data
        assert "workflow.yaml" in data

    def test_preview_component(self, client: TestClient) -> None:
        client.post("/api/studio/teams/from-template", json={
            "template_path": str(Path("profiles/content-moderation").resolve()),
        })
        response = client.get("/api/studio/preview/agents")
        assert response.status_code == 200


class TestGraphEndpoints:
    def test_graph(self, client: TestClient) -> None:
        client.post("/api/studio/teams/from-template", json={
            "template_path": str(Path("profiles/content-moderation").resolve()),
        })
        response = client.get("/api/studio/graph")
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 4
        assert len(data["edges"]) == 6
        assert data["is_valid"] is True


class TestConditionEndpoints:
    def test_get_operators(self, client: TestClient) -> None:
        response = client.get("/api/studio/conditions/operators")
        assert response.status_code == 200
        data = response.json()
        assert ">=" in data["operators"]

    def test_build_condition(self, client: TestClient) -> None:
        response = client.post("/api/studio/conditions/build", json={
            "field": "confidence",
            "operator": ">=",
            "value": "0.8",
        })
        assert response.status_code == 200
        assert response.json()["expression"] == "confidence >= 0.8"

    def test_parse_condition(self, client: TestClient) -> None:
        response = client.post("/api/studio/conditions/parse", json={
            "expression": "category == 'safe'",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["field"] == "category"
        assert data["operator"] == "=="


class TestTemplateEndpoints:
    def test_list_templates(self, client: TestClient) -> None:
        # Point at real profiles dir
        client.app.state.studio_config = StudioConfig(
            workspace_dir=Path.cwd(),
        )
        response = client.get("/api/studio/templates")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1

    def test_export(self, client: TestClient) -> None:
        client.post("/api/studio/teams/from-template", json={
            "template_path": str(Path("profiles/content-moderation").resolve()),
        })
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            response = client.post("/api/studio/templates/export", json={
                "output_path": tmp,
            })
            assert response.status_code == 200
            assert response.json()["count"] >= 4


class TestExtensionEndpoints:
    def test_connector_stub(self, client: TestClient) -> None:
        response = client.post("/api/studio/extensions/connector", json={
            "provider_id": "test-api",
            "display_name": "Test API",
        })
        assert response.status_code == 200
        assert "class TestApiProvider:" in response.json()["code"]

    def test_event_handler_stub(self, client: TestClient) -> None:
        response = client.post("/api/studio/extensions/event-handler", json={
            "handler_name": "my-handler",
        })
        assert response.status_code == 200
        assert "class MyHandlerHandler:" in response.json()["code"]

    def test_hook_stub(self, client: TestClient) -> None:
        response = client.post("/api/studio/extensions/hook", json={
            "phase_id": "analysis",
        })
        assert response.status_code == 200
        assert "def hook_analysis(" in response.json()["code"]
