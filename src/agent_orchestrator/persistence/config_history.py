"""Config history — Timestamped config version tracking.

Every config save creates a timestamped copy in workspace/.history/.
Provides undo capability and change audit trail.

Thread-safe: All public methods use internal lock.
"""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from agent_orchestrator.exceptions import PersistenceError

logger = logging.getLogger(__name__)

MAX_HISTORY_ENTRIES = 100
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


class ConfigHistory:
    """Maintains timestamped history of configuration changes.

    Thread-safe: All public methods use internal lock.
    """

    def __init__(self, history_dir: Path) -> None:
        self._dir = history_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, source_file: Path, label: str = "") -> Path:
        """Record a configuration file version.

        Creates a timestamped copy of the source file.

        Args:
            source_file: The config file to snapshot.
            label: Optional label for the snapshot.

        Returns:
            Path to the history copy.

        Raises:
            PersistenceError: If source doesn't exist or copy fails.
        """
        if not source_file.exists():
            msg = f"Source file not found: {source_file}"
            raise PersistenceError(msg)

        with self._lock:
            return self._record_unlocked(source_file, label)

    def _record_unlocked(self, source_file: Path, label: str = "") -> Path:
        """Record without acquiring lock (caller must hold lock)."""
        timestamp = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
        suffix = source_file.suffix
        stem = source_file.stem
        label_part = f"_{label}" if label else ""
        dest_name = f"{stem}_{timestamp}{label_part}{suffix}"
        dest_path = self._dir / dest_name

        try:
            shutil.copy2(str(source_file), str(dest_path))
        except OSError as e:
            msg = f"Failed to record config history: {e}"
            raise PersistenceError(msg) from e

        self._prune()
        logger.debug("Recorded config history: %s", dest_name)
        return dest_path

    def list_versions(self, stem_filter: str | None = None) -> list[Path]:
        """List all history versions, newest first.

        Args:
            stem_filter: Optional filter by original filename stem.

        Returns:
            List of history file paths sorted by timestamp (newest first).
        """
        with self._lock:
            entries = sorted(self._dir.iterdir(), reverse=True)
            if stem_filter:
                entries = [e for e in entries if e.name.startswith(stem_filter)]
            return entries

    def restore(self, history_path: Path, target_path: Path) -> None:
        """Restore a config file from a history version.

        Args:
            history_path: Path to the history version.
            target_path: Where to restore it.

        Raises:
            PersistenceError: If history file not found.
        """
        if not history_path.exists():
            msg = f"History file not found: {history_path}"
            raise PersistenceError(msg)

        with self._lock:
            # Record current version before restoring
            if target_path.exists():
                self._record_unlocked(target_path, label="pre_restore")

            try:
                shutil.copy2(str(history_path), str(target_path))
            except OSError as e:
                msg = f"Failed to restore from history: {e}"
                raise PersistenceError(msg) from e

            logger.info("Restored %s from %s", target_path.name, history_path.name)

    def _prune(self) -> None:
        """Remove oldest entries if over MAX_HISTORY_ENTRIES (must hold lock)."""
        entries = sorted(self._dir.iterdir())
        while len(entries) > MAX_HISTORY_ENTRIES:
            oldest = entries.pop(0)
            oldest.unlink(missing_ok=True)
            logger.debug("Pruned old config history: %s", oldest.name)
