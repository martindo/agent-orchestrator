"""WorkItem Lineage — unified chronological trace across all data sources.

Joins WorkItem history, DecisionLedger, ArtifactStore, and AuditLogger
into a single ordered timeline for full work-item traceability.

Thread-safe: Delegates to thread-safe underlying stores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LineageEvent:
    """A single event in a work item's lineage timeline."""

    timestamp: str
    source: str       # "history" | "decision" | "artifact" | "audit"
    event_type: str   # e.g. "status_transition", "governance_check", "artifact_stored"
    phase_id: str = ""
    agent_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkItemLineage:
    """Complete lineage for a single work item across all data sources."""

    work_item_id: str
    events: list[LineageEvent] = field(default_factory=list)
    decision_chain_valid: bool = True
    artifact_count: int = 0
    total_events: int = 0


class LineageBuilder:
    """Builds unified lineage from all 4 data sources.

    Thread-safe: Each underlying store is independently thread-safe.
    """

    def __init__(
        self,
        work_item_store: Any,
        decision_ledger: Any,
        artifact_store: Any,
        audit_logger: Any,
    ) -> None:
        self._work_item_store = work_item_store
        self._decision_ledger = decision_ledger
        self._artifact_store = artifact_store
        self._audit_logger = audit_logger

    def build_lineage(self, work_item_id: str) -> WorkItemLineage:
        """Build the complete lineage for a work item.

        Collects events from all 4 sources, merges and sorts chronologically.

        Args:
            work_item_id: The work item to trace.

        Returns:
            Complete WorkItemLineage with all events sorted by timestamp.
        """
        events: list[LineageEvent] = []

        # 1. WorkItem history → LineageEvents
        events.extend(self._collect_history_events(work_item_id))

        # 2. DecisionLedger → LineageEvents
        events.extend(self._collect_decision_events(work_item_id))

        # 3. ArtifactStore → LineageEvents
        artifact_events = self._collect_artifact_events(work_item_id)
        events.extend(artifact_events)

        # 4. AuditLogger → LineageEvents
        events.extend(self._collect_audit_events(work_item_id))

        # Sort chronologically by timestamp
        events.sort(key=lambda e: e.timestamp)

        # Verify decision chain integrity
        chain_valid = self._verify_decision_chain(work_item_id)

        lineage = WorkItemLineage(
            work_item_id=work_item_id,
            events=events,
            decision_chain_valid=chain_valid,
            artifact_count=len(artifact_events),
            total_events=len(events),
        )

        logger.debug(
            "Built lineage for %s: %d events from %d sources",
            work_item_id, len(events),
            len({e.source for e in events}),
        )
        return lineage

    def _collect_history_events(self, work_item_id: str) -> list[LineageEvent]:
        """Collect events from WorkItem.history."""
        if self._work_item_store is None:
            return []
        try:
            item = self._work_item_store.load(work_item_id)
            if item is None:
                return []
            events: list[LineageEvent] = []
            for entry in item.history:
                from_status = entry.from_status.value if entry.from_status else None
                events.append(LineageEvent(
                    timestamp=entry.timestamp.isoformat(),
                    source="history",
                    event_type="status_transition",
                    phase_id=entry.phase_id,
                    agent_id=entry.agent_id,
                    detail={
                        "from_status": from_status,
                        "to_status": entry.to_status.value,
                        "reason": entry.reason,
                    },
                ))
            return events
        except Exception as exc:
            logger.warning("Failed to collect history events for %s: %s", work_item_id, exc)
            return []

    def _collect_decision_events(self, work_item_id: str) -> list[LineageEvent]:
        """Collect events from DecisionLedger."""
        if self._decision_ledger is None:
            return []
        try:
            chain = self._decision_ledger.get_decision_chain(work_item_id)
            events: list[LineageEvent] = []
            for record in chain:
                events.append(LineageEvent(
                    timestamp=record.get("timestamp", ""),
                    source="decision",
                    event_type=record.get("decision_type", "unknown"),
                    phase_id=record.get("phase_id", ""),
                    agent_id=record.get("agent_id", ""),
                    detail={
                        "decision_id": record.get("decision_id", ""),
                        "outcome": record.get("outcome", ""),
                        "confidence": record.get("confidence", 0.0),
                        "policy_result": record.get("policy_result", ""),
                        "policy_id": record.get("policy_id", ""),
                        "reasoning_summary": record.get("reasoning_summary", ""),
                        "duration_seconds": record.get("duration_seconds", 0.0),
                    },
                ))
            return events
        except Exception as exc:
            logger.warning("Failed to collect decision events for %s: %s", work_item_id, exc)
            return []

    def _collect_artifact_events(self, work_item_id: str) -> list[LineageEvent]:
        """Collect events from ArtifactStore."""
        if self._artifact_store is None:
            return []
        try:
            artifacts = self._artifact_store.get_chain(work_item_id)
            events: list[LineageEvent] = []
            for artifact in artifacts:
                ts = artifact.timestamp
                timestamp_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                events.append(LineageEvent(
                    timestamp=timestamp_str,
                    source="artifact",
                    event_type="artifact_stored",
                    phase_id=artifact.phase_id,
                    agent_id=artifact.agent_id,
                    detail={
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        "content_hash": artifact.content_hash,
                        "version": artifact.version,
                    },
                ))
            return events
        except Exception as exc:
            logger.warning("Failed to collect artifact events for %s: %s", work_item_id, exc)
            return []

    def _collect_audit_events(self, work_item_id: str) -> list[LineageEvent]:
        """Collect events from AuditLogger."""
        if self._audit_logger is None:
            return []
        try:
            records = self._audit_logger.query(work_id=work_item_id, limit=10000)
            events: list[LineageEvent] = []
            for record in records:
                events.append(LineageEvent(
                    timestamp=record.get("timestamp", ""),
                    source="audit",
                    event_type=record.get("action", ""),
                    phase_id=record.get("data", {}).get("phase", ""),
                    agent_id=record.get("agent_id", ""),
                    detail={
                        "record_type": record.get("record_type", ""),
                        "action": record.get("action", ""),
                        "summary": record.get("summary", ""),
                        "sequence": record.get("sequence", 0),
                    },
                ))
            return events
        except Exception as exc:
            logger.warning("Failed to collect audit events for %s: %s", work_item_id, exc)
            return []

    def _verify_decision_chain(self, work_item_id: str) -> bool:
        """Verify the decision ledger chain integrity."""
        if self._decision_ledger is None:
            return True
        try:
            valid, _count = self._decision_ledger.verify_chain()
            return valid
        except Exception:
            return False
