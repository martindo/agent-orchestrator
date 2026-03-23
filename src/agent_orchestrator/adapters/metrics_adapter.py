"""Metrics Adapter — Execution metrics collection.

Collects and aggregates metrics from agent executions,
phase transitions, and pipeline processing.

Thread-safe: All public methods use internal lock.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetricEntry:
    """A single metric data point."""

    name: str
    value: float
    tags: dict[str, str] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class MetricsCollector:
    """Collects and persists execution metrics.

    Thread-safe: All public methods use internal lock.
    """

    def __init__(self, metrics_path: Path | None = None) -> None:
        self._metrics: list[MetricEntry] = []
        self._counters: dict[str, float] = {}
        self._path = metrics_path
        self._lock = threading.Lock()

    def record(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Record a metric data point.

        Args:
            name: Metric name (e.g., 'agent.execution_time').
            value: Metric value.
            tags: Optional key-value tags.
        """
        entry = MetricEntry(name=name, value=value, tags=tags or {})
        with self._lock:
            self._metrics.append(entry)
            self._counters[name] = self._counters.get(name, 0) + value

        if self._path:
            self._persist(entry)

    def increment(self, name: str, tags: dict[str, str] | None = None) -> None:
        """Increment a counter metric.

        Args:
            name: Counter name.
            tags: Optional tags.
        """
        self.record(name, 1.0, tags)

    def get_counter(self, name: str) -> float:
        """Get cumulative counter value."""
        with self._lock:
            return self._counters.get(name, 0)

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all metrics."""
        with self._lock:
            return {
                "total_entries": len(self._metrics),
                "counters": dict(self._counters),
            }

    def record_score(
        self,
        work_id: str,
        phase_id: str,
        agent_id: str,
        scores: dict[str, float],
    ) -> None:
        """Record a structured quality score entry.

        Args:
            work_id: Work item ID.
            phase_id: Phase ID.
            agent_id: Agent ID.
            scores: Score dimensions and values.
        """
        entry_data = {
            "type": "quality_score",
            "work_id": work_id,
            "phase_id": phase_id,
            "agent_id": agent_id,
            "scores": scores,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._metrics.append(MetricEntry(
                name="quality_score",
                value=0.0,
                tags={"work_id": work_id, "phase_id": phase_id, "agent_id": agent_id},
            ))
        if self._path:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry_data) + "\n")
            except OSError as e:
                logger.warning("Failed to persist score: %s", e)

    def get_score_history(
        self,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read back quality score entries from the metrics file.

        Args:
            agent_id: Optional filter by agent ID.
            limit: Maximum entries to return.

        Returns:
            List of score entry dicts (newest first).
        """
        if self._path is None or not self._path.exists():
            return []

        results: list[dict[str, Any]] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") != "quality_score":
                        continue
                    if agent_id is not None and data.get("agent_id") != agent_id:
                        continue
                    results.append(data)
        except OSError as e:
            logger.warning("Failed to read score history: %s", e)

        return list(reversed(results[-limit:]))

    def _persist(self, entry: MetricEntry) -> None:
        """Append metric to JSONL file."""
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                data = {
                    "name": entry.name,
                    "value": entry.value,
                    "tags": entry.tags,
                    "timestamp": entry.timestamp,
                }
                f.write(json.dumps(data) + "\n")
        except OSError as e:
            logger.warning("Failed to persist metric: %s", e)
