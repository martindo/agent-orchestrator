"""Tamper-evidence tests for the AuditLogger hash chain (audit 3.2).

These lock in the properties the "immutable, tamper-evident audit trail" claim
requires: the full record (including the data payload) is hashed with a full
SHA-256 digest, verify_chain recomputes hashes to detect edits, and the chain
survives rotation instead of being severed.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_orchestrator.governance.audit_logger import AuditLogger, RecordType


def _ledger(dir_: Path) -> Path:
    return dir_ / "ledger.jsonl"


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_lines(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8",
    )


# ---- Hash strength ----------------------------------------------------------


def test_hash_is_full_sha256(tmp_path):
    audit = AuditLogger(tmp_path / ".audit")
    r = audit.append(RecordType.DECISION, "approve", "hi")
    assert len(r.hash) == 64  # full 256-bit digest, not truncated to 16


def test_data_payload_participates_in_hash():
    """The data payload must be part of the digest (it was omitted before)."""
    base = {
        "sequence": 1, "record_type": "decision", "action": "act", "summary": "s",
        "work_id": "", "agent_id": "", "app_id": "", "run_id": "",
        "data": {"amount": 100}, "timestamp": "2026-07-22T00:00:00+00:00",
        "prev_hash": "",
    }
    forged = {**base, "data": {"amount": 999}}
    assert AuditLogger._digest_dict(base) != AuditLogger._digest_dict(forged)


# ---- verify_chain detects tampering -----------------------------------------


def test_valid_chain_verifies(tmp_path):
    audit = AuditLogger(tmp_path / ".audit")
    for i in range(5):
        audit.append(RecordType.DECISION, "approve", f"rec {i}", data={"i": i})
    assert audit.verify_chain() is True


def test_tampering_with_data_payload_is_detected(tmp_path):
    """THE core fix: editing the data payload must break verification."""
    adir = tmp_path / ".audit"
    audit = AuditLogger(adir)
    audit.append(RecordType.DECISION, "approve", "loan", data={"amount": 100})
    audit.append(RecordType.DECISION, "approve", "next", data={"x": 1})
    assert audit.verify_chain() is True

    records = _read_lines(_ledger(adir))
    records[0]["data"]["amount"] = 1_000_000  # forge the payload, keep hashes
    _write_lines(_ledger(adir), records)

    assert AuditLogger(adir).verify_chain() is False


def test_tampering_with_field_is_detected(tmp_path):
    adir = tmp_path / ".audit"
    audit = AuditLogger(adir)
    audit.append(RecordType.DECISION, "approve", "original summary")
    records = _read_lines(_ledger(adir))
    records[0]["summary"] = "edited summary"
    _write_lines(_ledger(adir), records)
    assert AuditLogger(adir).verify_chain() is False


def test_reordering_records_is_detected(tmp_path):
    adir = tmp_path / ".audit"
    audit = AuditLogger(adir)
    audit.append(RecordType.DECISION, "a", "first")
    audit.append(RecordType.DECISION, "b", "second")
    records = _read_lines(_ledger(adir))
    _write_lines(_ledger(adir), list(reversed(records)))  # break linkage
    assert AuditLogger(adir).verify_chain() is False


def test_deleting_a_record_is_detected(tmp_path):
    adir = tmp_path / ".audit"
    audit = AuditLogger(adir)
    audit.append(RecordType.DECISION, "a", "first")
    audit.append(RecordType.DECISION, "b", "second")
    audit.append(RecordType.DECISION, "c", "third")
    records = _read_lines(_ledger(adir))
    del records[1]  # drop the middle record
    _write_lines(_ledger(adir), records)
    assert AuditLogger(adir).verify_chain() is False


# ---- Rotation preserves the chain -------------------------------------------


def test_chain_survives_rotation(tmp_path):
    adir = tmp_path / ".audit"
    # Tiny cap forces a rotation on nearly every append.
    audit = AuditLogger(adir, max_file_bytes=200)
    first = audit.append(RecordType.DECISION, "a", "first", data={"n": 0})
    for i in range(1, 6):
        audit.append(RecordType.DECISION, "x", f"rec {i}", data={"n": i})

    rotated = list(adir.glob("ledger.*.jsonl"))
    assert rotated, "expected at least one rotated segment"
    # First record of the active file must chain to the previous segment,
    # not restart from an empty genesis.
    active = _read_lines(_ledger(adir))
    assert active[0]["prev_hash"] != ""
    assert audit.verify_chain() is True
    assert first.prev_hash == ""  # genesis is still the very first record


def test_tampering_in_rotated_segment_is_detected(tmp_path):
    adir = tmp_path / ".audit"
    audit = AuditLogger(adir, max_file_bytes=200)
    for i in range(6):
        audit.append(RecordType.DECISION, "x", f"rec {i}", data={"n": i})

    rotated = sorted(adir.glob("ledger.*.jsonl"))
    assert rotated
    seg = _read_lines(rotated[0])
    seg[0]["summary"] = "tampered in rotated file"
    _write_lines(rotated[0], seg)

    assert AuditLogger(adir).verify_chain() is False


def test_dropping_a_rotated_segment_is_detected(tmp_path):
    adir = tmp_path / ".audit"
    audit = AuditLogger(adir, max_file_bytes=200)
    for i in range(6):
        audit.append(RecordType.DECISION, "x", f"rec {i}", data={"n": i})

    rotated = sorted(adir.glob("ledger.*.jsonl"))
    assert rotated
    rotated[0].unlink()  # remove the oldest segment entirely

    # The next segment's first record now dangles (prev_hash points at a record
    # that no longer exists), so verification fails.
    assert AuditLogger(adir).verify_chain() is False
