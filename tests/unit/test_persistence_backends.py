"""Tests for the tiered persistence infrastructure (file / sqlite / postgresql).

The SQL store tests are parametrized over every available SQL backend: SQLite
always runs (in-process, no server), and PostgreSQL is added automatically when
AGENT_ORCH_DATABASE_URL / DATABASE_URL points at one (CI provides a service
container). The same assertions therefore gate both backends.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("sqlalchemy")  # SQL backends require the `sql` extra

from datetime import datetime, timezone

from agent_orchestrator.core.work_queue import (
    WorkItem,
    WorkItemHistoryEntry,
    WorkItemStatus,
)
from agent_orchestrator.exceptions import ConfigurationError
from agent_orchestrator.persistence.backend import (
    WorkItemStoreProtocol,
    build_work_item_store,
)
from agent_orchestrator.persistence.sql.engine import (
    dispose_all,
    get_engine,
    resolve_database_url,
)
from agent_orchestrator.persistence.sql.tables import work_items
from agent_orchestrator.persistence.sql.work_item_store import SqlWorkItemStore
from agent_orchestrator.persistence.work_item_store import WorkItemStore


def _pg_url() -> str | None:
    url = os.environ.get("AGENT_ORCH_DATABASE_URL") or os.environ.get("DATABASE_URL")
    return url if url and "postgres" in url else None


SQL_BACKENDS = ["sqlite"] + (["postgresql"] if _pg_url() else [])


def _mk(work_id: str, status: str = "pending", *, type_id: str = "task",
        app_id: str = "default", run_id: str = "") -> WorkItem:
    item = WorkItem(id=work_id, type_id=type_id, title=f"Item {work_id}")
    item.status = WorkItemStatus(status)
    item.app_id = app_id
    item.run_id = run_id
    return item


class _FakeSettings:
    def __init__(self, backend: str) -> None:
        self.persistence_backend = backend


# ---- URL resolution ---------------------------------------------------------


def test_file_backend_has_no_url(tmp_path):
    assert resolve_database_url("file", tmp_path) is None


def test_sqlite_url_defaults_under_workspace(tmp_path):
    url = resolve_database_url("sqlite", tmp_path)
    assert url.startswith("sqlite:///")
    assert "state.db" in url


def test_postgresql_requires_env(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_ORCH_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigurationError):
        resolve_database_url("postgresql", tmp_path)


def test_postgresql_normalizes_driver(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ORCH_DATABASE_URL", "postgresql://u:p@h:5432/db")
    assert resolve_database_url("postgresql", tmp_path).startswith("postgresql+psycopg://")


# ---- Backend dispatch -------------------------------------------------------


def test_dispatch_file_returns_file_store(tmp_path):
    store = build_work_item_store(_FakeSettings("file"), tmp_path)
    assert isinstance(store, WorkItemStore)
    assert isinstance(store, WorkItemStoreProtocol)


def test_dispatch_sqlite_returns_sql_store(tmp_path):
    store = build_work_item_store(_FakeSettings("sqlite"), tmp_path)
    assert isinstance(store, SqlWorkItemStore)
    assert isinstance(store, WorkItemStoreProtocol)
    dispose_all()


def test_dispatch_default_is_file(tmp_path):
    store = build_work_item_store(None, tmp_path)  # no settings → file
    assert isinstance(store, WorkItemStore)


# ---- SQL store behaviour (parametrized over every available SQL backend) -----


@pytest.fixture(params=SQL_BACKENDS)
def sql_store(request, tmp_path):
    engine = get_engine(request.param, tmp_path)
    with engine.begin() as conn:  # clean slate (shared DB on postgres)
        conn.execute(work_items.delete())
    yield SqlWorkItemStore(engine)
    with engine.begin() as conn:
        conn.execute(work_items.delete())
    dispose_all()


def test_save_and_load_roundtrip(sql_store):
    item = _mk("w1", "pending", type_id="task", app_id="app-a", run_id="r1")
    sql_store.save(item)
    loaded = sql_store.load("w1")
    assert loaded is not None
    assert loaded.id == "w1"
    assert loaded.type_id == "task"
    assert loaded.app_id == "app-a"
    assert loaded.status == WorkItemStatus.PENDING


def test_load_missing_returns_none(sql_store):
    assert sql_store.load("nope") is None


def test_save_is_upsert(sql_store):
    sql_store.save(_mk("w1", "pending"))
    sql_store.save(_mk("w1", "completed"))  # same id → update, not duplicate
    assert sql_store.load("w1").status == WorkItemStatus.COMPLETED
    assert sql_store.summary()["total"] == 1


def test_query_filters(sql_store):
    sql_store.save(_mk("a", "pending", type_id="task", app_id="x"))
    sql_store.save(_mk("b", "completed", type_id="task", app_id="x"))
    sql_store.save(_mk("c", "pending", type_id="bug", app_id="y"))

    assert {w.id for w in sql_store.query(status=WorkItemStatus.PENDING)} == {"a", "c"}
    assert {w.id for w in sql_store.query(type_id="task")} == {"a", "b"}
    assert {w.id for w in sql_store.query(app_id="y")} == {"c"}
    assert len(sql_store.query(limit=2)) == 2


def test_get_incomplete_excludes_terminal(sql_store):
    sql_store.save(_mk("a", "pending"))
    sql_store.save(_mk("b", "in_progress"))
    sql_store.save(_mk("c", "completed"))
    sql_store.save(_mk("d", "failed"))
    sql_store.save(_mk("e", "cancelled"))
    assert {w.id for w in sql_store.get_incomplete()} == {"a", "b"}


def test_summary_counts(sql_store):
    sql_store.save(_mk("a", "pending", type_id="task"))
    sql_store.save(_mk("b", "pending", type_id="bug"))
    sql_store.save(_mk("c", "completed", type_id="task"))
    summary = sql_store.summary()
    assert summary["total"] == 3
    assert summary["by_status"]["pending"] == 2
    assert summary["by_type"]["task"] == 2


def test_history_survives_roundtrip(sql_store):
    item = _mk("w1", "completed")
    item.history = [
        WorkItemHistoryEntry(
            timestamp=datetime.now(timezone.utc),
            from_status=WorkItemStatus.IN_PROGRESS,
            to_status=WorkItemStatus.COMPLETED,
            phase_id="p1",
            agent_id="agent-1",
            reason="done",
        )
    ]
    sql_store.save(item)
    loaded = sql_store.load("w1")
    assert loaded.status == WorkItemStatus.COMPLETED
    assert len(loaded.history) == 1
    assert loaded.history[0].to_status == WorkItemStatus.COMPLETED
    assert loaded.history[0].reason == "done"
