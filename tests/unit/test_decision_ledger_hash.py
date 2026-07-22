"""Regression tests for the decision-ledger hash coverage (audit 3.3).

The record hash used to enumerate only 18 fields, silently leaving tool_calls,
warnings, review_notes, duration_seconds and metadata outside the chain — they
could be edited without breaking verify_chain, despite the record being
"immutable". These tests lock in that every field participates in the hash.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_orchestrator.governance.decision_ledger import (
    DecisionLedger,
    DecisionOutcome,
    DecisionType,
    _hash_record_dict,
    _record_to_dict,
)


@pytest.fixture
def ledger(tmp_path: Path) -> DecisionLedger:
    return DecisionLedger(tmp_path / "ledger")


def _ledger_file(led: DecisionLedger) -> Path:
    return led._ledger_path  # noqa: SLF001 (test introspection)


def _record_one(led: DecisionLedger) -> None:
    led.record_decision(
        decision_type=DecisionType.AGENT_EXECUTION,
        outcome=DecisionOutcome.COMPLETED,
        agent_id="a1",
        tool_calls=["search", "write"],
        warnings=["low confidence"],
        review_notes="looks fine",
        duration_seconds=1.5,
        metadata={"cost": 0.01},
    )


def _tamper_field(path: Path, index: int, mutate) -> None:
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    record = json.loads(lines[index])
    mutate(record)  # edit a field WITHOUT touching record_hash
    lines[index] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- Every previously-unhashed field is now covered -------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.__setitem__("tool_calls", ["exfiltrate"]),
        lambda r: r.__setitem__("warnings", []),
        lambda r: r.__setitem__("review_notes", "forged approval note"),
        lambda r: r.__setitem__("duration_seconds", 0.0),
        lambda r: r["metadata"].__setitem__("cost", 9999),
    ],
    ids=["tool_calls", "warnings", "review_notes", "duration_seconds", "metadata"],
)
def test_previously_unhashed_field_now_detected(ledger, mutate):
    _record_one(ledger)
    assert ledger.verify_chain()[0] is True
    _tamper_field(_ledger_file(ledger), 0, mutate)
    valid, _ = ledger.verify_chain()
    assert valid is False


def test_valid_chain_still_verifies(ledger):
    for _ in range(3):
        _record_one(ledger)
    valid, count = ledger.verify_chain()
    assert valid is True
    assert count == 3


# ---- Unit-level: the digest reacts to each field ----------------------------


def test_hash_reacts_to_all_mutable_fields():
    base = {
        "decision_id": "d1", "sequence": 1, "decision_type": "agent_execution",
        "outcome": "completed", "agent_id": "", "work_item_id": "", "phase_id": "",
        "run_id": "", "app_id": "", "input_hash": "", "output_hash": "",
        "reasoning_summary": "", "tool_calls": [], "confidence": 0.0,
        "policy_result": "", "policy_id": "", "warnings": [], "reviewer": "",
        "review_notes": "", "duration_seconds": 0.0, "metadata": {},
        "timestamp": "2026-07-22T00:00:00+00:00", "previous_hash": "",
    }
    baseline = _hash_record_dict(base)
    for field, value in [
        ("tool_calls", ["x"]),
        ("warnings", ["w"]),
        ("review_notes", "n"),
        ("duration_seconds", 2.0),
        ("metadata", {"k": "v"}),
    ]:
        assert _hash_record_dict({**base, field: value}) != baseline, field


def test_record_hash_ignores_only_record_hash_field():
    # Two dicts differing only in record_hash must hash identically.
    d = {"sequence": 1, "decision_type": "x", "outcome": "y", "metadata": {}}
    assert _hash_record_dict({**d, "record_hash": "a"}) == _hash_record_dict(
        {**d, "record_hash": "b"}
    )
