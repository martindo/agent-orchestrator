"""Tests for lineage REST API routes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_orchestrator.api.lineage_routes import lineage_router
from agent_orchestrator.core.work_queue import WorkItemStatus


# ---- Fake Stores ----


@dataclass
class FakeHistoryEntry:
    """Mimics WorkItemHistoryEntry for testing."""

    timestamp: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    from_status: WorkItemStatus | None = None
    to_status: WorkItemStatus = WorkItemStatus.PENDING
    phase_id: str = ""
    agent_id: str = ""
    reason: str = ""


@dataclass
class FakeWorkItem:
    """Mimics a persisted WorkItem."""

    id: str = "wi-1"
    history: list[FakeHistoryEntry] = field(default_factory=list)


class FakeWorkItemStore:
    """In-memory work item store for testing."""

    def __init__(self, items: dict[str, FakeWorkItem] | None = None) -> None:
        self._items = items or {}

    def load(self, work_item_id: str) -> FakeWorkItem | None:
        return self._items.get(work_item_id)


@dataclass
class FakeArtifact:
    """Mimics an Artifact record."""

    artifact_id: str = "art-1"
    work_id: str = "wi-1"
    phase_id: str = "phase-1"
    agent_id: str = "agent-1"
    artifact_type: str = "output"
    content_hash: str = "abc123"
    version: int = 1
    timestamp: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
    )


class FakeArtifactStore:
    """In-memory artifact store for testing."""

    def __init__(self, artifacts: dict[str, list[FakeArtifact]] | None = None) -> None:
        self._artifacts = artifacts or {}

    def get_chain(self, work_item_id: str) -> list[FakeArtifact]:
        return self._artifacts.get(work_item_id, [])


class FakeDecisionLedger:
    """In-memory decision ledger for testing."""

    def __init__(
        self,
        chain: dict[str, list[dict[str, Any]]] | None = None,
        valid: bool = True,
    ) -> None:
        self._chain = chain or {}
        self._valid = valid

    def get_decision_chain(self, work_item_id: str) -> list[dict[str, Any]]:
        return self._chain.get(work_item_id, [])

    def verify_chain(self) -> tuple[bool, int]:
        total = sum(len(c) for c in self._chain.values())
        return self._valid, total


class FakeAuditLogger:
    """In-memory audit logger for testing."""

    def __init__(self, records: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._records = records or {}

    def query(self, work_id: str = "", limit: int = 10000, **kwargs: Any) -> list[dict[str, Any]]:
        return self._records.get(work_id, [])


# ---- Helpers ----


def _make_app(
    work_item_store: Any = None,
    decision_ledger: Any = None,
    artifact_store: Any = None,
    audit_logger: Any = None,
    no_engine: bool = False,
) -> TestClient:
    app = FastAPI()
    app.include_router(lineage_router, prefix="/api/v1")

    if no_engine:
        app.state.engine = None
    else:
        mock_engine = MagicMock()
        mock_engine.work_item_store = work_item_store
        mock_engine.decision_ledger = decision_ledger
        mock_engine.artifact_store = artifact_store
        mock_engine.audit_logger = audit_logger
        app.state.engine = mock_engine

    return TestClient(app)


# ---- Tests: Get Lineage ----


class TestGetLineage:
    def test_no_engine(self) -> None:
        client = _make_app(no_engine=True)
        resp = client.get("/api/v1/work-items/wi-1/lineage")
        assert resp.status_code == 503

    def test_empty_lineage(self) -> None:
        client = _make_app(
            work_item_store=FakeWorkItemStore(),
            decision_ledger=FakeDecisionLedger(),
            artifact_store=FakeArtifactStore(),
            audit_logger=FakeAuditLogger(),
        )
        resp = client.get("/api/v1/work-items/wi-1/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["work_item_id"] == "wi-1"
        assert data["total_events"] == 0
        assert data["decision_chain_valid"] is True
        assert data["events"] == []

    def test_lineage_with_history(self) -> None:
        item = FakeWorkItem(
            id="wi-1",
            history=[
                FakeHistoryEntry(
                    from_status=WorkItemStatus.PENDING,
                    to_status=WorkItemStatus.IN_PROGRESS,
                    phase_id="phase-1",
                    agent_id="agent-1",
                    reason="started",
                ),
            ],
        )
        client = _make_app(
            work_item_store=FakeWorkItemStore({"wi-1": item}),
            decision_ledger=FakeDecisionLedger(),
            artifact_store=FakeArtifactStore(),
            audit_logger=FakeAuditLogger(),
        )
        resp = client.get("/api/v1/work-items/wi-1/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 1
        event = data["events"][0]
        assert event["source"] == "history"
        assert event["event_type"] == "status_transition"
        assert event["phase_id"] == "phase-1"

    def test_lineage_with_all_sources(self) -> None:
        item = FakeWorkItem(id="wi-1", history=[
            FakeHistoryEntry(
                to_status=WorkItemStatus.IN_PROGRESS,
                reason="started",
            ),
        ])
        decisions = {
            "wi-1": [
                {
                    "timestamp": "2026-01-01T00:00:02Z",
                    "decision_type": "governance_check",
                    "phase_id": "phase-1",
                    "agent_id": "",
                    "decision_id": "dec-1",
                    "outcome": "allow",
                    "confidence": 0.9,
                },
            ],
        }
        artifacts = {
            "wi-1": [FakeArtifact()],
        }
        audit = {
            "wi-1": [
                {
                    "timestamp": "2026-01-01T00:00:03Z",
                    "action": "state_change",
                    "agent_id": "agent-1",
                    "data": {"phase": "phase-1"},
                    "record_type": "STATE_CHANGE",
                    "summary": "completed",
                    "sequence": 1,
                },
            ],
        }
        client = _make_app(
            work_item_store=FakeWorkItemStore({"wi-1": item}),
            decision_ledger=FakeDecisionLedger(decisions),
            artifact_store=FakeArtifactStore(artifacts),
            audit_logger=FakeAuditLogger(audit),
        )
        resp = client.get("/api/v1/work-items/wi-1/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 4
        sources = {e["source"] for e in data["events"]}
        assert sources == {"history", "decision", "artifact", "audit"}

    def test_lineage_all_stores_none(self) -> None:
        """All stores None — graceful degradation."""
        client = _make_app()
        resp = client.get("/api/v1/work-items/wi-1/lineage")
        assert resp.status_code == 200
        assert resp.json()["total_events"] == 0


# ---- Tests: Get Decisions ----


class TestGetDecisions:
    def test_no_engine(self) -> None:
        client = _make_app(no_engine=True)
        resp = client.get("/api/v1/work-items/wi-1/decisions")
        assert resp.status_code == 503

    def test_no_ledger(self) -> None:
        client = _make_app()
        resp = client.get("/api/v1/work-items/wi-1/decisions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decisions"] == []
        assert data["chain_valid"] is True

    def test_with_decisions(self) -> None:
        decisions = {
            "wi-1": [
                {
                    "decision_id": "d-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "decision_type": "governance_check",
                    "outcome": "allow",
                },
            ],
        }
        client = _make_app(decision_ledger=FakeDecisionLedger(decisions, valid=True))
        resp = client.get("/api/v1/work-items/wi-1/decisions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["chain_valid"] is True

    def test_invalid_chain(self) -> None:
        decisions = {"wi-1": [{"decision_id": "d-1"}]}
        client = _make_app(decision_ledger=FakeDecisionLedger(decisions, valid=False))
        resp = client.get("/api/v1/work-items/wi-1/decisions")
        assert resp.status_code == 200
        assert resp.json()["chain_valid"] is False


# ---- Tests: Get Artifacts ----


class TestGetArtifacts:
    def test_no_engine(self) -> None:
        client = _make_app(no_engine=True)
        resp = client.get("/api/v1/work-items/wi-1/artifacts")
        assert resp.status_code == 503

    def test_no_store(self) -> None:
        client = _make_app()
        resp = client.get("/api/v1/work-items/wi-1/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifacts"] == []
        assert data["total"] == 0

    def test_with_artifacts(self) -> None:
        artifacts = {
            "wi-1": [
                FakeArtifact(artifact_id="a-1", phase_id="p-1", agent_id="ag-1"),
                FakeArtifact(artifact_id="a-2", phase_id="p-2", agent_id="ag-2"),
            ],
        }
        client = _make_app(artifact_store=FakeArtifactStore(artifacts))
        resp = client.get("/api/v1/work-items/wi-1/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["artifacts"][0]["artifact_id"] == "a-1"
        assert data["artifacts"][1]["artifact_id"] == "a-2"

    def test_empty_work_item(self) -> None:
        client = _make_app(artifact_store=FakeArtifactStore())
        resp = client.get("/api/v1/work-items/wi-999/artifacts")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
