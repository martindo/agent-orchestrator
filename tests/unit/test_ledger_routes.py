"""Tests for decision ledger REST API routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_orchestrator.api.ledger_routes import ledger_router
from agent_orchestrator.governance.decision_ledger import (
    DecisionLedger,
    DecisionOutcome,
    DecisionType,
)


@pytest.fixture()
def ledger(tmp_path: Path) -> DecisionLedger:
    return DecisionLedger(tmp_path / "decisions")


def _make_app(ledger: DecisionLedger | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(ledger_router, prefix="/api/v1")
    if ledger is not None:
        mock_engine = MagicMock()
        mock_engine.decision_ledger = ledger
        app.state.engine = mock_engine
    else:
        app.state.engine = None
    return TestClient(app)


class TestQueryDecisions:
    def test_query_all(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            agent_id="a1",
        )
        client = _make_app(ledger)
        resp = client.get("/api/v1/ledger/decisions")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_query_by_agent(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            agent_id="target",
        )
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            agent_id="other",
        )
        client = _make_app(ledger)
        resp = client.get("/api/v1/ledger/decisions", params={"agent_id": "target"})
        assert len(resp.json()) == 1

    def test_no_engine(self) -> None:
        client = _make_app()
        resp = client.get("/api/v1/ledger/decisions")
        assert resp.status_code == 503

    def test_invalid_decision_type(self, ledger: DecisionLedger) -> None:
        client = _make_app(ledger)
        resp = client.get("/api/v1/ledger/decisions", params={"decision_type": "invalid"})
        assert resp.status_code == 400


class TestDecisionChain:
    def test_chain(self, ledger: DecisionLedger) -> None:
        for i in range(3):
            ledger.record_decision(
                decision_type=DecisionType.AGENT_EXECUTION,
                outcome=DecisionOutcome.COMPLETED,
                work_item_id="wi-chain",
            )
        client = _make_app(ledger)
        resp = client.get("/api/v1/ledger/decisions/chain/wi-chain")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_chain_not_found(self, ledger: DecisionLedger) -> None:
        client = _make_app(ledger)
        resp = client.get("/api/v1/ledger/decisions/chain/missing")
        assert resp.status_code == 404


class TestVerify:
    def test_verify_intact(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
        )
        client = _make_app(ledger)
        resp = client.get("/api/v1/ledger/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain_valid"] is True
        assert data["status"] == "intact"


class TestSummary:
    def test_summary(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
        )
        client = _make_app(ledger)
        resp = client.get("/api/v1/ledger/summary")
        assert resp.status_code == 200
        assert resp.json()["total_decisions"] == 1
