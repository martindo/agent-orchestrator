"""The Studio working team survives a backend restart (audit 6.1).

Previously the team lived only in app.state (in-memory) and was lost on restart.
It's now persisted to the workspace and reloaded on demand. A "restart" is
modelled here as a fresh app (empty in-memory state) on the same workspace.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from studio.app import create_app

TEAMS = "/api/studio/teams"


def _client(config) -> TestClient:
    return TestClient(create_app(config))


def test_created_team_survives_restart(studio_config):
    first = _client(studio_config)
    assert first.post(TEAMS, json={"name": "My Team", "description": "d"}).status_code == 200

    # Fresh app on the same workspace has no in-memory team → loads from disk.
    second = _client(studio_config)
    resp = second.get(f"{TEAMS}/current")
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Team"


def test_update_is_persisted(studio_config):
    first = _client(studio_config)
    first.post(TEAMS, json={"name": "T", "description": ""})
    current = first.get(f"{TEAMS}/current").json()
    current["description"] = "updated after restart"
    assert first.put(f"{TEAMS}/current", json=current).status_code == 200

    second = _client(studio_config)
    assert second.get(f"{TEAMS}/current").json()["description"] == "updated after restart"


def test_no_team_still_404(studio_config):
    # A clean workspace with nothing persisted still reports no team.
    assert _client(studio_config).get(f"{TEAMS}/current").status_code == 404
