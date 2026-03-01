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
