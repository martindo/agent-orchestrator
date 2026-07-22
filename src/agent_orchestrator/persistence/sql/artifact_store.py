"""SqlArtifactStore — SQL-backed artifact persistence (SQLite + PostgreSQL).

Implements the same interface as the file-based
:class:`~agent_orchestrator.persistence.artifact_store.ArtifactStore` and reuses
its serialization helpers. Each ``store`` is an append (one row), matching the
file store's JSONL-index semantics; ``get_by_hash`` returns the latest row for a
content hash.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, and_, func, select

from agent_orchestrator.exceptions import PersistenceError
from agent_orchestrator.persistence.artifact_store import (
    Artifact,
    ArtifactStore,
    _compute_hash,
)
from agent_orchestrator.persistence.sql.tables import artifacts

logger = logging.getLogger(__name__)


class SqlArtifactStore:
    """Content-addressable artifact persistence backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def store(self, artifact: Artifact) -> str:
        """Persist an artifact (append) and return its content hash."""
        content_hash = _compute_hash(artifact.content)
        artifact.content_hash = content_hash
        if not artifact.artifact_id:
            artifact.artifact_id = str(uuid.uuid4())

        entry = ArtifactStore._artifact_to_index_entry(artifact)
        row = {
            **entry,
            "timestamp": datetime.fromisoformat(entry["timestamp"]),
            "content": artifact.content,
        }
        try:
            with self._engine.begin() as conn:
                conn.execute(artifacts.insert().values(**row))
        except Exception as exc:
            raise PersistenceError(f"Failed to store artifact: {exc}") from exc
        return content_hash

    @staticmethod
    def _row_to_artifact(row: Any) -> Artifact:
        ts = row["timestamp"]
        entry = {
            "artifact_id": row["artifact_id"],
            "work_id": row["work_id"],
            "phase_id": row["phase_id"],
            "agent_id": row["agent_id"],
            "artifact_type": row["artifact_type"],
            "content_hash": row["content_hash"],
            "version": row["version"],
            "timestamp": ts.isoformat() if ts is not None else "",
            "run_id": row["run_id"],
            "app_id": row["app_id"],
        }
        return ArtifactStore._entry_to_artifact(entry, row["content"])

    def get_by_hash(self, content_hash: str) -> Artifact | None:
        """Return the most recently stored artifact for a content hash."""
        stmt = (
            select(artifacts)
            .where(artifacts.c.content_hash == content_hash)
            .order_by(artifacts.c.row_id.desc())
            .limit(1)
        )
        with self._engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return self._row_to_artifact(row) if row is not None else None

    def query(
        self,
        work_id: str | None = None,
        phase_id: str | None = None,
        agent_id: str | None = None,
        artifact_type: str | None = None,
        limit: int = 100,
    ) -> list[Artifact]:
        """Query artifacts by metadata filters, newest first."""
        conditions = []
        if work_id is not None:
            conditions.append(artifacts.c.work_id == work_id)
        if phase_id is not None:
            conditions.append(artifacts.c.phase_id == phase_id)
        if agent_id is not None:
            conditions.append(artifacts.c.agent_id == agent_id)
        if artifact_type is not None:
            conditions.append(artifacts.c.artifact_type == artifact_type)

        stmt = select(artifacts)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(
            artifacts.c.timestamp.desc(), artifacts.c.row_id.desc()
        ).limit(limit)

        with self._engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [self._row_to_artifact(r) for r in rows]

    def get_chain(self, work_id: str) -> list[Artifact]:
        """Return all artifacts for a work item in chronological order."""
        stmt = (
            select(artifacts)
            .where(artifacts.c.work_id == work_id)
            .order_by(artifacts.c.timestamp.asc(), artifacts.c.row_id.asc())
        )
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [self._row_to_artifact(r) for r in rows]

    def count(self) -> int:
        """Return total number of stored artifact rows."""
        with self._engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(artifacts)).scalar_one()
