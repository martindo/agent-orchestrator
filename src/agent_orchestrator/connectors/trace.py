"""Connector execution trace store — thread-safe in-memory ring buffer."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .models import CapabilityType, ConnectorCostInfo, ConnectorStatus


class ConnectorExecutionTrace(BaseModel, frozen=True):
    """Full execution trace for a single connector invocation."""

    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    run_id: str | None = None
    workflow_id: str | None = None
    module_name: str | None = None
    agent_role: str | None = None
    connector_id: str
    provider: str
    capability_type: CapabilityType
    operation: str
    parameter_keys: list[str] = Field(default_factory=list)
    status: ConnectorStatus
    duration_ms: float | None = None
    cost_info: ConnectorCostInfo | None = None
    error_message: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    attempt_number: int = 1


class ConnectorTraceStore:
    """Thread-safe ring-buffer store for connector execution traces.

    Keeps up to max_entries traces (oldest evicted first).
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._lock = threading.Lock()
        self._traces: list[ConnectorExecutionTrace] = []
        self._max_entries = max_entries

    def record(self, trace: ConnectorExecutionTrace) -> None:
        """Add a trace to the store, evicting oldest if at capacity."""
        with self._lock:
            self._traces.append(trace)
            if len(self._traces) > self._max_entries:
                self._traces = self._traces[-self._max_entries:]

    def query(
        self,
        run_id: str | None = None,
        connector_id: str | None = None,
        capability_type: CapabilityType | None = None,
        limit: int = 100,
    ) -> list[ConnectorExecutionTrace]:
        """Query traces with optional filters, newest first.

        Args:
            run_id: Filter by run ID.
            connector_id: Filter by connector ID.
            capability_type: Filter by capability type.
            limit: Maximum number of results to return.

        Returns:
            List of matching traces, newest first.
        """
        with self._lock:
            results = list(reversed(self._traces))
        if run_id:
            results = [t for t in results if t.run_id == run_id]
        if connector_id:
            results = [t for t in results if t.connector_id == connector_id]
        if capability_type:
            results = [t for t in results if t.capability_type == capability_type]
        return results[:limit]

    def get_summary(self) -> dict:
        """Return aggregated counts by status and capability type."""
        with self._lock:
            total = len(self._traces)
            by_status: dict[str, int] = {}
            by_capability: dict[str, int] = {}
            for t in self._traces:
                by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
                by_capability[t.capability_type.value] = (
                    by_capability.get(t.capability_type.value, 0) + 1
                )
        return {
            "total_traces": total,
            "by_status": by_status,
            "by_capability": by_capability,
        }
