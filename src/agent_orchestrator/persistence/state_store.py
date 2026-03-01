"""State store — Runtime state persistence (agents, queue, pipeline).

Persists runtime state to .state/ directory as JSON files.
Enables crash recovery and session resumption.

Thread-safe: All public methods use internal lock.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_orchestrator.exceptions import PersistenceError

logger = logging.getLogger(__name__)


class StateStore:
    """File-based runtime state persistence.

    Stores state as JSON files in the workspace .state/ directory.

    Thread-safe: All public methods use internal lock.

    State Ownership: StateStore owns the .state/ directory on disk.
    """

    def __init__(self, state_dir: Path) -> None:
        self._dir = state_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(self, namespace: str, data: Any) -> None:
        """Save state data to a namespaced file.

        Args:
            namespace: State namespace (e.g., 'agents', 'queue', 'pipeline').
            data: JSON-serializable data.

        Raises:
            PersistenceError: If write fails.
        """
        path = self._dir / f"{namespace}.json"
        with self._lock:
            try:
                temp_path = path.with_suffix(f".json.tmp.{os.getpid()}")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)
                if os.name == "nt" and path.exists():
                    os.remove(path)
                os.rename(str(temp_path), str(path))
            except OSError as e:
                msg = f"Failed to save state '{namespace}': {e}"
                raise PersistenceError(msg) from e
            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

    def load(self, namespace: str) -> Any:
        """Load state data from a namespaced file.

        Args:
            namespace: State namespace.

        Returns:
            Parsed JSON data, or None if not found.
        """
        path = self._dir / f"{namespace}.json"
        with self._lock:
            if not path.exists():
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load state '%s': %s", namespace, e)
                return None

    def delete(self, namespace: str) -> bool:
        """Delete a state file.

        Args:
            namespace: State namespace.

        Returns:
            True if file existed and was deleted.
        """
        path = self._dir / f"{namespace}.json"
        with self._lock:
            if path.exists():
                path.unlink()
                return True
            return False

    def list_namespaces(self) -> list[str]:
        """List all saved state namespaces."""
        with self._lock:
            return [
                p.stem for p in self._dir.glob("*.json")
                if not p.name.endswith(".tmp")
            ]

    def clear(self) -> None:
        """Delete all state files."""
        with self._lock:
            for p in self._dir.glob("*.json"):
                p.unlink(missing_ok=True)
            logger.info("Cleared all state from %s", self._dir)
