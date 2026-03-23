"""Eval Dataset Management — persist and manage reusable evaluation datasets.

Provides a DatasetStore for CRUD operations on EvalDataset instances,
backed by JSONL persistence.

Thread-safe: All public methods use internal lock.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_orchestrator.exceptions import PersistenceError

logger = logging.getLogger(__name__)


@dataclass
class EvalDataset:
    """A reusable evaluation dataset — a snapshot of work items."""

    dataset_id: str
    name: str
    description: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    tags: list[str] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "description": self.description,
            "items": self.items,
            "created_at": self.created_at,
            "tags": self.tags,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalDataset:
        """Deserialize from a dict."""
        return cls(
            dataset_id=data["dataset_id"],
            name=data["name"],
            description=data.get("description", ""),
            items=data.get("items", []),
            created_at=data.get("created_at", ""),
            tags=data.get("tags", []),
            version=data.get("version", 1),
        )


class DatasetStore:
    """JSONL-backed persistence for evaluation datasets.

    File layout::

        {persistence_dir}/datasets.jsonl

    Each line is a full JSON snapshot. On load, latest entry per
    dataset_id wins (upsert semantics).

    Thread-safe: All public methods use internal lock.
    """

    def __init__(self, persistence_dir: Path) -> None:
        self._dir = persistence_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "datasets.jsonl"
        if not self._file.exists():
            self._file.touch()
        self._lock = threading.Lock()
        logger.debug("DatasetStore initialized at %s", self._dir)

    def save_dataset(self, dataset: EvalDataset) -> None:
        """Persist a dataset to the JSONL store.

        Args:
            dataset: The dataset to save.

        Raises:
            PersistenceError: On I/O failure.
        """
        record = dataset.to_dict()
        with self._lock:
            try:
                with open(self._file, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            except OSError as exc:
                raise PersistenceError(f"Failed to save dataset: {exc}") from exc
        logger.debug("Saved dataset %s", dataset.dataset_id)

    def load_dataset(self, dataset_id: str) -> EvalDataset | None:
        """Load a dataset by ID.

        Args:
            dataset_id: The dataset identifier.

        Returns:
            The dataset, or None if not found.
        """
        with self._lock:
            latest = self._load_datasets_map()
        record = latest.get(dataset_id)
        if record is None:
            return None
        return EvalDataset.from_dict(record)

    def list_datasets(self) -> list[EvalDataset]:
        """List all datasets.

        Returns:
            All datasets, newest first by created_at.
        """
        with self._lock:
            latest = self._load_datasets_map()
        datasets = [EvalDataset.from_dict(r) for r in latest.values()]
        datasets.sort(key=lambda d: d.created_at, reverse=True)
        return datasets

    def delete_dataset(self, dataset_id: str) -> bool:
        """Delete a dataset by rewriting the JSONL without it.

        Args:
            dataset_id: The dataset to delete.

        Returns:
            True if found and deleted, False otherwise.

        Raises:
            PersistenceError: On I/O failure.
        """
        with self._lock:
            latest = self._load_datasets_map()
            if dataset_id not in latest:
                return False
            del latest[dataset_id]
            try:
                with open(self._file, "w", encoding="utf-8") as fh:
                    for record in latest.values():
                        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            except OSError as exc:
                raise PersistenceError(f"Failed to delete dataset: {exc}") from exc
        logger.debug("Deleted dataset %s", dataset_id)
        return True

    def create_from_work_items(
        self,
        name: str,
        items: list[dict[str, Any]],
        description: str = "",
        tags: list[str] | None = None,
    ) -> EvalDataset:
        """Create a dataset from a list of work item dicts.

        Snapshots the items into a reusable dataset and persists it.

        Args:
            name: Dataset name.
            items: Work item dicts to snapshot.
            description: Optional description.
            tags: Optional tags.

        Returns:
            The created and persisted EvalDataset.
        """
        dataset = EvalDataset(
            dataset_id=f"ds-{uuid.uuid4().hex[:8]}",
            name=name,
            description=description or f"Created from {len(items)} work items",
            items=items,
            tags=tags or [],
        )
        self.save_dataset(dataset)
        logger.info(
            "Created dataset %s with %d items",
            dataset.dataset_id, len(items),
        )
        return dataset

    def _load_datasets_map(self) -> dict[str, dict[str, Any]]:
        """Read all dataset lines, keeping latest entry per dataset_id.

        Returns:
            Map of dataset_id -> latest record dict.
        """
        datasets: dict[str, dict[str, Any]] = {}
        try:
            text = self._file.read_text(encoding="utf-8").strip()
            if not text:
                return datasets
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                datasets[record["dataset_id"]] = record
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read datasets: %s", exc, exc_info=True)
        return datasets
