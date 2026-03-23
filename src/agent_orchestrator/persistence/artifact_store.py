"""ArtifactStore — Content-addressable file-based artifact storage.

Captures agent inputs and outputs as versioned artifacts, linked to
work items and phases. Uses SHA-256 content hashing for deduplication.

Thread-safe: All public methods use internal lock.
"""

from __future__ import annotations

import hashlib
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


def _compute_hash(content: dict[str, Any]) -> str:
    """Compute SHA-256 hex digest for artifact content."""
    serialized = json.dumps(content, sort_keys=True, default=str).encode()
    return hashlib.sha256(serialized).hexdigest()


@dataclass
class Artifact:
    """Versioned artifact linked to a work item and phase."""

    artifact_id: str
    work_id: str
    phase_id: str
    agent_id: str
    artifact_type: str  # "input", "output", "critic_feedback"
    content_hash: str  # SHA-256 hex of content JSON
    content: dict[str, Any]
    version: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str = ""
    app_id: str = ""


def create_artifact(
    work_id: str,
    phase_id: str,
    agent_id: str,
    artifact_type: str,
    content: dict[str, Any],
    run_id: str = "",
    app_id: str = "",
    version: int = 1,
) -> Artifact:
    """Factory function to create an Artifact with auto-generated ID and hash."""
    return Artifact(
        artifact_id=str(uuid.uuid4()),
        work_id=work_id,
        phase_id=phase_id,
        agent_id=agent_id,
        artifact_type=artifact_type,
        content_hash=_compute_hash(content),
        content=content,
        version=version,
        run_id=run_id,
        app_id=app_id,
    )


