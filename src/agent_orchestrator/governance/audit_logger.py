"""AuditLogger — Immutable append-only audit trail.

Records governance decisions, state changes, and system events
as hash-chained JSONL entries for tamper detection.

Thread-safe: All public methods use internal lock.

Reuses pattern from decision_os/ledger_core.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from agent_orchestrator.exceptions import PersistenceError

logger = logging.getLogger(__name__)


class RecordType(str, Enum):
    """Types of audit records."""

    DECISION = "decision"
    STATE_CHANGE = "state_change"
    ESCALATION = "escalation"
    ERROR = "error"
    CONFIG_CHANGE = "config_change"
    SYSTEM_EVENT = "system_event"


@dataclass
class AuditRecord:
    """A single audit trail entry."""

    sequence: int
    record_type: RecordType
    action: str
    summary: str
    work_id: str = ""
    agent_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    prev_hash: str = ""
    hash: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class AuditLogger:
    """Append-only hash-chained audit logger.

    Thread-safe: All public methods use internal lock.

    Records are appended to a JSONL file. Each record includes
    the hash of the previous record for chain integrity.
    """

    def __init__(self, audit_dir: Path) -> None:
        self._dir = audit_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path = self._dir / "ledger.jsonl"
        self._lock = threading.Lock()
        self._sequence = 0
        self._last_hash = ""

        # Initialize from existing ledger
        self._load_state()

    def _load_state(self) -> None:
        """Load sequence and last hash from existing ledger."""
        if not self._ledger_path.exists():
            return
        try:
            with open(self._ledger_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        self._sequence = record.get("sequence", 0)
                        self._last_hash = record.get("hash", "")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load audit state: %s", e)

    def append(
        self,
        record_type: RecordType,
        action: str,
        summary: str,
        work_id: str = "",
        agent_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> AuditRecord:
        """Append a record to the audit trail.

        Args:
            record_type: Type of audit record.
            action: Action performed.
            summary: Human-readable summary.
            work_id: Related work item ID.
            agent_id: Related agent ID.
            data: Additional data payload.

        Returns:
            The created AuditRecord.
        """
        with self._lock:
            self._sequence += 1
            record = AuditRecord(
                sequence=self._sequence,
                record_type=record_type,
                action=action,
                summary=summary,
                work_id=work_id,
                agent_id=agent_id,
                data=data or {},
                prev_hash=self._last_hash,
            )
            record.hash = self._compute_hash(record)
            self._last_hash = record.hash

            self._write_record(record)
            return record

    def _compute_hash(self, record: AuditRecord) -> str:
        """Compute SHA-256 hash for chain integrity."""
        data_str = json.dumps({
            "sequence": record.sequence,
            "record_type": record.record_type.value,
            "action": record.action,
            "summary": record.summary,
            "work_id": record.work_id,
            "timestamp": record.timestamp,
            "prev_hash": record.prev_hash,
        }, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]

    def _write_record(self, record: AuditRecord) -> None:
        """Append a record to the JSONL file."""
        record_dict = asdict(record)
        record_dict["record_type"] = record.record_type.value
        try:
            with open(self._ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record_dict) + "\n")
        except OSError as e:
            msg = f"Failed to write audit record: {e}"
            raise PersistenceError(msg) from e

    def query(
        self,
        work_id: str | None = None,
        record_type: RecordType | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query audit records.

        Args:
            work_id: Filter by work item ID.
            record_type: Filter by record type.
            limit: Max records to return.

        Returns:
            List of matching records (newest first).
        """
        with self._lock:
            records: list[dict[str, Any]] = []
            if not self._ledger_path.exists():
                return records

            try:
                with open(self._ledger_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        record = json.loads(line)
                        if work_id and record.get("work_id") != work_id:
                            continue
                        if record_type and record.get("record_type") != record_type.value:
                            continue
                        records.append(record)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Error reading audit log: %s", e)

            return list(reversed(records[-limit:]))

    def verify_chain(self) -> bool:
        """Verify the integrity of the hash chain.

        Returns:
            True if chain is intact.
        """
        with self._lock:
            if not self._ledger_path.exists():
                return True

            prev_hash = ""
            try:
                with open(self._ledger_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        record = json.loads(line)
                        if record.get("prev_hash", "") != prev_hash:
                            logger.error(
                                "Chain broken at sequence %d",
                                record.get("sequence", 0),
                            )
                            return False
                        prev_hash = record.get("hash", "")
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Error verifying chain: %s", e)
                return False

            return True
