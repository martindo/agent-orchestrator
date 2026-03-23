"""Tests for WorkItemStore JSONL persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus
from agent_orchestrator.persistence.work_item_store import WorkItemStore


@pytest.fixture
def store(tmp_path: Path) -> WorkItemStore:
    return WorkItemStore(workspace_path=str(tmp_path))


def _make_item(
    id: str = "w1",
    type_id: str = "test",
    status: WorkItemStatus = WorkItemStatus.PENDING,
    app_id: str = "default",
    run_id: str = "run1",
) -> WorkItem:
    item = WorkItem(id=id, type_id=type_id, title=f"Item {id}", app_id=app_id, run_id=run_id)
    if status != WorkItemStatus.PENDING:
        item.record_transition(status, reason="test setup")
    return item


# ---- Save & Load ----


def test_save_and_load(store: WorkItemStore) -> None:
    item = _make_item()
    store.save(item)
    loaded = store.load("w1")
    assert loaded is not None
    assert loaded.id == "w1"
    assert loaded.type_id == "test"
    assert loaded.title == "Item w1"
    assert loaded.status == WorkItemStatus.PENDING


def test_load_nonexistent(store: WorkItemStore) -> None:
    assert store.load("nonexistent") is None


def test_save_preserves_history(store: WorkItemStore) -> None:
    item = _make_item()
    item.record_transition(WorkItemStatus.QUEUED, reason="enqueued")
    item.record_transition(WorkItemStatus.IN_PROGRESS, reason="dequeued")
    store.save(item)

    loaded = store.load("w1")
    assert loaded is not None
    assert len(loaded.history) == 3
    assert loaded.history[0].to_status == WorkItemStatus.PENDING
    assert loaded.history[1].to_status == WorkItemStatus.QUEUED
    assert loaded.history[2].to_status == WorkItemStatus.IN_PROGRESS
    assert loaded.history[1].reason == "enqueued"


def test_save_upsert_semantics(store: WorkItemStore) -> None:
    """Saving the same item twice should return the latest version on load."""
    item = _make_item()
    store.save(item)

    item.record_transition(WorkItemStatus.QUEUED, reason="q")
    store.save(item)

    loaded = store.load("w1")
    assert loaded is not None
    assert loaded.status == WorkItemStatus.QUEUED


def test_preserves_timestamps(store: WorkItemStore) -> None:
    item = _make_item()
    item.record_transition(WorkItemStatus.IN_PROGRESS, reason="ip")
    item.record_transition(WorkItemStatus.COMPLETED, reason="done")
    store.save(item)

    loaded = store.load("w1")
    assert loaded is not None
    assert loaded.submitted_at is not None
    assert loaded.started_at is not None
    assert loaded.completed_at is not None


def test_preserves_error(store: WorkItemStore) -> None:
    item = _make_item()
    item.record_transition(WorkItemStatus.FAILED, reason="boom")
    item.error = "something went wrong"
    store.save(item)

    loaded = store.load("w1")
    assert loaded is not None
    assert loaded.error == "something went wrong"


# ---- Query ----


def test_query_by_status(store: WorkItemStore) -> None:
    store.save(_make_item("w1"))
    completed = _make_item("w2")
    completed.record_transition(WorkItemStatus.QUEUED, reason="q")
    completed.record_transition(WorkItemStatus.IN_PROGRESS, reason="ip")
    completed.record_transition(WorkItemStatus.COMPLETED, reason="done")
    store.save(completed)

    results = store.query(status=WorkItemStatus.COMPLETED)
    assert len(results) == 1
    assert results[0].id == "w2"


def test_query_by_type(store: WorkItemStore) -> None:
    store.save(_make_item("w1", type_id="alpha"))
    store.save(_make_item("w2", type_id="beta"))

    results = store.query(type_id="alpha")
    assert len(results) == 1
    assert results[0].id == "w1"


def test_query_by_app_id(store: WorkItemStore) -> None:
    store.save(_make_item("w1", app_id="app1"))
    store.save(_make_item("w2", app_id="app2"))

    results = store.query(app_id="app1")
    assert len(results) == 1
    assert results[0].id == "w1"


def test_query_by_run_id(store: WorkItemStore) -> None:
    store.save(_make_item("w1", run_id="r1"))
    store.save(_make_item("w2", run_id="r2"))

    results = store.query(run_id="r1")
    assert len(results) == 1
    assert results[0].id == "w1"


def test_query_limit(store: WorkItemStore) -> None:
    for i in range(10):
        store.save(_make_item(f"w{i}"))
    results = store.query(limit=3)
    assert len(results) == 3


# ---- Crash recovery ----


def test_get_incomplete(store: WorkItemStore) -> None:
    pending = _make_item("w1")
    store.save(pending)

    in_progress = _make_item("w2")
    in_progress.record_transition(WorkItemStatus.IN_PROGRESS, reason="ip")
    store.save(in_progress)

    completed = _make_item("w3")
    completed.record_transition(WorkItemStatus.COMPLETED, reason="done")
    store.save(completed)

    failed = _make_item("w4")
    failed.record_transition(WorkItemStatus.FAILED, reason="err")
    store.save(failed)

    incomplete = store.get_incomplete()
    ids = {item.id for item in incomplete}
    assert ids == {"w1", "w2"}


def test_crash_recovery_roundtrip(store: WorkItemStore) -> None:
    """Save items, create new store instance (simulating restart), verify recovery."""
    item = _make_item("w1")
    item.record_transition(WorkItemStatus.QUEUED, reason="q")
    item.record_transition(WorkItemStatus.IN_PROGRESS, reason="ip")
    store.save(item)

    # Simulate restart by creating a new store at the same path
    new_store = WorkItemStore(workspace_path=str(store._dir.parent))
    incomplete = new_store.get_incomplete()
    assert len(incomplete) == 1
    assert incomplete[0].id == "w1"
    assert incomplete[0].status == WorkItemStatus.IN_PROGRESS
    assert len(incomplete[0].history) == 3


# ---- Summary ----


def test_summary(store: WorkItemStore) -> None:
    store.save(_make_item("w1", type_id="alpha"))

    completed = _make_item("w2", type_id="beta")
    completed.record_transition(WorkItemStatus.COMPLETED, reason="done")
    store.save(completed)

    summary = store.summary()
    assert summary["total"] == 2
    assert summary["by_status"]["pending"] == 1
    assert summary["by_status"]["completed"] == 1
    assert summary["by_type"]["alpha"] == 1
    assert summary["by_type"]["beta"] == 1
