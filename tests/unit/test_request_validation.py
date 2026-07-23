"""Request-model validation for previously raw-`dict` endpoints (audit 2.5).

These endpoints used to accept `body: dict` with no schema, silently defaulting
missing fields. They now use Pydantic models, so bad input returns 422.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_orchestrator.api.app import create_app

API = "/api/v1"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# ---- 422 on missing required fields -----------------------------------------


@pytest.mark.parametrize(
    "path,bad_body",
    [
        (f"{API}/branching/evaluate", {}),                 # condition required
        (f"{API}/branching/resolve", {}),                  # phase_config required
        (f"{API}/communication/request", {"question": "?"}),  # missing ids/role
        (f"{API}/communication/respond/r1", {}),           # responder/response required
        (f"{API}/plugins/register", {"name": "P"}),        # id required
        (f"{API}/schedules/", {}),                         # workflow_id required
        (f"{API}/tenants/", {"tenant_id": "t1"}),          # tenant_name required
    ],
)
def test_missing_required_fields_return_422(client, path, bad_body):
    assert client.post(path, json=bad_body).status_code == 422


def test_wrong_types_return_422(client):
    # cost endpoints have no required fields but are now typed.
    assert client.post(f"{API}/cost/estimate", json={"tasks": "not-a-list"}).status_code == 422
    assert client.post(f"{API}/cost/recommend-model", json={"story_points": "abc"}).status_code == 422


# ---- valid bodies still succeed ---------------------------------------------


def test_branching_evaluate_valid(client):
    resp = client.post(f"{API}/branching/evaluate", json={"condition": "x == 1", "context": {"x": 1}})
    assert resp.status_code == 200
    assert resp.json()["result"] is True


def test_cost_estimate_valid_empty(client):
    resp = client.post(f"{API}/cost/estimate", json={"tasks": []})
    assert resp.status_code == 200
    assert "optimized_total" in resp.json()


def test_plugin_register_valid(client):
    resp = client.post(f"{API}/plugins/register", json={"id": "p1", "name": "Plugin One"})
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "p1"


def test_tenant_create_valid(client):
    resp = client.post(f"{API}/tenants/", json={"tenant_id": "t1", "tenant_name": "Tenant One"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_schedule_create_valid(client):
    resp = client.post(f"{API}/schedules/", json={"workflow_id": "wf1"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
