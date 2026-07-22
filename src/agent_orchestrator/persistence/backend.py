"""Persistence backend selection — the dispatch point for the tiered
file / sqlite / postgresql persistence infrastructure.

The ``persistence_backend`` setting chooses the tier:

* ``file`` (default) — the in-process, JSON/JSONL file stores. Zero external
  deps; fine for single-process / LITE.
* ``sqlite`` — SQL via SQLAlchemy against a local file DB. Real ACID + SQL
  querying, still zero-ops.
* ``postgresql`` — the same SQL implementation against PostgreSQL, for the
  multi-process STANDARD / ENTERPRISE deployments where in-process file locks
  cannot safely serialize concurrent writers.

The SQL tiers share one implementation (SQLAlchemy Core), so ``sqlite`` and
``postgresql`` differ only by connection URL. Factories fail loud on a
misconfigured SQL backend rather than silently degrading to files.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus

logger = logging.getLogger(__name__)

_SQL_BACKENDS = {"sqlite", "postgresql"}


def _backend_name(settings: Any | None) -> str:
    """Resolve the active backend: AGENT_ORCH_PERSISTENCE_BACKEND env wins
    (so containerized deploys can drive it), else the settings value, else file."""
    env = os.environ.get("AGENT_ORCH_PERSISTENCE_BACKEND")
    if env:
        return env.strip().lower()
    backend = getattr(settings, "persistence_backend", "file")
    return str(getattr(backend, "value", backend)).lower()


@runtime_checkable
class WorkItemStoreProtocol(Protocol):
    """Common interface implemented by both the file and SQL work item stores."""

    def save(self, work_item: WorkItem) -> None: ...

    def load(self, work_id: str) -> WorkItem | None: ...

    def query(
        self,
        *,
        status: WorkItemStatus | None = ...,
        type_id: str | None = ...,
        app_id: str | None = ...,
        run_id: str | None = ...,
        limit: int = ...,
    ) -> list[WorkItem]: ...

    def get_incomplete(self) -> list[WorkItem]: ...

    def summary(self) -> dict[str, Any]: ...


def build_work_item_store(
    settings: Any | None,
    workspace_dir: Path | str,
) -> WorkItemStoreProtocol:
    """Construct the work item store for the configured persistence backend."""
    name = _backend_name(settings)

    if name in _SQL_BACKENDS:
        # Import lazily so the file backend never requires SQLAlchemy/psycopg.
        from agent_orchestrator.persistence.sql.engine import get_engine
        from agent_orchestrator.persistence.sql.work_item_store import SqlWorkItemStore

        engine = get_engine(name, workspace_dir, settings)
        if engine is not None:
            logger.info("Work item store: %s backend", name)
            return SqlWorkItemStore(engine)

    from agent_orchestrator.persistence.work_item_store import WorkItemStore

    return WorkItemStore(workspace_path=str(workspace_dir))


def build_artifact_store(
    settings: Any | None,
    workspace_dir: Path | str,
    file_base_dir: Path | str,
) -> Any:
    """Construct the artifact store for the configured persistence backend.

    ``file_base_dir`` is where the file backend writes (the engine passes its
    ``.state`` dir); the SQL backends ignore it and use the shared engine.
    """
    name = _backend_name(settings)

    if name in _SQL_BACKENDS:
        from agent_orchestrator.persistence.sql.artifact_store import SqlArtifactStore
        from agent_orchestrator.persistence.sql.engine import get_engine

        engine = get_engine(name, workspace_dir, settings)
        if engine is not None:
            logger.info("Artifact store: %s backend", name)
            return SqlArtifactStore(engine)

    from agent_orchestrator.persistence.artifact_store import ArtifactStore

    return ArtifactStore(file_base_dir)
