"""Tests for the /config/history endpoint + AgentManager accessor (audit 1.5).

The endpoint used to be a dead stub that always returned []; it now surfaces the
real config-history snapshots the AgentManager records.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_orchestrator.api.app import create_app
from agent_orchestrator.configuration.agent_manager import AgentManager
from agent_orchestrator.persistence.config_history import ConfigHistory

from .test_core import _make_test_config_manager

API = "/api/v1"


# ---- AgentManager.list_config_history ---------------------------------------


def test_history_enabled_by_default_but_empty(tmp_path):
    # History is now on by default (dir created on demand), even without a
    # pre-existing .history — it's just empty until something is recorded.
    manager = AgentManager(_make_test_config_manager(tmp_path))
    assert manager._history is not None
    assert (tmp_path / ".history").is_dir()
    assert manager.list_config_history() == []


def test_history_lists_recorded_snapshots_with_component_and_label(tmp_path):
    manager = AgentManager(_make_test_config_manager(tmp_path))  # history auto-created
    assert manager._history is not None

    src = tmp_path / "agents.yaml"
    src.write_text("agents: []\n", encoding="utf-8")
    manager._history.record(src, label="agent_crud")

    history = manager.list_config_history()
    assert len(history) == 1
    assert history[0]["name"].startswith("agents_")
    assert history[0]["component"] == "agents"
    assert history[0]["label"] == "agent_crud"
    assert history[0]["modified"]  # ISO timestamp present


# ---- Route ------------------------------------------------------------------


def test_route_empty_without_manager():
    client = TestClient(create_app())  # no workspace → no agent_manager
    resp = client.get(f"{API}/config/history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_route_returns_manager_history():
    class _FakeManager:
        def list_config_history(self):
            return [{"name": "agents_20260722.yaml", "modified": "2026-07-22T00:00:00+00:00"}]

    app = create_app()
    app.state.agent_manager = _FakeManager()
    client = TestClient(app)
    body = client.get(f"{API}/config/history").json()
    assert body == [{"name": "agents_20260722.yaml", "modified": "2026-07-22T00:00:00+00:00"}]
