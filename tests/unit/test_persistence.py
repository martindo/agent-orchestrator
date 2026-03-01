"""Unit tests for persistence layer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from agent_orchestrator.persistence.config_history import ConfigHistory
from agent_orchestrator.persistence.settings_store import SettingsStore
from agent_orchestrator.persistence.state_store import StateStore
from agent_orchestrator.exceptions import PersistenceError


class TestSettingsStore:
    """Tests for SettingsStore."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        store = SettingsStore(tmp_path / "settings.yaml")
        store.save({"active_profile": "test", "log_level": "DEBUG"})
        data = store.load()
        assert data["active_profile"] == "test"
        assert data["log_level"] == "DEBUG"

    def test_load_missing(self, tmp_path: Path) -> None:
        store = SettingsStore(tmp_path / "missing.yaml")
        data = store.load()
        assert data.get("active_profile") is None
        assert data.get("api_keys") == {}

    def test_get_and_set(self, tmp_path: Path) -> None:
        store = SettingsStore(tmp_path / "settings.yaml")
        store.save({"active_profile": "test"})
        store.set("log_level", "WARNING")
        assert store.get("log_level") == "WARNING"

    def test_creates_backup(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.yaml"
        store = SettingsStore(path)
        store.save({"version": 1})
        store.save({"version": 2})
        backup = path.with_suffix(".yaml.bak")
        assert backup.exists()


class TestStateStore:
    """Tests for StateStore."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / ".state")
        store.save("agents", {"agent-1": {"state": "idle"}})
        data = store.load("agents")
        assert data["agent-1"]["state"] == "idle"

    def test_load_missing(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / ".state")
        assert store.load("nonexistent") is None

    def test_delete(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / ".state")
        store.save("temp", {"key": "value"})
        assert store.delete("temp")
        assert store.load("temp") is None
        assert not store.delete("temp")

    def test_list_namespaces(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / ".state")
        store.save("agents", {})
        store.save("queue", {})
        namespaces = store.list_namespaces()
        assert "agents" in namespaces
        assert "queue" in namespaces

    def test_clear(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / ".state")
        store.save("a", {})
        store.save("b", {})
        store.clear()
        assert store.list_namespaces() == []


class TestConfigHistory:
    """Tests for ConfigHistory."""

    def test_record_and_list(self, tmp_path: Path) -> None:
        history = ConfigHistory(tmp_path / ".history")
        source = tmp_path / "test.yaml"
        source.write_text("key: value", encoding="utf-8")

        path = history.record(source)
        assert path.exists()
        versions = history.list_versions()
        assert len(versions) == 1

    def test_record_missing_raises(self, tmp_path: Path) -> None:
        history = ConfigHistory(tmp_path / ".history")
        with pytest.raises(PersistenceError, match="not found"):
            history.record(tmp_path / "nonexistent.yaml")

    def test_restore(self, tmp_path: Path) -> None:
        history = ConfigHistory(tmp_path / ".history")
        source = tmp_path / "config.yaml"
        source.write_text("version: 1", encoding="utf-8")
        v1_path = history.record(source)

        source.write_text("version: 2", encoding="utf-8")
        history.restore(v1_path, source)
        assert "version: 1" in source.read_text(encoding="utf-8")

    def test_filter_versions(self, tmp_path: Path) -> None:
        history = ConfigHistory(tmp_path / ".history")
        a = tmp_path / "agents.yaml"
        w = tmp_path / "workflow.yaml"
        a.write_text("a", encoding="utf-8")
        w.write_text("w", encoding="utf-8")

        history.record(a)
        history.record(w)

        agent_versions = history.list_versions("agents")
        assert len(agent_versions) == 1