class ArtifactStore:
    """File-based content-addressable artifact store.

    Stores artifact content as individual JSON files keyed by SHA-256 hash.
    Maintains a JSONL index for querying artifact metadata.

    Thread-safe: All public methods use internal lock.

    Directory layout::

        base_dir/
          artifacts/
            index.jsonl          — one JSON object per line (metadata)
            {content_hash}.json  — artifact content
    """

    def __init__(self, base_dir: Path) -> None:
        self._artifacts_dir = base_dir / "artifacts"
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._artifacts_dir / "index.jsonl"
        if not self._index_path.exists():
            self._index_path.touch()
        self._lock = threading.Lock()
        logger.debug("ArtifactStore initialized at %s", self._artifacts_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, artifact: Artifact) -> str:
        """Persist an artifact and return its content hash.

        Computes the content hash from the artifact's content, writes the
        content file (skipping if it already exists for deduplication),
        and appends a reference entry to the index.

        Args:
            artifact: The artifact to store.

        Returns:
            The SHA-256 content hash.

        Raises:
            PersistenceError: If writing fails.
        """
        content_hash = _compute_hash(artifact.content)
        artifact.content_hash = content_hash

        if not artifact.artifact_id:
            artifact.artifact_id = str(uuid.uuid4())

        with self._lock:
            try:
                content_path = self._artifacts_dir / f"{content_hash}.json"
                if not content_path.exists():
                    content_path.write_text(
                        json.dumps(artifact.content, sort_keys=True, default=str),
                        encoding="utf-8",
                    )
                    logger.debug("Wrote content file %s", content_path.name)
                else:
                    logger.debug("Content file %s already exists, dedup", content_path.name)

                self._append_index(self._artifact_to_index_entry(artifact))
            except OSError as exc:
                raise PersistenceError(f"Failed to store artifact: {exc}") from exc

        return content_hash

    def get_by_hash(self, content_hash: str) -> Artifact | None:
        """Retrieve an artifact by its content hash.

        Returns the most recent index entry that matches the hash, with
        the content loaded from the content file. Returns ``None`` if no
        matching artifact is found.
        """
        with self._lock:
            entries = self._read_index()

        matching = [e for e in entries if e.get("content_hash") == content_hash]
        if not matching:
            return None

        entry = matching[-1]
        content = self._read_content(content_hash)
        if content is None:
            return None

        return self._entry_to_artifact(entry, content)

    def query(
        self,
        work_id: str | None = None,
        phase_id: str | None = None,
        agent_id: str | None = None,
        artifact_type: str | None = None,
        limit: int = 100,
    ) -> list[Artifact]:
        """Query artifacts by metadata filters.

        Returns matching artifacts sorted newest-first, up to *limit*.
        """
        with self._lock:
            entries = self._read_index()

        filtered: list[dict[str, Any]] = []
        for entry in entries:
            if work_id is not None and entry.get("work_id") != work_id:
                continue
            if phase_id is not None and entry.get("phase_id") != phase_id:
                continue
            if agent_id is not None and entry.get("agent_id") != agent_id:
                continue
            if artifact_type is not None and entry.get("artifact_type") != artifact_type:
                continue
            filtered.append(entry)

        # Newest first
        filtered.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        filtered = filtered[:limit]

        results: list[Artifact] = []
        for entry in filtered:
            content = self._read_content(entry["content_hash"])
            if content is not None:
                results.append(self._entry_to_artifact(entry, content))
        return results

    def get_chain(self, work_id: str) -> list[Artifact]:
        """Return all artifacts for a work item in chronological order."""
        with self._lock:
            entries = self._read_index()

        matching = [e for e in entries if e.get("work_id") == work_id]
        matching.sort(key=lambda e: e.get("timestamp", ""))

        results: list[Artifact] = []
        for entry in matching:
            content = self._read_content(entry["content_hash"])
            if content is not None:
                results.append(self._entry_to_artifact(entry, content))
        return results

    def count(self) -> int:
        """Return total number of artifacts in the index."""
        with self._lock:
            return len(self._read_index())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_index(self) -> list[dict[str, Any]]:
        """Read and parse all entries from the JSONL index file."""
        entries: list[dict[str, Any]] = []
        try:
            text = self._index_path.read_text(encoding="utf-8").strip()
            if not text:
                return entries
            for line in text.splitlines():
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read index: %s", exc, exc_info=True)
        return entries

    def _append_index(self, entry: dict[str, Any]) -> None:
        """Append a single entry to the JSONL index file."""
        with open(self._index_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    def _read_content(self, content_hash: str) -> dict[str, Any] | None:
        """Read content from a content-addressed file."""
        content_path = self._artifacts_dir / f"{content_hash}.json"
        try:
            text = content_path.read_text(encoding="utf-8")
            return json.loads(text)  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read content %s: %s", content_hash, exc, exc_info=True)
            return None

    @staticmethod
    def _artifact_to_index_entry(artifact: Artifact) -> dict[str, Any]:
        """Convert an Artifact to an index entry dict (excludes content)."""
        return {
            "artifact_id": artifact.artifact_id,
            "work_id": artifact.work_id,
            "phase_id": artifact.phase_id,
            "agent_id": artifact.agent_id,
            "artifact_type": artifact.artifact_type,
            "content_hash": artifact.content_hash,
            "version": artifact.version,
            "timestamp": artifact.timestamp.isoformat(),
            "run_id": artifact.run_id,
            "app_id": artifact.app_id,
        }

    @staticmethod
    def _entry_to_artifact(entry: dict[str, Any], content: dict[str, Any]) -> Artifact:
        """Reconstruct an Artifact from an index entry and content dict."""
        timestamp_raw = entry.get("timestamp", "")
        if isinstance(timestamp_raw, str) and timestamp_raw:
            timestamp = datetime.fromisoformat(timestamp_raw)
        else:
            timestamp = datetime.now(timezone.utc)

        return Artifact(
            artifact_id=entry["artifact_id"],
            work_id=entry["work_id"],
            phase_id=entry["phase_id"],
            agent_id=entry["agent_id"],
            artifact_type=entry["artifact_type"],
            content_hash=entry["content_hash"],
            content=content,
            version=entry.get("version", 1),
            timestamp=timestamp,
            run_id=entry.get("run_id", ""),
            app_id=entry.get("app_id", ""),
        )
