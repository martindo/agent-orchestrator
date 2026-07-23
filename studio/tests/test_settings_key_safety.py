"""Studio must not persist env-sourced API keys to plaintext YAML (audit 2.4).

Aligns Studio's settings store with the runtime's: keys supplied via env vars
are stripped on save and re-applied from env on load; user-entered keys are kept.
"""

from __future__ import annotations

from types import SimpleNamespace

import yaml

from studio.routes import settings_routes as sr


def _request(tmp_path, api_keys: dict) -> SimpleNamespace:
    state = SimpleNamespace(
        llm_settings={"api_keys": dict(api_keys), "endpoints": {}},
        studio_config=SimpleNamespace(workspace_dir=str(tmp_path)),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_env_sourced_key_not_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ORCH_OPENAI_API_KEY", "env-secret")
    request = _request(tmp_path, {"openai": "env-secret", "anthropic": "user-typed"})

    sr._save_to_disk(request)

    raw = (tmp_path / sr._SETTINGS_FILE).read_text(encoding="utf-8")
    assert "env-secret" not in raw          # env-sourced key not persisted
    assert "user-typed" in raw              # user-entered key kept
    on_disk = yaml.safe_load(raw)["api_keys"]
    assert on_disk["openai"] == ""
    assert on_disk["anthropic"] == "user-typed"


def test_env_key_refilled_on_load(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ORCH_OPENAI_API_KEY", "env-secret")
    # Persist with the env key stripped.
    sr._save_to_disk(_request(tmp_path, {"openai": "env-secret", "anthropic": "user-typed"}))

    # A fresh store loads: openai refilled from env, anthropic from disk.
    fresh = _request(tmp_path, {})
    sr._load_from_disk(fresh)
    keys = fresh.app.state.llm_settings["api_keys"]
    assert keys["openai"] == "env-secret"
    assert keys["anthropic"] == "user-typed"


def test_user_key_persisted_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_ORCH_ANTHROPIC_API_KEY", raising=False)
    sr._save_to_disk(_request(tmp_path, {"anthropic": "typed-by-user"}))
    on_disk = yaml.safe_load((tmp_path / sr._SETTINGS_FILE).read_text())["api_keys"]
    assert on_disk["anthropic"] == "typed-by-user"  # kept — not env-sourced
