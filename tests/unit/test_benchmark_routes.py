"""Tests for benchmark REST API routes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_orchestrator.api.benchmark_routes import benchmark_router
from agent_orchestrator.simulation.models import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkRunResult,
    BenchmarkSuiteConfig,
)


# ---- Fake Store ----


class FakeBenchmarkStore:
    """In-memory store for testing benchmark routes."""

    def __init__(self) -> None:
        self._suites: dict[str, BenchmarkSuiteConfig] = {}
        self._runs: dict[str, list[BenchmarkRunResult]] = {}

    def list_suites(self) -> list[BenchmarkSuiteConfig]:
        return list(self._suites.values())

    def load_suite(self, suite_id: str) -> BenchmarkSuiteConfig | None:
        return self._suites.get(suite_id)

    def save_suite(self, suite: BenchmarkSuiteConfig) -> None:
        self._suites[suite.suite_id] = suite

    def delete_suite(self, suite_id: str) -> bool:
        if suite_id in self._suites:
            del self._suites[suite_id]
            return True
        return False

    def get_runs(self, suite_id: str, limit: int = 20) -> list[BenchmarkRunResult]:
        return self._runs.get(suite_id, [])[:limit]

    def get_run(self, run_id: str) -> BenchmarkRunResult | None:
        for runs in self._runs.values():
            for r in runs:
                if r.run_id == run_id:
                    return r
        return None

    def save_run(self, result: BenchmarkRunResult) -> None:
        self._runs.setdefault(result.suite_id, []).append(result)


class FakeBenchmarkRunner:
    """Fake runner that returns a pre-built result."""

    async def run_suite(self, suite: BenchmarkSuiteConfig) -> BenchmarkRunResult:
        case_results = [
            BenchmarkCaseResult(
                case_id=c.case_id,
                passed=True,
                actual_status="completed",
                actual_confidence=0.9,
                duration_seconds=0.1,
            )
            for c in suite.cases
        ]
        return BenchmarkRunResult(
            run_id="run-test-001",
            suite_id=suite.suite_id,
            status="completed",
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
            duration_seconds=1.0,
            total_cases=len(suite.cases),
            passed=len(suite.cases),
            failed=0,
            pass_rate=1.0,
            case_results=case_results,
        )


# ---- Helpers ----


def _make_app(
    store: FakeBenchmarkStore | None = None,
    runner: FakeBenchmarkRunner | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(benchmark_router, prefix="/api/v1")
    mock_engine = MagicMock()

    if store is not None:
        mock_engine.benchmark_store = store
    else:
        mock_engine.benchmark_store = None

    if runner is not None:
        mock_engine.benchmark_runner = runner
    else:
        mock_engine.benchmark_runner = None

    app.state.engine = mock_engine
    return TestClient(app)


def _make_app_no_engine() -> TestClient:
    app = FastAPI()
    app.include_router(benchmark_router, prefix="/api/v1")
    app.state.engine = None
    return TestClient(app)


# ---- Tests: List Suites ----


class TestListSuites:
    def test_list_empty(self) -> None:
        client = _make_app(FakeBenchmarkStore(), FakeBenchmarkRunner())
        resp = client.get("/api/v1/benchmarks/suites")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_no_engine(self) -> None:
        client = _make_app_no_engine()
        resp = client.get("/api/v1/benchmarks/suites")
        assert resp.status_code == 503

    def test_no_store(self) -> None:
        client = _make_app(None, FakeBenchmarkRunner())
        resp = client.get("/api/v1/benchmarks/suites")
        assert resp.status_code == 503


# ---- Tests: Create Suite ----


class TestCreateSuite:
    def test_create_basic(self) -> None:
        store = FakeBenchmarkStore()
        client = _make_app(store, FakeBenchmarkRunner())
        resp = client.post("/api/v1/benchmarks/suites", json={
            "name": "Regression Suite",
            "description": "Tests workflow regression",
            "cases": [
                {
                    "case_id": "case-1",
                    "work_item_data": {"query": "hello"},
                    "expected_status": "completed",
                    "expected_min_confidence": 0.7,
                },
            ],
            "tags": ["regression"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Regression Suite"
        assert data["case_count"] == 1
        assert len(data["cases"]) == 1
        assert data["cases"][0]["case_id"] == "case-1"
        assert "suite_id" in data

    def test_create_empty_cases(self) -> None:
        store = FakeBenchmarkStore()
        client = _make_app(store, FakeBenchmarkRunner())
        resp = client.post("/api/v1/benchmarks/suites", json={
            "name": "Empty Suite",
        })
        assert resp.status_code == 201
        assert resp.json()["case_count"] == 0

    def test_create_persists(self) -> None:
        store = FakeBenchmarkStore()
        client = _make_app(store, FakeBenchmarkRunner())
        client.post("/api/v1/benchmarks/suites", json={
            "name": "Persisted",
            "cases": [{"case_id": "c1"}],
        })
        assert len(store.list_suites()) == 1


# ---- Tests: Get Suite ----


class TestGetSuite:
    def test_get_existing(self) -> None:
        store = FakeBenchmarkStore()
        client = _make_app(store, FakeBenchmarkRunner())
        create_resp = client.post("/api/v1/benchmarks/suites", json={
            "name": "Get Test",
            "cases": [{"case_id": "c1"}],
        })
        suite_id = create_resp.json()["suite_id"]

        resp = client.get(f"/api/v1/benchmarks/suites/{suite_id}")
        assert resp.status_code == 200
        assert resp.json()["suite_id"] == suite_id
        assert resp.json()["case_count"] == 1

    def test_get_not_found(self) -> None:
        client = _make_app(FakeBenchmarkStore(), FakeBenchmarkRunner())
        resp = client.get("/api/v1/benchmarks/suites/missing")
        assert resp.status_code == 404


# ---- Tests: Delete Suite ----


class TestDeleteSuite:
    def test_delete_existing(self) -> None:
        store = FakeBenchmarkStore()
        client = _make_app(store, FakeBenchmarkRunner())
        create_resp = client.post("/api/v1/benchmarks/suites", json={
            "name": "To Delete",
        })
        suite_id = create_resp.json()["suite_id"]

        resp = client.delete(f"/api/v1/benchmarks/suites/{suite_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Confirm gone
        resp = client.get(f"/api/v1/benchmarks/suites/{suite_id}")
        assert resp.status_code == 404

    def test_delete_not_found(self) -> None:
        client = _make_app(FakeBenchmarkStore(), FakeBenchmarkRunner())
        resp = client.delete("/api/v1/benchmarks/suites/missing")
        assert resp.status_code == 404


# ---- Tests: Run Suite ----


class TestRunSuite:
    def test_run_success(self) -> None:
        store = FakeBenchmarkStore()
        runner = FakeBenchmarkRunner()
        client = _make_app(store, runner)

        create_resp = client.post("/api/v1/benchmarks/suites", json={
            "name": "Run Test",
            "cases": [
                {"case_id": "c1", "work_item_data": {"q": "test"}},
                {"case_id": "c2", "work_item_data": {"q": "test2"}},
            ],
        })
        suite_id = create_resp.json()["suite_id"]

        resp = client.post(f"/api/v1/benchmarks/suites/{suite_id}/run")
        assert resp.status_code == 201
        data = resp.json()
        assert data["run_id"] == "run-test-001"
        assert data["status"] == "completed"
        assert data["total_cases"] == 2
        assert data["passed"] == 2
        assert data["failed"] == 0
        assert data["pass_rate"] == 1.0
        assert len(data["case_results"]) == 2

    def test_run_not_found(self) -> None:
        client = _make_app(FakeBenchmarkStore(), FakeBenchmarkRunner())
        resp = client.post("/api/v1/benchmarks/suites/missing/run")
        assert resp.status_code == 404

    def test_run_no_runner(self) -> None:
        store = FakeBenchmarkStore()
        client = _make_app(store, None)
        store.save_suite(BenchmarkSuiteConfig(
            suite_id="s1", name="No Runner",
        ))
        resp = client.post("/api/v1/benchmarks/suites/s1/run")
        assert resp.status_code == 503

    def test_run_saves_result(self) -> None:
        store = FakeBenchmarkStore()
        runner = FakeBenchmarkRunner()
        client = _make_app(store, runner)

        client.post("/api/v1/benchmarks/suites", json={
            "name": "Persist Run",
            "cases": [{"case_id": "c1"}],
        })
        suite_id = client.get("/api/v1/benchmarks/suites").json()[0]["suite_id"]

        client.post(f"/api/v1/benchmarks/suites/{suite_id}/run")
        assert len(store.get_runs(suite_id)) == 1


# ---- Tests: List Runs ----


class TestListRuns:
    def test_list_empty(self) -> None:
        client = _make_app(FakeBenchmarkStore(), FakeBenchmarkRunner())
        resp = client.get("/api/v1/benchmarks/suites/any/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_run(self) -> None:
        store = FakeBenchmarkStore()
        runner = FakeBenchmarkRunner()
        client = _make_app(store, runner)

        client.post("/api/v1/benchmarks/suites", json={
            "name": "List Runs",
            "cases": [{"case_id": "c1"}],
        })
        suite_id = client.get("/api/v1/benchmarks/suites").json()[0]["suite_id"]
        client.post(f"/api/v1/benchmarks/suites/{suite_id}/run")

        resp = client.get(f"/api/v1/benchmarks/suites/{suite_id}/runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ---- Tests: Get Run ----


class TestGetRun:
    def test_get_existing_run(self) -> None:
        store = FakeBenchmarkStore()
        runner = FakeBenchmarkRunner()
        client = _make_app(store, runner)

        client.post("/api/v1/benchmarks/suites", json={
            "name": "Get Run",
            "cases": [{"case_id": "c1"}],
        })
        suite_id = client.get("/api/v1/benchmarks/suites").json()[0]["suite_id"]
        run_resp = client.post(f"/api/v1/benchmarks/suites/{suite_id}/run")
        run_id = run_resp.json()["run_id"]

        resp = client.get(f"/api/v1/benchmarks/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == run_id
        assert resp.json()["suite_id"] == suite_id

    def test_get_run_not_found(self) -> None:
        client = _make_app(FakeBenchmarkStore(), FakeBenchmarkRunner())
        resp = client.get("/api/v1/benchmarks/runs/missing")
        assert resp.status_code == 404


# ---- Tests: Create Suite from History ----


class TestCreateSuiteFromHistory:
    def test_from_explicit_items(self) -> None:
        store = FakeBenchmarkStore()
        client = _make_app(store, FakeBenchmarkRunner())

        resp = client.post("/api/v1/benchmarks/suites/from-history", json={
            "suite_name": "History Suite",
            "min_confidence": 0.5,
            "items": [
                {
                    "id": "wi-1",
                    "data": {"query": "test"},
                    "status": "completed",
                    "results": {"answer": "ok"},
                    "confidence": 0.9,
                },
            ],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "History Suite"
        assert data["case_count"] >= 1

    def test_from_empty_items_no_engine(self) -> None:
        store = FakeBenchmarkStore()
        client = _make_app(store, FakeBenchmarkRunner())

        resp = client.post("/api/v1/benchmarks/suites/from-history", json={
            "suite_name": "Empty History",
            "items": [],
        })
        assert resp.status_code == 201
        assert resp.json()["case_count"] == 0
