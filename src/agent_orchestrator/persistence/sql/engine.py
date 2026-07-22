"""Engine creation and connection-URL resolution for SQL backends.

Resolution rules for the database URL:

* ``AGENT_ORCH_DATABASE_URL`` (or ``DATABASE_URL``) always wins when set.
* ``postgresql`` backend: requires one of those env vars — refuses to guess a
  connection (fail loud rather than silently degrade).
* ``sqlite`` backend: defaults to a file under
  ``{workspace}/.agent-orchestrator/state.db`` when no env URL is given.
* ``file`` backend: no engine (returns None).

Engines are cached per-URL and their tables are created on first use
(``metadata.create_all``), so callers can request an engine cheaply.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event

from agent_orchestrator.exceptions import ConfigurationError
from agent_orchestrator.persistence.sql.tables import metadata

logger = logging.getLogger(__name__)

_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()


def _env_url() -> str | None:
    return os.environ.get("AGENT_ORCH_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _normalize_pg_url(url: str) -> str:
    """Force the psycopg (v3) driver so both ``postgres://`` and bare
    ``postgresql://`` URLs resolve to ``postgresql+psycopg://``."""
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def resolve_database_url(
    backend: str,
    workspace_dir: Path | str,
    settings: Any | None = None,
) -> str | None:
    """Resolve the SQLAlchemy URL for a backend, or None for the file backend."""
    name = str(getattr(backend, "value", backend)).lower()
    env = _env_url()

    if name == "postgresql":
        if not env:
            raise ConfigurationError(
                "persistence_backend is 'postgresql' but neither "
                "AGENT_ORCH_DATABASE_URL nor DATABASE_URL is set — refusing to "
                "guess a database connection.",
            )
        return _normalize_pg_url(env)

    if name == "sqlite":
        if env and env.startswith("sqlite"):
            return env
        db_path = Path(workspace_dir) / ".agent-orchestrator" / "state.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.as_posix()}"

    # file (or anything unknown) → no SQL engine
    return None


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # Allow cross-thread use (the engine runs stores from worker threads)
        # and enable WAL so readers don't block the writer.
        eng = create_engine(
            url, future=True, connect_args={"check_same_thread": False},
        )

        @event.listens_for(eng, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001, ANN202
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng

    return create_engine(url, future=True, pool_pre_ping=True)


def get_engine(
    backend: str,
    workspace_dir: Path | str,
    settings: Any | None = None,
) -> Engine | None:
    """Return a cached SQLAlchemy engine for the backend (None for file).

    Tables are created on first use. Raises ConfigurationError for a
    misconfigured postgresql backend (see resolve_database_url).
    """
    url = resolve_database_url(backend, workspace_dir, settings)
    if url is None:
        return None

    with _engines_lock:
        engine = _engines.get(url)
        if engine is None:
            engine = _make_engine(url)
            metadata.create_all(engine)
            _engines[url] = engine
            logger.info("SQL persistence engine ready (%s)", engine.url.render_as_string(hide_password=True))
        return engine


def dispose_all() -> None:
    """Dispose and clear all cached engines (mainly for tests)."""
    with _engines_lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
