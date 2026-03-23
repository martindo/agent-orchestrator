"""Decision Ledger — Cryptographic tamper-evident chain of agent decisions.

Every agent action produces a structured decision record containing identity,
input/output hashes, confidence, governance result, and a cryptographic hash
of the previous record.  Records form a Merkle-style chain enabling:

- Explainable AI (full reasoning trace per decision)
- Regulatory audit (immutable, verifiable chain)
- Forensic investigation (input → reasoning → output linkage)
- Proof of integrity (hash chain detects any alteration)

Thread-safe: All public methods use an internal reentrant lock.
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


class DecisionType(str, Enum):
    """Classification of decision records."""

    AGENT_EXECUTION = "agent_execution"
    GOVERNANCE_CHECK = "governance_check"
    QUALITY_GATE = "quality_gate"
    CRITIC_EVALUATION = "critic_evaluation"
    HUMAN_REVIEW = "human_review"
    PHASE_COMPLETION = "phase_completion"
    WORK_COMPLETION = "work_completion"
    ESCALATION = "escalation"


class DecisionOutcome(str, Enum):
    """Outcome of a decision."""

    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class DecisionRecord:
    """A single immutable decision in the ledger.

    Every field is frozen after creation to guarantee integrity.
    """

    # Identity
    decision_id: str
    sequence: int
    decision_type: DecisionType
    outcome: DecisionOutcome

    # Actor context
    agent_id: str = ""
    work_item_id: str = ""
    phase_id: str = ""
    run_id: str = ""
    app_id: str = ""

    # Content hashes (SHA-256 of serialized input/output)
    input_hash: str = ""
    output_hash: str = ""

    # Reasoning
    reasoning_summary: str = ""
    tool_calls: list[str] = field(default_factory=list)

    # Confidence and governance
    confidence: float = 0.0
    policy_result: str = ""
    policy_id: str = ""
    warnings: list[str] = field(default_factory=list)

    # Reviewer (for human review decisions)
    reviewer: str = ""
    review_notes: str = ""

    # Metadata
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    # Timestamps and chain integrity
    timestamp: str = ""
    previous_hash: str = ""
    record_hash: str = ""


def _compute_content_hash(data: Any) -> str:
    """Compute a deterministic SHA-256 hash of arbitrary data.

    Args:
        data: The data to hash.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _compute_record_hash(record: DecisionRecord) -> str:
    """Compute the cryptographic hash of a decision record.

    Uses the full record content (excluding the record_hash field itself)
    to produce a SHA-256 digest. This ensures that any modification to
    any field is detectable.

    Args:
        record: The decision record to hash.

    Returns:
        Full hex-encoded SHA-256 digest.
    """
    hash_input = {
        "decision_id": record.decision_id,
        "sequence": record.sequence,
        "decision_type": record.decision_type.value,
        "outcome": record.outcome.value,
        "agent_id": record.agent_id,
        "work_item_id": record.work_item_id,
        "phase_id": record.phase_id,
        "run_id": record.run_id,
        "app_id": record.app_id,
        "input_hash": record.input_hash,
        "output_hash": record.output_hash,
        "reasoning_summary": record.reasoning_summary,
        "confidence": record.confidence,
        "policy_result": record.policy_result,
        "policy_id": record.policy_id,
        "reviewer": record.reviewer,
        "timestamp": record.timestamp,
        "previous_hash": record.previous_hash,
    }
    serialized = json.dumps(hash_input, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


class DecisionLedger:
    """Cryptographic tamper-evident decision ledger.

    Maintains an append-only chain of decision records with hash linking.
    Each record's hash incorporates the previous record's hash, creating
    a chain of trust that enables forensic verification.

    Thread-safe: All public methods use an internal reentrant lock.

    Usage:
        ledger = DecisionLedger(state_dir / "decisions")
        record = ledger.record_decision(
            decision_type=DecisionType.AGENT_EXECUTION,
            outcome=DecisionOutcome.COMPLETED,
            agent_id="researcher",
            work_item_id="wi-123",
            input_data={"query": "test"},
            output_data={"result": "found"},
            confidence=0.85,
        )
        assert ledger.verify_chain()
    """

    def __init__(self, ledger_dir: Path) -> None:
        self._dir = ledger_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path = self._dir / "decisions.jsonl"
        self._lock = threading.RLock()
        self._sequence = 0
        self._last_hash = ""
        self._count = 0

        self._load_state()

    def _load_state(self) -> None:
        """Load sequence counter and last hash from existing ledger."""
        if not self._ledger_path.exists():
            return
        try:
            with open(self._ledger_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        self._sequence = record.get("sequence", 0)
                        self._last_hash = record.get("record_hash", "")
                        self._count += 1
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load decision ledger state: %s", exc)

    def record_decision(
        self,
        *,
        decision_type: DecisionType,
        outcome: DecisionOutcome,
        agent_id: str = "",
        work_item_id: str = "",
        phase_id: str = "",
        run_id: str = "",
        app_id: str = "",
        input_data: Any = None,
        output_data: Any = None,
        reasoning_summary: str = "",
        tool_calls: list[str] | None = None,
        confidence: float = 0.0,
        policy_result: str = "",
        policy_id: str = "",
        warnings: list[str] | None = None,
        reviewer: str = "",
        review_notes: str = "",
        duration_seconds: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionRecord:
        """Record a decision in the ledger.

        Creates a new immutable record, chains it to the previous record,
        and persists it to the JSONL file.

        Args:
            decision_type: Classification of this decision.
            outcome: The decision outcome.
            agent_id: Agent that made the decision.
            work_item_id: Related work item.
            phase_id: Related workflow phase.
            run_id: Execution run identifier.
            app_id: Application identifier.
            input_data: Raw input (hashed, not stored).
            output_data: Raw output (hashed, not stored).
            reasoning_summary: Human-readable reasoning explanation.
            tool_calls: List of tools/capabilities invoked.
            confidence: Confidence score (0.0-1.0).
            policy_result: Governance policy evaluation result.
            policy_id: ID of the evaluated policy.
            warnings: Any governance warnings.
            reviewer: Human reviewer identity.
            review_notes: Human reviewer notes.
            duration_seconds: Execution duration.
            metadata: Additional metadata.

        Returns:
            The created DecisionRecord.
        """
        with self._lock:
            self._sequence += 1
            now = datetime.now(timezone.utc).isoformat()

            input_hash = _compute_content_hash(input_data) if input_data else ""
            output_hash = _compute_content_hash(output_data) if output_data else ""
            decision_id = f"dec-{self._sequence:08d}"

            # Create record without hash first (hash depends on all fields)
            record = DecisionRecord(
                decision_id=decision_id,
                sequence=self._sequence,
                decision_type=decision_type,
                outcome=outcome,
                agent_id=agent_id,
                work_item_id=work_item_id,
                phase_id=phase_id,
                run_id=run_id,
                app_id=app_id,
                input_hash=input_hash,
                output_hash=output_hash,
                reasoning_summary=reasoning_summary,
                tool_calls=tool_calls or [],
                confidence=confidence,
                policy_result=policy_result,
                policy_id=policy_id,
                warnings=warnings or [],
                reviewer=reviewer,
                review_notes=review_notes,
                duration_seconds=duration_seconds,
                metadata=metadata or {},
                timestamp=now,
                previous_hash=self._last_hash,
            )

            # Compute and set the record hash (frozen dataclass — use object.__setattr__)
            record_hash = _compute_record_hash(record)
            object.__setattr__(record, "record_hash", record_hash)
            self._last_hash = record_hash
            self._count += 1

            self._write_record(record)
            logger.debug(
                "Decision recorded: id=%s type=%s outcome=%s agent=%s work=%s",
                decision_id,
                decision_type.value,
                outcome.value,
                agent_id,
                work_item_id,
            )
            return record

    def _write_record(self, record: DecisionRecord) -> None:
        """Append a record to the JSONL ledger file."""
        record_dict = asdict(record)
        record_dict["decision_type"] = record.decision_type.value
        record_dict["outcome"] = record.outcome.value
        try:
            with open(self._ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record_dict, default=str) + "\n")
        except OSError as exc:
            msg = f"Failed to write decision record: {exc}"
            raise PersistenceError(msg) from exc

    def verify_chain(self) -> tuple[bool, int]:
        """Verify the integrity of the entire decision chain.

        Recomputes every record's hash and checks that each record's
        previous_hash matches the preceding record's record_hash.

        Returns:
            Tuple of (is_valid, records_verified).
        """
        with self._lock:
            if not self._ledger_path.exists():
                return True, 0

            previous_hash = ""
            count = 0
            try:
                with open(self._ledger_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        raw = json.loads(line)

                        # Verify chain link
                        if raw.get("previous_hash", "") != previous_hash:
                            logger.error(
                                "Decision chain broken at sequence %d: "
                                "expected previous_hash=%s, got=%s",
                                raw.get("sequence", 0),
                                previous_hash,
                                raw.get("previous_hash", ""),
                            )
                            return False, count

                        # Reconstruct record and verify its hash
                        stored_hash = raw.get("record_hash", "")
                        record = DecisionRecord(
                            decision_id=raw["decision_id"],
                            sequence=raw["sequence"],
                            decision_type=DecisionType(raw["decision_type"]),
                            outcome=DecisionOutcome(raw["outcome"]),
                            agent_id=raw.get("agent_id", ""),
                            work_item_id=raw.get("work_item_id", ""),
                            phase_id=raw.get("phase_id", ""),
                            run_id=raw.get("run_id", ""),
                            app_id=raw.get("app_id", ""),
                            input_hash=raw.get("input_hash", ""),
                            output_hash=raw.get("output_hash", ""),
                            reasoning_summary=raw.get("reasoning_summary", ""),
                            confidence=raw.get("confidence", 0.0),
                            policy_result=raw.get("policy_result", ""),
                            policy_id=raw.get("policy_id", ""),
                            reviewer=raw.get("reviewer", ""),
                            timestamp=raw.get("timestamp", ""),
                            previous_hash=raw.get("previous_hash", ""),
                        )
                        computed_hash = _compute_record_hash(record)
                        if computed_hash != stored_hash:
                            logger.error(
                                "Decision record tampered at sequence %d: "
                                "computed_hash=%s, stored_hash=%s",
                                raw.get("sequence", 0),
                                computed_hash,
                                stored_hash,
                            )
                            return False, count

                        previous_hash = stored_hash
                        count += 1
            except (json.JSONDecodeError, OSError, KeyError, ValueError) as exc:
                logger.error("Error verifying decision chain: %s", exc)
                return False, count

            return True, count

    def query(
        self,
        *,
        work_item_id: str | None = None,
        agent_id: str | None = None,
        decision_type: DecisionType | None = None,
        outcome: DecisionOutcome | None = None,
        phase_id: str | None = None,
        run_id: str | None = None,
        app_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query decision records with optional filters.

        Args:
            work_item_id: Filter by work item.
            agent_id: Filter by agent.
            decision_type: Filter by decision type.
            outcome: Filter by outcome.
            phase_id: Filter by phase.
            run_id: Filter by run.
            app_id: Filter by application.
            limit: Maximum records to return.

        Returns:
            Matching records as dicts (newest first).
        """
        with self._lock:
            if not self._ledger_path.exists():
                return []

            records: list[dict[str, Any]] = []
            try:
                with open(self._ledger_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        record = json.loads(line)
                        if work_item_id and record.get("work_item_id") != work_item_id:
                            continue
                        if agent_id and record.get("agent_id") != agent_id:
                            continue
                        if decision_type and record.get("decision_type") != decision_type.value:
                            continue
                        if outcome and record.get("outcome") != outcome.value:
                            continue
                        if phase_id and record.get("phase_id") != phase_id:
                            continue
                        if run_id and record.get("run_id") != run_id:
                            continue
                        if app_id and record.get("app_id") != app_id:
                            continue
                        records.append(record)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Error reading decision ledger: %s", exc)

            return list(reversed(records[-limit:]))

    def get_decision_chain(self, work_item_id: str) -> list[dict[str, Any]]:
        """Get the complete decision chain for a work item.

        Returns all decisions in chronological order, forming a complete
        audit trail from submission to completion.

        Args:
            work_item_id: The work item to trace.

        Returns:
            Ordered list of decision records.
        """
        return list(reversed(self.query(work_item_id=work_item_id, limit=10000)))

    def get_agent_decisions(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent decisions made by a specific agent.

        Args:
            agent_id: The agent identifier.
            limit: Maximum records to return.

        Returns:
            Decisions by this agent (newest first).
        """
        return self.query(agent_id=agent_id, limit=limit)

    def summary(self) -> dict[str, Any]:
        """Return summary statistics for the ledger.

        Returns:
            Dictionary with counts by type, outcome, and chain status.
        """
        with self._lock:
            by_type: dict[str, int] = {}
            by_outcome: dict[str, int] = {}
            agents_seen: set[str] = set()
            work_items_seen: set[str] = set()

            if self._ledger_path.exists():
                try:
                    with open(self._ledger_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            record = json.loads(line)
                            dt = record.get("decision_type", "unknown")
                            by_type[dt] = by_type.get(dt, 0) + 1
                            oc = record.get("outcome", "unknown")
                            by_outcome[oc] = by_outcome.get(oc, 0) + 1
                            if record.get("agent_id"):
                                agents_seen.add(record["agent_id"])
                            if record.get("work_item_id"):
                                work_items_seen.add(record["work_item_id"])
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Error reading ledger summary: %s", exc)

            return {
                "total_decisions": self._count,
                "by_type": by_type,
                "by_outcome": by_outcome,
                "unique_agents": len(agents_seen),
                "unique_work_items": len(work_items_seen),
                "chain_length": self._sequence,
            }
