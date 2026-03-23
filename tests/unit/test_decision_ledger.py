"""Tests for DecisionLedger — cryptographic tamper-evident decision chain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_orchestrator.governance.decision_ledger import (
    DecisionLedger,
    DecisionOutcome,
    DecisionRecord,
    DecisionType,
    _compute_content_hash,
    _compute_record_hash,
)


@pytest.fixture()
def ledger_dir(tmp_path: Path) -> Path:
    """Provide a temp directory for ledger persistence."""
    return tmp_path / "decisions"


@pytest.fixture()
def ledger(ledger_dir: Path) -> DecisionLedger:
    """Create a fresh DecisionLedger."""
    return DecisionLedger(ledger_dir)


class TestRecordDecision:
    """Test recording decisions."""

    def test_basic_record(self, ledger: DecisionLedger) -> None:
        record = ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            agent_id="researcher",
            work_item_id="wi-001",
        )
        assert record.decision_id == "dec-00000001"
        assert record.sequence == 1
        assert record.decision_type == DecisionType.AGENT_EXECUTION
        assert record.outcome == DecisionOutcome.COMPLETED
        assert record.agent_id == "researcher"
        assert record.work_item_id == "wi-001"
        assert record.record_hash != ""
        assert record.previous_hash == ""

    def test_chain_linking(self, ledger: DecisionLedger) -> None:
        r1 = ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
        )
        r2 = ledger.record_decision(
            decision_type=DecisionType.GOVERNANCE_CHECK,
            outcome=DecisionOutcome.APPROVED,
        )
        assert r2.previous_hash == r1.record_hash
        assert r2.sequence == 2

    def test_input_output_hashing(self, ledger: DecisionLedger) -> None:
        record = ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            input_data={"query": "test"},
            output_data={"result": "found"},
        )
        assert record.input_hash != ""
        assert record.output_hash != ""
        # Same input should produce same hash
        expected = _compute_content_hash({"query": "test"})
        assert record.input_hash == expected

    def test_all_fields(self, ledger: DecisionLedger) -> None:
        record = ledger.record_decision(
            decision_type=DecisionType.HUMAN_REVIEW,
            outcome=DecisionOutcome.APPROVED,
            agent_id="agent-1",
            work_item_id="wi-002",
            phase_id="review",
            run_id="run-abc",
            app_id="app-xyz",
            input_data={"doc": "content"},
            output_data={"approved": True},
            reasoning_summary="Meets all criteria",
            tool_calls=["search", "classify"],
            confidence=0.92,
            policy_result="allow",
            policy_id="pol-01",
            warnings=["minor formatting issue"],
            reviewer="alice@example.com",
            review_notes="Looks good",
            duration_seconds=5.3,
            metadata={"source": "api"},
        )
        assert record.reviewer == "alice@example.com"
        assert record.confidence == 0.92
        assert record.tool_calls == ["search", "classify"]
        assert record.warnings == ["minor formatting issue"]

    def test_frozen_record(self, ledger: DecisionLedger) -> None:
        record = ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
        )
        with pytest.raises(AttributeError):
            record.agent_id = "changed"  # type: ignore[misc]


class TestVerifyChain:
    """Test chain verification."""

    def test_empty_ledger(self, ledger: DecisionLedger) -> None:
        valid, count = ledger.verify_chain()
        assert valid is True
        assert count == 0

    def test_valid_chain(self, ledger: DecisionLedger) -> None:
        for i in range(5):
            ledger.record_decision(
                decision_type=DecisionType.AGENT_EXECUTION,
                outcome=DecisionOutcome.COMPLETED,
                agent_id=f"agent-{i}",
            )
        valid, count = ledger.verify_chain()
        assert valid is True
        assert count == 5

    def test_tampered_chain(self, ledger: DecisionLedger, ledger_dir: Path) -> None:
        for i in range(3):
            ledger.record_decision(
                decision_type=DecisionType.AGENT_EXECUTION,
                outcome=DecisionOutcome.COMPLETED,
            )

        # Tamper with the ledger file
        ledger_file = ledger_dir / "decisions.jsonl"
        lines = ledger_file.read_text(encoding="utf-8").strip().split("\n")
        record = json.loads(lines[1])
        record["confidence"] = 999.0  # Tamper!
        record["record_hash"] = "tampered_hash"
        lines[1] = json.dumps(record)
        ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        valid, count = ledger.verify_chain()
        assert valid is False
        assert count == 1  # First record verified, second failed


class TestQuery:
    """Test querying decisions."""

    def test_query_by_work_item(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            work_item_id="wi-001",
        )
        ledger.record_decision(
            decision_type=DecisionType.GOVERNANCE_CHECK,
            outcome=DecisionOutcome.APPROVED,
            work_item_id="wi-002",
        )
        results = ledger.query(work_item_id="wi-001")
        assert len(results) == 1
        assert results[0]["work_item_id"] == "wi-001"

    def test_query_by_agent(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            agent_id="agent-a",
        )
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.FAILED,
            agent_id="agent-b",
        )
        results = ledger.query(agent_id="agent-a")
        assert len(results) == 1

    def test_query_by_type(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
        )
        ledger.record_decision(
            decision_type=DecisionType.GOVERNANCE_CHECK,
            outcome=DecisionOutcome.APPROVED,
        )
        results = ledger.query(decision_type=DecisionType.GOVERNANCE_CHECK)
        assert len(results) == 1
        assert results[0]["decision_type"] == "governance_check"

    def test_query_by_outcome(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
        )
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.FAILED,
        )
        results = ledger.query(outcome=DecisionOutcome.FAILED)
        assert len(results) == 1

    def test_get_decision_chain(self, ledger: DecisionLedger) -> None:
        for i in range(3):
            ledger.record_decision(
                decision_type=DecisionType.AGENT_EXECUTION,
                outcome=DecisionOutcome.COMPLETED,
                work_item_id="wi-chain",
                agent_id=f"agent-{i}",
            )
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            work_item_id="wi-other",
        )
        chain = ledger.get_decision_chain("wi-chain")
        assert len(chain) == 3
        # Chronological order
        assert chain[0]["sequence"] < chain[1]["sequence"] < chain[2]["sequence"]

    def test_get_agent_decisions(self, ledger: DecisionLedger) -> None:
        for i in range(3):
            ledger.record_decision(
                decision_type=DecisionType.AGENT_EXECUTION,
                outcome=DecisionOutcome.COMPLETED,
                agent_id="target-agent",
            )
        decisions = ledger.get_agent_decisions("target-agent")
        assert len(decisions) == 3


class TestPersistence:
    """Test ledger persistence across restarts."""

    def test_persistence(self, ledger_dir: Path) -> None:
        ledger1 = DecisionLedger(ledger_dir)
        r1 = ledger1.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
        )
        r2 = ledger1.record_decision(
            decision_type=DecisionType.GOVERNANCE_CHECK,
            outcome=DecisionOutcome.APPROVED,
        )

        # Create new instance from same dir
        ledger2 = DecisionLedger(ledger_dir)
        r3 = ledger2.record_decision(
            decision_type=DecisionType.QUALITY_GATE,
            outcome=DecisionOutcome.COMPLETED,
        )
        assert r3.sequence == 3
        assert r3.previous_hash == r2.record_hash

        valid, count = ledger2.verify_chain()
        assert valid is True
        assert count == 3


class TestSummary:
    """Test summary statistics."""

    def test_summary(self, ledger: DecisionLedger) -> None:
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            agent_id="a1",
            work_item_id="wi-1",
        )
        ledger.record_decision(
            decision_type=DecisionType.GOVERNANCE_CHECK,
            outcome=DecisionOutcome.APPROVED,
            agent_id="a1",
            work_item_id="wi-1",
        )
        ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.FAILED,
            agent_id="a2",
            work_item_id="wi-2",
        )

        summary = ledger.summary()
        assert summary["total_decisions"] == 3
        assert summary["by_type"]["agent_execution"] == 2
        assert summary["by_type"]["governance_check"] == 1
        assert summary["by_outcome"]["completed"] == 1
        assert summary["by_outcome"]["approved"] == 1
        assert summary["by_outcome"]["failed"] == 1
        assert summary["unique_agents"] == 2
        assert summary["unique_work_items"] == 2


class TestContentHashing:
    """Test content hash functions."""

    def test_deterministic(self) -> None:
        h1 = _compute_content_hash({"a": 1, "b": 2})
        h2 = _compute_content_hash({"b": 2, "a": 1})
        assert h1 == h2  # sort_keys=True

    def test_different_content(self) -> None:
        h1 = _compute_content_hash({"a": 1})
        h2 = _compute_content_hash({"a": 2})
        assert h1 != h2
