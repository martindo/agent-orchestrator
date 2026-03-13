"""Unit tests for REST API endpoints."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from fastapi.testclient import TestClient

from agent_orchestrator.api.app import create_app
from agent_orchestrator.configuration.models import AgentDefinition, LLMConfig
from agent_orchestrator.exceptions import AgentError, ConfigurationError, OrchestratorError


@pytest.fixture
def client() -> TestClient:
    """Create a test client with no engine (bare app)."""
    app = create_app()
    return TestClient(app)


def _make_agent(agent_id: str = "test-agent", name: str = "Test Agent") -> AgentDefinition:
    """Create a test AgentDefinition."""
    return AgentDefinition(
        id=agent_id,
        name=name,
        system_prompt="You are a test agent.",
        phases=["process"],
        llm=LLMConfig(provider="openai", model="gpt-4o"),
    )


def _make_client_with_manager(agent_manager: MagicMock) -> TestClient:
    """Create a test client with a mocked AgentManager."""
    app = create_app()
    app.state.agent_manager = agent_manager
    return TestClient(app)


def _make_mock_engine() -> MagicMock:
    """Create a properly configured mock engine."""
    engine = MagicMock()
    engine.get_status.return_value = {
        "state": "running",
        "queue": {"current_size": 0},
        "pipeline": {"total_items": 0},
        "agents": {},
    }
    engine.list_work_items.return_value = []
    engine.get_work_item.return_value = None
    engine.get_workflow_phases.return_value = []
    engine.get_workflow_phase.return_value = None

    # Mock async methods
    engine.start = AsyncMock()
    engine.stop = AsyncMock()
    engine.pause = AsyncMock()
    engine.resume = AsyncMock()
    engine.submit_work = AsyncMock()

    # Governor
    mock_governor = MagicMock()
    mock_governor.list_policies.return_value = []
    engine.governor = mock_governor

    # Review queue
    mock_review_queue = MagicMock()
    mock_review_queue.get_all.return_value = []
    engine.review_queue = mock_review_queue

    # Audit logger
    mock_audit = MagicMock()
    mock_audit.query.return_value = []
    engine.audit_logger = mock_audit

    # Metrics
    mock_metrics = MagicMock()
    mock_metrics.get_summary.return_value = {"total_entries": 0, "counters": {}}
    engine.metrics = mock_metrics

    return engine


def _make_client_with_engine(engine: MagicMock) -> TestClient:
    """Create a test client with a mocked engine."""
    app = create_app()
    app.state.engine = engine
    return TestClient(app)


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health(self, client: TestClient) -> None:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

    def test_readiness(self, client: TestClient) -> None:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_liveness(self, client: TestClient) -> None:
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"


class TestAgentEndpoints:
    """Tests for agent management endpoints."""

    def test_list_agents(self, client: TestClient) -> None:
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_unknown_agent(self, client: TestClient) -> None:
        response = client.get("/api/v1/agents/nonexistent")
        assert response.status_code == 404


class TestAgentCRUDEndpoints:
    """Tests for agent CRUD endpoints with mocked AgentManager."""

    def test_list_agents_with_data(self) -> None:
        mock_am = MagicMock()
        mock_am.list_agents.return_value = [
            _make_agent("a1", "Agent 1"),
            _make_agent("a2", "Agent 2"),
        ]
        client = _make_client_with_manager(mock_am)

        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "a1"
        assert data[1]["id"] == "a2"

    def test_get_agent(self) -> None:
        mock_am = MagicMock()
        mock_am.get_agent.return_value = _make_agent("a1", "Agent 1")
        client = _make_client_with_manager(mock_am)

        response = client.get("/api/v1/agents/a1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "a1"
        assert data["name"] == "Agent 1"
        assert data["provider"] == "openai"
        assert data["model"] == "gpt-4o"

    def test_get_unknown_agent_returns_404(self) -> None:
        mock_am = MagicMock()
        mock_am.get_agent.return_value = None
        client = _make_client_with_manager(mock_am)

        response = client.get("/api/v1/agents/unknown")
        assert response.status_code == 404

    def test_create_agent(self) -> None:
        mock_am = MagicMock()
        mock_am.create_agent.return_value = _make_agent("new-agent", "New Agent")
        client = _make_client_with_manager(mock_am)

        response = client.post("/api/v1/agents", json={
            "id": "new-agent",
            "name": "New Agent",
            "system_prompt": "test prompt",
            "phases": ["process"],
            "llm": {"provider": "openai", "model": "gpt-4o"},
        })
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "new-agent"
        mock_am.create_agent.assert_called_once()

    def test_create_duplicate_returns_409(self) -> None:
        mock_am = MagicMock()
        mock_am.create_agent.side_effect = AgentError("Agent 'dup' already exists")
        client = _make_client_with_manager(mock_am)

        response = client.post("/api/v1/agents", json={
            "id": "dup",
            "name": "Dup",
            "system_prompt": "test",
            "phases": ["p1"],
            "llm": {"provider": "openai", "model": "gpt-4o"},
        })
        assert response.status_code == 409

    def test_create_invalid_returns_422(self) -> None:
        mock_am = MagicMock()
        mock_am.create_agent.side_effect = ConfigurationError("Invalid agent")
        client = _make_client_with_manager(mock_am)

        response = client.post("/api/v1/agents", json={
            "id": "bad",
            "name": "Bad",
            "system_prompt": "test",
            "phases": ["p1"],
            "llm": {"provider": "openai", "model": "gpt-4o"},
        })
        assert response.status_code == 422

    def test_update_agent(self) -> None:
        updated = _make_agent("a1", "Updated Name")
        mock_am = MagicMock()
        mock_am.update_agent.return_value = updated
        client = _make_client_with_manager(mock_am)

        response = client.put("/api/v1/agents/a1", json={
            "name": "Updated Name",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"

    def test_update_unknown_returns_404(self) -> None:
        mock_am = MagicMock()
        mock_am.update_agent.side_effect = AgentError("Agent 'x' not found")
        client = _make_client_with_manager(mock_am)

        response = client.put("/api/v1/agents/x", json={"name": "X"})
        assert response.status_code == 404

    def test_update_empty_body_returns_422(self) -> None:
        mock_am = MagicMock()
        client = _make_client_with_manager(mock_am)

        response = client.put("/api/v1/agents/a1", json={})
        assert response.status_code == 422

    def test_delete_agent(self) -> None:
        mock_am = MagicMock()
        mock_am.delete_agent.return_value = True
        client = _make_client_with_manager(mock_am)

        response = client.delete("/api/v1/agents/a1")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["agent_id"] == "a1"

    def test_delete_unknown_returns_404(self) -> None:
        mock_am = MagicMock()
        mock_am.delete_agent.return_value = False
        client = _make_client_with_manager(mock_am)

        response = client.delete("/api/v1/agents/unknown")
        assert response.status_code == 404

    def test_export_agents(self) -> None:
        mock_am = MagicMock()
        agent = _make_agent("a1", "Agent 1")
        mock_am.list_agents.return_value = [agent]
        client = _make_client_with_manager(mock_am)

        response = client.get("/api/v1/agents/export")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert len(data["agents"]) == 1


# ---- No-engine fallback tests ----


class TestNoEngineEndpoints:
    """Tests that endpoints degrade gracefully when no engine is present."""

    def test_workitems_list_returns_empty(self, client: TestClient) -> None:
        response = client.get("/api/v1/workitems")
        assert response.status_code == 200
        assert response.json() == []

    def test_workitems_create_returns_503(self, client: TestClient) -> None:
        response = client.post("/api/v1/workitems", json={
            "id": "w1", "type_id": "task", "title": "Test",
        })
        assert response.status_code == 503

    def test_workitems_get_returns_503(self, client: TestClient) -> None:
        response = client.get("/api/v1/workitems/w1")
        assert response.status_code == 503

    def test_execution_status_returns_idle(self, client: TestClient) -> None:
        response = client.get("/api/v1/execution/status")
        assert response.status_code == 200
        assert response.json()["state"] == "idle"

    def test_execution_start_returns_503(self, client: TestClient) -> None:
        response = client.post("/api/v1/execution/start")
        assert response.status_code == 503

    def test_execution_stop_returns_503(self, client: TestClient) -> None:
        response = client.post("/api/v1/execution/stop")
        assert response.status_code == 503

    def test_execution_pause_returns_503(self, client: TestClient) -> None:
        response = client.post("/api/v1/execution/pause")
        assert response.status_code == 503

    def test_execution_resume_returns_503(self, client: TestClient) -> None:
        response = client.post("/api/v1/execution/resume")
        assert response.status_code == 503

    def test_governance_policies_returns_empty(self, client: TestClient) -> None:
        response = client.get("/api/v1/governance/policies")
        assert response.status_code == 200
        assert response.json() == []

    def test_governance_reviews_returns_empty(self, client: TestClient) -> None:
        response = client.get("/api/v1/governance/reviews")
        assert response.status_code == 200
        assert response.json() == []

    def test_metrics_returns_empty(self, client: TestClient) -> None:
        response = client.get("/api/v1/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_entries"] == 0

    def test_audit_returns_empty(self, client: TestClient) -> None:
        response = client.get("/api/v1/audit")
        assert response.status_code == 200
        assert response.json() == []

    def test_config_profiles_returns_empty(self, client: TestClient) -> None:
        response = client.get("/api/v1/config/profiles")
        assert response.status_code == 200
        assert response.json()["profiles"] == []

    def test_config_validate_returns_valid(self, client: TestClient) -> None:
        response = client.post("/api/v1/config/validate")
        assert response.status_code == 200
        assert response.json()["is_valid"] is True

    def test_scale_agent_returns_503(self, client: TestClient) -> None:
        response = client.post("/api/v1/agents/a1/scale?concurrency=2")
        assert response.status_code == 503

    def test_workflow_phases_returns_empty(self, client: TestClient) -> None:
        response = client.get("/api/v1/workflow/phases")
        assert response.status_code == 200
        assert response.json() == []

    def test_workflow_phase_returns_404(self, client: TestClient) -> None:
        response = client.get("/api/v1/workflow/phases/p1")
        assert response.status_code == 404


# ---- Wired endpoint tests (mocked engine) ----


class TestExecutionEndpointsWired:
    """Tests for execution endpoints with mocked engine."""

    def test_status_returns_engine_state(self) -> None:
        engine = _make_mock_engine()
        engine.get_status.return_value = {
            "state": "running",
            "queue": {"current_size": 2},
            "pipeline": {"total_items": 1},
            "agents": {"agent-1": {"running": 1}},
        }
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/execution/status")
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "running"
        assert data["queue"]["current_size"] == 2

    def test_start_calls_engine(self) -> None:
        engine = _make_mock_engine()
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/execution/start")
        assert response.status_code == 200
        assert response.json()["status"] == "started"
        engine.start.assert_called_once()

    def test_start_already_running_returns_409(self) -> None:
        engine = _make_mock_engine()
        engine.start.side_effect = OrchestratorError("Cannot start engine in state 'running'")
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/execution/start")
        assert response.status_code == 409

    def test_stop_calls_engine(self) -> None:
        engine = _make_mock_engine()
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/execution/stop")
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"
        engine.stop.assert_called_once()

    def test_pause_calls_engine(self) -> None:
        engine = _make_mock_engine()
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/execution/pause")
        assert response.status_code == 200
        assert response.json()["status"] == "paused"
        engine.pause.assert_called_once()

    def test_resume_calls_engine(self) -> None:
        engine = _make_mock_engine()
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/execution/resume")
        assert response.status_code == 200
        assert response.json()["status"] == "resumed"
        engine.resume.assert_called_once()


class TestWorkItemEndpointsWired:
    """Tests for work item endpoints with mocked engine."""

    def test_list_work_items(self) -> None:
        engine = _make_mock_engine()
        engine.list_work_items.return_value = [
            {"id": "w1", "type_id": "task", "title": "Item 1", "status": "pending", "current_phase": "p1", "priority": 5},
            {"id": "w2", "type_id": "bug", "title": "Item 2", "status": "in_progress", "current_phase": "p2", "priority": 3},
        ]
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/workitems")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "w1"
        assert data[1]["status"] == "in_progress"

    def test_submit_work_item(self) -> None:
        engine = _make_mock_engine()
        engine.submit_work.return_value = "w1"
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/workitems", json={
            "id": "w1", "type_id": "task", "title": "New item",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "w1"
        assert data["title"] == "New item"
        engine.submit_work.assert_called_once()

    def test_submit_work_item_engine_error(self) -> None:
        engine = _make_mock_engine()
        engine.submit_work.side_effect = OrchestratorError("Engine not running")
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/workitems", json={
            "id": "w1", "type_id": "task", "title": "Fail",
        })
        assert response.status_code == 409

    def test_get_work_item(self) -> None:
        engine = _make_mock_engine()
        mock_item = MagicMock()
        mock_item.id = "w1"
        mock_item.type_id = "task"
        mock_item.title = "Found item"
        mock_item.status.value = "pending"
        mock_item.current_phase = "process"
        mock_item.data = {}
        mock_item.results = {}
        mock_item.app_id = "default"
        mock_item.run_id = ""
        engine.get_work_item.return_value = mock_item
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/workitems/w1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "w1"
        assert data["title"] == "Found item"

    def test_get_work_item_not_found(self) -> None:
        engine = _make_mock_engine()
        engine.get_work_item.return_value = None
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/workitems/nonexistent")
        assert response.status_code == 404


class TestWorkflowEndpointsWired:
    """Tests for workflow endpoints with mocked engine."""

    def test_list_phases(self) -> None:
        engine = _make_mock_engine()
        mock_phase = MagicMock()
        mock_phase.id = "p1"
        mock_phase.name = "Process"
        mock_phase.description = "Main phase"
        mock_phase.order = 1
        mock_phase.agents = ["agent-1"]
        mock_phase.parallel = False
        mock_phase.on_success = "p2"
        mock_phase.on_failure = ""
        mock_phase.is_terminal = False
        mock_phase.requires_human = False
        mock_phase.skippable = False
        engine.get_workflow_phases.return_value = [mock_phase]
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/workflow/phases")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "p1"
        assert data[0]["name"] == "Process"
        assert data[0]["agents"] == ["agent-1"]

    def test_get_phase(self) -> None:
        engine = _make_mock_engine()
        mock_phase = MagicMock()
        mock_phase.id = "p1"
        mock_phase.name = "Process"
        mock_phase.description = ""
        mock_phase.order = 1
        mock_phase.agents = ["agent-1"]
        mock_phase.parallel = False
        mock_phase.on_success = "p2"
        mock_phase.on_failure = ""
        mock_phase.is_terminal = False
        mock_phase.requires_human = False
        mock_phase.skippable = False
        engine.get_workflow_phase.return_value = mock_phase
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/workflow/phases/p1")
        assert response.status_code == 200
        assert response.json()["id"] == "p1"

    def test_get_phase_not_found(self) -> None:
        engine = _make_mock_engine()
        engine.get_workflow_phase.return_value = None
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/workflow/phases/nonexistent")
        assert response.status_code == 404


class TestGovernanceEndpointsWired:
    """Tests for governance endpoints with mocked engine."""

    def test_list_policies(self) -> None:
        engine = _make_mock_engine()
        mock_policy = MagicMock()
        mock_policy.id = "pol-1"
        mock_policy.name = "Safety"
        mock_policy.action = "review"
        mock_policy.priority = 10
        mock_policy.enabled = True
        engine.governor.list_policies.return_value = [mock_policy]
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/governance/policies")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "pol-1"
        assert data[0]["action"] == "review"

    def test_create_policy(self) -> None:
        engine = _make_mock_engine()
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/governance/policies", json={
            "id": "pol-new",
            "name": "New Policy",
            "action": "warn",
            "priority": 5,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "pol-new"
        assert data["action"] == "warn"
        engine.governor.add_policy.assert_called_once()

    def test_create_policy_no_engine(self, client: TestClient) -> None:
        response = client.post("/api/v1/governance/policies", json={
            "id": "pol-1", "name": "P", "action": "allow",
        })
        assert response.status_code == 503

    def test_list_reviews(self) -> None:
        engine = _make_mock_engine()
        mock_review = MagicMock()
        mock_review.id = "review-1"
        mock_review.work_id = "w1"
        mock_review.phase_id = "p1"
        mock_review.reason = "Low confidence"
        mock_review.reviewed = False
        mock_review.reviewed_by = None
        mock_review.created_at.isoformat.return_value = "2026-01-01T00:00:00+00:00"
        engine.review_queue.get_all.return_value = [mock_review]
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/governance/reviews")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "review-1"
        assert data[0]["reviewed"] is False


class TestMetricsEndpointsWired:
    """Tests for metrics endpoints with mocked engine."""

    def test_get_metrics_summary(self) -> None:
        engine = _make_mock_engine()
        engine.metrics.get_summary.return_value = {
            "total_entries": 42,
            "counters": {"phase.completed": 10, "work.completed": 5},
        }
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_entries"] == 42
        assert data["counters"]["phase.completed"] == 10

    def test_get_agent_metrics(self) -> None:
        engine = _make_mock_engine()
        engine.get_status.return_value = {
            "state": "running",
            "agents": {
                "agent-1": {"running": 2, "idle": 0, "max_concurrency": 3},
            },
        }
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/metrics/agents/agent-1")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "agent-1"
        assert data["metrics"]["running"] == 2

    def test_get_unknown_agent_metrics(self) -> None:
        engine = _make_mock_engine()
        engine.get_status.return_value = {"state": "running", "agents": {}}
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/metrics/agents/unknown")
        assert response.status_code == 200
        data = response.json()
        assert data["metrics"] == {}


class TestAuditEndpointsWired:
    """Tests for audit endpoints with mocked engine."""

    def test_query_audit(self) -> None:
        engine = _make_mock_engine()
        engine.audit_logger.query.return_value = [
            {"sequence": 1, "record_type": "system_event", "action": "engine.start", "summary": "Started"},
        ]
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/audit")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["action"] == "engine.start"

    def test_query_audit_with_filters(self) -> None:
        engine = _make_mock_engine()
        engine.audit_logger.query.return_value = []
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/audit?work_id=w1&record_type=state_change&limit=50")
        assert response.status_code == 200
        from agent_orchestrator.governance.audit_logger import RecordType
        engine.audit_logger.query.assert_called_once_with(
            work_id="w1", record_type=RecordType.STATE_CHANGE, limit=50,
        )

    def test_query_audit_invalid_record_type(self) -> None:
        engine = _make_mock_engine()
        client = _make_client_with_engine(engine)

        response = client.get("/api/v1/audit?record_type=invalid")
        assert response.status_code == 422


class TestConfigEndpointsWired:
    """Tests for config endpoints with mocked config_manager."""

    def test_list_profiles(self) -> None:
        app = create_app()
        mock_cm = MagicMock()
        mock_cm.list_profiles.return_value = ["default", "production"]
        mock_settings = MagicMock()
        mock_settings.active_profile = "default"
        mock_cm.get_settings.return_value = mock_settings
        app.state.config_manager = mock_cm
        client = TestClient(app)

        response = client.get("/api/v1/config/profiles")
        assert response.status_code == 200
        data = response.json()
        assert data["profiles"] == ["default", "production"]
        assert data["active"] == "default"

    def test_validate_config(self) -> None:
        app = create_app()
        mock_cm = MagicMock()
        mock_profile = MagicMock()
        mock_settings = MagicMock()
        mock_cm.get_profile.return_value = mock_profile
        mock_cm.get_settings.return_value = mock_settings
        app.state.config_manager = mock_cm

        with patch("agent_orchestrator.api.routes.validate_profile") as mock_validate:
            mock_result = MagicMock()
            mock_result.is_valid = True
            mock_result.errors = []
            mock_result.warnings = ["No API keys configured"]
            mock_validate.return_value = mock_result

            client = TestClient(app)
            response = client.post("/api/v1/config/validate")
            assert response.status_code == 200
            data = response.json()
            assert data["is_valid"] is True
            assert data["warnings"] == ["No API keys configured"]

    def test_validate_config_errors(self) -> None:
        app = create_app()
        mock_cm = MagicMock()
        mock_profile = MagicMock()
        mock_settings = MagicMock()
        mock_cm.get_profile.return_value = mock_profile
        mock_cm.get_settings.return_value = mock_settings
        app.state.config_manager = mock_cm

        with patch("agent_orchestrator.api.routes.validate_profile") as mock_validate:
            mock_result = MagicMock()
            mock_result.is_valid = False
            mock_result.errors = ["Agent 'x' references unknown phase"]
            mock_result.warnings = []
            mock_validate.return_value = mock_result

            client = TestClient(app)
            response = client.post("/api/v1/config/validate")
            assert response.status_code == 200
            data = response.json()
            assert data["is_valid"] is False
            assert len(data["errors"]) == 1


class TestScaleAgentWired:
    """Tests for agent scale endpoint with mocked engine."""

    def test_scale_agent(self) -> None:
        engine = _make_mock_engine()
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/agents/agent-1/scale?concurrency=3")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "scaled"
        assert data["agent_id"] == "agent-1"
        assert data["concurrency"] == "3"
        engine.scale_agent.assert_called_once_with("agent-1", 3)

    def test_scale_agent_error(self) -> None:
        engine = _make_mock_engine()
        engine.scale_agent.side_effect = Exception("Agent not found")
        client = _make_client_with_engine(engine)

        response = client.post("/api/v1/agents/agent-1/scale?concurrency=5")
        assert response.status_code == 400


# ---- Connector Execute Endpoint Tests ----

from agent_orchestrator.connectors.models import (  # noqa: E402
    CapabilityType,
    ConnectorCostInfo,
    ConnectorInvocationResult,
    ConnectorStatus,
)


def _make_invocation_result(
    status: ConnectorStatus = ConnectorStatus.SUCCESS,
    payload: dict | None = None,
    error_message: str | None = None,
    capability_type: CapabilityType = CapabilityType.SEARCH,
    operation: str = "query",
    cost_info: ConnectorCostInfo | None = None,
) -> ConnectorInvocationResult:
    return ConnectorInvocationResult(
        request_id="req-test-001",
        connector_id="search-tavily",
        provider="tavily",
        capability_type=capability_type,
        operation=operation,
        status=status,
        payload=payload,
        error_message=error_message,
        cost_info=cost_info,
        duration_ms=42.0,
    )


def _make_engine_with_connector_service(result: ConnectorInvocationResult) -> MagicMock:
    engine = _make_mock_engine()
    mock_service = MagicMock()
    mock_service.execute = AsyncMock(return_value=result)
    engine.connector_service = mock_service
    return engine


class TestConnectorExecuteEndpoint:
    """Tests for POST /api/v1/connectors/execute."""

    def test_successful_search_execution(self) -> None:
        payload = {"query": "test query", "results": [{"title": "Result 1", "url": "https://example.com"}]}
        result = _make_invocation_result(payload=payload)
        engine = _make_engine_with_connector_service(result)
        client = _make_client_with_engine(engine)

        response = client.post(
            "/api/v1/connectors/execute",
            json={"capability_type": "search", "operation": "query", "parameters": {"q": "test query"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["provider"] == "tavily"
        assert data["capability_type"] == "search"
        assert data["operation"] == "query"
        assert data["payload"] == payload
        assert data["duration_ms"] == 42.0

    def test_passes_all_fields_to_service(self) -> None:
        result = _make_invocation_result()
        engine = _make_engine_with_connector_service(result)
        client = _make_client_with_engine(engine)

        client.post(
            "/api/v1/connectors/execute",
            json={
                "capability_type": "search",
                "operation": "query",
                "parameters": {"q": "climate change"},
                "context": {"run_id": "r1", "workflow_id": "w1"},
                "preferred_provider": "brave",
                "timeout_seconds": 10.0,
            },
        )

        engine.connector_service.execute.assert_called_once_with(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={"q": "climate change"},
            context={"run_id": "r1", "workflow_id": "w1"},
            preferred_provider="brave",
            timeout_seconds=10.0,
        )

    def test_permission_denied_returns_200_with_status(self) -> None:
        result = _make_invocation_result(
            status=ConnectorStatus.PERMISSION_DENIED,
            error_message="Denied by policy: module not allowed",
        )
        engine = _make_engine_with_connector_service(result)
        client = _make_client_with_engine(engine)

        response = client.post(
            "/api/v1/connectors/execute",
            json={"capability_type": "search", "operation": "query", "parameters": {}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "permission_denied"
        assert data["payload"] is None

    def test_unavailable_provider_returns_200_with_status(self) -> None:
        result = _make_invocation_result(
            status=ConnectorStatus.UNAVAILABLE,
            error_message="No provider available for capability_type=search",
        )
        engine = _make_engine_with_connector_service(result)
        client = _make_client_with_engine(engine)

        response = client.post(
            "/api/v1/connectors/execute",
            json={"capability_type": "search", "operation": "query", "parameters": {}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unavailable"

    def test_unknown_capability_type_returns_422(self) -> None:
        result = _make_invocation_result()
        engine = _make_engine_with_connector_service(result)
        client = _make_client_with_engine(engine)

        response = client.post(
            "/api/v1/connectors/execute",
            json={"capability_type": "not_a_real_type", "operation": "query", "parameters": {}},
        )

        assert response.status_code == 422
        assert "not_a_real_type" in response.json()["detail"]

    def test_no_engine_returns_503(self) -> None:
        app = create_app()
        client = TestClient(app)

        response = client.post(
            "/api/v1/connectors/execute",
            json={"capability_type": "search", "operation": "query", "parameters": {}},
        )

        assert response.status_code == 503

    def test_no_connector_service_returns_503(self) -> None:
        engine = _make_mock_engine()
        engine.connector_service = None
        client = _make_client_with_engine(engine)

        response = client.post(
            "/api/v1/connectors/execute",
            json={"capability_type": "search", "operation": "query", "parameters": {}},
        )

        assert response.status_code == 503

    def test_cost_info_included_in_response(self) -> None:
        cost = ConnectorCostInfo(request_cost=0.004, currency="USD", unit_label="search")
        result = _make_invocation_result(
            payload={"query": "q", "results": []},
            cost_info=cost,
        )
        engine = _make_engine_with_connector_service(result)
        client = _make_client_with_engine(engine)

        response = client.post(
            "/api/v1/connectors/execute",
            json={"capability_type": "search", "operation": "query", "parameters": {"q": "q"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["cost_info"]["request_cost"] == 0.004
        assert data["cost_info"]["currency"] == "USD"
        assert data["cost_info"]["unit_label"] == "search"

    def test_empty_context_defaults_to_none(self) -> None:
        result = _make_invocation_result()
        engine = _make_engine_with_connector_service(result)
        client = _make_client_with_engine(engine)

        client.post(
            "/api/v1/connectors/execute",
            json={"capability_type": "search", "operation": "query", "parameters": {}},
        )

        call_kwargs = engine.connector_service.execute.call_args.kwargs
        assert call_kwargs["context"] is None

    def test_all_capability_types_accepted(self) -> None:
        valid_types = ["search", "documents", "messaging", "ticketing", "repository"]
        for cap_type in valid_types:
            result = _make_invocation_result(capability_type=CapabilityType(cap_type))
            engine = _make_engine_with_connector_service(result)
            client = _make_client_with_engine(engine)

            response = client.post(
                "/api/v1/connectors/execute",
                json={"capability_type": cap_type, "operation": "test_op", "parameters": {}},
            )

            assert response.status_code == 200, f"Failed for capability_type={cap_type}"
