"""Tests for simulation REST API routes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_orchestrator.api.simulation_routes import simulation_router
from agent_orchestrator.simulation.sandbox import SimulationSandbox


def _make_app(sandbox: SimulationSandbox | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(simulation_router, prefix="/api/v1")
    if sandbox is not None:
        mock_engine = MagicMock()
        mock_engine.simulation_sandbox = sandbox
        mock_engine.list_work_items = MagicMock(return_value=[])
        app.state.engine = mock_engine
    else:
        app.state.engine = None
    return TestClient(app)


class TestListSimulations:
    def test_list_empty(self) -> None:
        client = _make_app(SimulationSandbox())
        resp = client.get("/api/v1/simulations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_no_engine(self) -> None:
        client = _make_app()
        resp = client.get("/api/v1/simulations")
        assert resp.status_code == 503


class TestRunSimulation:
    def test_dry_run(self) -> None:
        client = _make_app(SimulationSandbox())
        resp = client.post("/api/v1/simulations", json={
            "name": "Test",
            "dry_run": True,
            "historical_items": [
                {
                    "id": "wi-1",
                    "data": {"q": "test"},
                    "status": "completed",
                    "results": {},
                    "confidence": 0.8,
                    "phases_completed": 3,
                },
                {
                    "id": "wi-2",
                    "data": {"q": "test2"},
                    "status": "completed",
                    "results": {},
                    "confidence": 0.7,
                    "phases_completed": 2,
                },
            ],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "completed"
        assert data["items_processed"] == 2
        assert data["items_same"] == 2
        assert len(data["comparisons"]) == 2

    def test_empty_items(self) -> None:
        client = _make_app(SimulationSandbox())
        resp = client.post("/api/v1/simulations", json={
            "name": "Empty",
            "historical_items": [],
        })
        assert resp.status_code == 201
        assert resp.json()["items_processed"] == 0


class TestGetSimulation:
    def test_get_after_run(self) -> None:
        sandbox = SimulationSandbox()
        client = _make_app(sandbox)

        # Run a simulation first
        client.post("/api/v1/simulations", json={
            "name": "Get Test",
            "historical_items": [{"id": "wi-1", "data": {}, "status": "completed", "confidence": 0.5}],
        })

        # Get it by listing first
        sims = client.get("/api/v1/simulations").json()
        sim_id = sims[0]["simulation_id"]

        resp = client.get(f"/api/v1/simulations/{sim_id}")
        assert resp.status_code == 200
        assert resp.json()["simulation_id"] == sim_id

    def test_get_not_found(self) -> None:
        client = _make_app(SimulationSandbox())
        resp = client.get("/api/v1/simulations/missing")
        assert resp.status_code == 404


class TestSummary:
    def test_summary(self) -> None:
        sandbox = SimulationSandbox()
        client = _make_app(sandbox)
        client.post("/api/v1/simulations", json={
            "name": "S1",
            "historical_items": [{"id": "wi-1", "data": {}, "status": "completed", "confidence": 0.5}],
        })
        resp = client.get("/api/v1/simulations/summary")
        assert resp.status_code == 200
        assert resp.json()["total_simulations"] == 1
