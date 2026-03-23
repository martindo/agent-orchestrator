"""WorkItemStore — JSONL-backed persistence for work items.

Follows the same JSONL persistence pattern used by AuditLogger and
ArtifactStore. Supports save, load, query, and crash-recovery operations.

Thread-safe: All public methods use internal lock.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_orchestrator.core.work_queue import (
    TERMINAL_STATUSES,
    WorkItem,
    WorkItemHistoryEntry,
    WorkItemStatus,
)
from agent_orchestrator.exceptions import PersistenceError

logger = logging.getLogger(__name__)


def _work_item_to_dict(item: WorkItem) -> dict[str, Any]:
    """Serialize a WorkItem (including history) to a JSON-safe dict."""
    history_entries = []
    for entry in item.history:
        history_entries.append({
            "timestamp": entry.timestamp.isoformat(),
            "from_status": entry.from_status.value if entry.from_status else None,
            "to_status": entry.to_status.value,
            "phase_id": entry.phase_id,
            "agent_id": entry.agent_id,
            "reason": entry.reason,
            "metadata": entry.metadata,
        })

    return {
        "id": item.id,
        "type_id": item.type_id,
        "title": item.title,
        "data": item.data,
        "priority": item.priority,
        "status": item.status.value,
        "run_id": item.run_id,
        "app_id": item.app_id,
        "current_phase": item.current_phase,
        "submitted_at": item.submitted_at.isoformat(),
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "metadata": item.metadata,
        "results": item.results,
        "error": item.error,
        "attempt_count": item.attempt_count,
        "history": history_entries,
        "deadline": item.deadline.isoformat() if item.deadline else None,
        "urgency": item.urgency,
        "sla_policy_id": item.sla_policy_id,
        "routing_tags": item.routing_tags,
    }


def _dict_to_work_item(d: dict[str, Any]) -> WorkItem:
    """Deserialize a dict back into a WorkItem with history."""
    history_entries: list[WorkItemHistoryEntry] = []
    for h in d.get("history", []):
        from_raw = h.get("from_status")
        history_entries.append(WorkItemHistoryEntry(
            timestamp=datetime.fromisoformat(h["timestamp"]),
            from_status=WorkItemStatus(from_raw) if from_raw else None,
            to_status=WorkItemStatus(h["to_status"]),
            phase_id=h.get("phase_id", ""),
            agent_id=h.get("agent_id", ""),
            reason=h.get("reason", ""),
            metadata=h.get("metadata", {}),
        ))

    def _parse_dt(val: str | None) -> datetime | None:
        if val is None:
            return None
        return datetime.fromisoformat(val)

    item = object.__new__(WorkItem)
    item.id = d["id"]
    item.type_id = d["type_id"]
    item.title = d["title"]
    item.data = d.get("data", {})
    item.priority = d.get("priority", 5)
    item.status = WorkItemStatus(d["status"])
    item.run_id = d.get("run_id", "")
    item.app_id = d.get("app_id", "default")
    item.current_phase = d.get("current_phase", "")
    item.submitted_at = datetime.fromisoformat(d["submitted_at"])
    item.started_at = _parse_dt(d.get("started_at"))
    item.completed_at = _parse_dt(d.get("completed_at"))
    item.metadata = d.get("metadata", {})
    item.results = d.get("results", {})
    item.error = d.get("error")
    item.attempt_count = d.get("attempt_count", 0)
    item.history = history_entries
    item.deadline = _parse_dt(d.get("deadline"))
    item.urgency = d.get("urgency", "")
    item.sla_policy_id = d.get("sla_policy_id", "")
    item.routing_tags = d.get("routing_tags", [])
    return item


class WorkItemStore:
    """JSONL-backed work item persistence.

    File layout::

        {workspace}/.agent-orchestrator/work_items.jsonl

    Each line is a full JSON snapshot of a WorkItem (upsert semantics —
    latest line for a given ID wins on load).

    Thread-safe: All public methods use internal lock.
    """

    def __init__(self, workspace_path: str = "") -> None:
        base = Path(workspace_path) if workspace_path else Path.cwd()
        self._dir = base / ".agent-orchestrator"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "work_items.jsonl"
        if not self._file.exists():
            self._file.touch()
        self._lock = threading.Lock()
        logger.debug("WorkItemStore initialized at %s", self._file)

    def save(self, work_item: WorkItem) -> None:
        """Append a work item snapshot to the persistent store."""
        record = _work_item_to_dict(work_item)
        with self._lock:
            try:
                with open(self._file, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            except OSError as exc:
                raise PersistenceError(f"Failed to save work item: {exc}") from exc

    def _load_latest_map(self) -> dict[str, dict[str, Any]]:
        """Read all lines and keep only the latest entry per work item ID."""
        items: dict[str, dict[str, Any]] = {}
        try:
            text = self._file.read_text(encoding="utf-8").strip()
            if not text:
                return items
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                items[record["id"]] = record
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read work items: %s", exc, exc_info=True)
        return items

    def load(self, work_id: str) -> WorkItem | None:
        """Load a specific work item by ID (latest snapshot)."""
        with self._lock:
            latest = self._load_latest_map()
        record = latest.get(work_id)
        if record is None:
            return None
        return _dict_to_work_item(record)

    def query(
        self,
        *,
        status: WorkItemStatus | None = None,
        type_id: str | None = None,
        app_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[WorkItem]:
        """Query work items with optional filters."""
        with self._lock:
            latest = self._load_latest_map()

        results: list[WorkItem] = []
        for record in latest.values():
            if status is not None and record.get("status") != status.value:
                continue
            if type_id is not None and record.get("type_id") != type_id:
                continue
            if app_id is not None and record.get("app_id") != app_id:
                continue
            if run_id is not None and record.get("run_id") != run_id:
                continue
            results.append(_dict_to_work_item(record))

        # Sort by submitted_at descending (most recent first)
        results.sort(key=lambda w: w.submitted_at, reverse=True)
        return results[:limit]

    def get_incomplete(self) -> list[WorkItem]:
        """Get all non-terminal work items (for crash recovery)."""
        with self._lock:
            latest = self._load_latest_map()

        results: list[WorkItem] = []
        for record in latest.values():
            if record.get("status") not in TERMINAL_STATUSES:
                results.append(_dict_to_work_item(record))

        results.sort(key=lambda w: w.submitted_at)
        return results

    def summary(self) -> dict[str, Any]:
        """Return counts by status, type, and recent activity."""
        with self._lock:
            latest = self._load_latest_map()

        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        total = len(latest)

        for record in latest.values():
            s = record.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
            t = record.get("type_id", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
        }
