"""Tests for ArtifactStore — content-addressable artifact storage."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_orchestrator.persistence.artifact_store import (
    Artifact,
    ArtifactStore,
    _compute_hash,
    create_artifact,
)


def _make_artifact(
    work_id: str = "work-1",
    phase_id: str = "phase-1",
    agent_id: str = "agent-1",
    artifact_type: str = "output",
    content: dict | None = None,
    run_id: str = "",
    app_id: str = "",
) -> Artifact:
    """Helper to build an artifact with sensible defaults."""
    return create_artifact(
        work_id=work_id,
        phase_id=phase_id,
        agent_id=agent_id,
        artifact_type=artifact_type,
        content=content or {"key": "value"},
        run_id=run_id,
        app_id=app_id,
    )


# ------------------------------------------------------------------
# Store & retrieve
# ------------------------------------------------------------------


def test_store_and_retrieve(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = _make_artifact(content={"greeting": "hello"})
    content_hash = store.store(artifact)

    retrieved = store.get_by_hash(content_hash)
    assert retrieved is not None
    assert retrieved.content == {"greeting": "hello"}
    assert retrieved.work_id == "work-1"
    assert retrieved.content_hash == content_hash


def test_store_generates_hash(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = _make_artifact(content={"data": 42})
    content_hash = store.store(artifact)

    expected_hash = _compute_hash({"data": 42})
    assert content_hash == expected_hash
    assert artifact.content_hash == expected_hash


# ------------------------------------------------------------------
# Deduplication
# ------------------------------------------------------------------


def test_content_deduplication(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    content = {"same": "content"}

    a1 = _make_artifact(work_id="w1", content=content)
    a2 = _make_artifact(work_id="w2", content=content)

    h1 = store.store(a1)
    h2 = store.store(a2)

    assert h1 == h2

    # Only one content file should exist
    content_files = list((tmp_path / "artifacts").glob("*.json"))
    # Exclude index.jsonl
    content_files = [f for f in content_files if f.name != "index.jsonl"]
    assert len(content_files) == 1

    # But there should be two index entries
    assert store.count() == 2


# ------------------------------------------------------------------
# Query filters
# ------------------------------------------------------------------


def test_query_by_work_id(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.store(_make_artifact(work_id="w-a"))
    store.store(_make_artifact(work_id="w-b"))
    store.store(_make_artifact(work_id="w-a"))

    results = store.query(work_id="w-a")
    assert len(results) == 2
    assert all(r.work_id == "w-a" for r in results)


def test_query_by_phase_id(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.store(_make_artifact(phase_id="p1", content={"v": 1}))
    store.store(_make_artifact(phase_id="p2", content={"v": 2}))

    results = store.query(phase_id="p1")
    assert len(results) == 1
    assert results[0].phase_id == "p1"


def test_query_by_agent_id(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.store(_make_artifact(agent_id="a1", content={"v": 1}))
    store.store(_make_artifact(agent_id="a2", content={"v": 2}))

    results = store.query(agent_id="a1")
    assert len(results) == 1
    assert results[0].agent_id == "a1"


def test_query_by_artifact_type(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.store(_make_artifact(artifact_type="input", content={"v": 1}))
    store.store(_make_artifact(artifact_type="output", content={"v": 2}))
    store.store(_make_artifact(artifact_type="critic_feedback", content={"v": 3}))

    results = store.query(artifact_type="output")
    assert len(results) == 1
    assert results[0].artifact_type == "output"


def test_query_limit(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    for i in range(10):
        store.store(_make_artifact(content={"i": i}))

    results = store.query(limit=3)
    assert len(results) == 3


# ------------------------------------------------------------------
# Chain
# ------------------------------------------------------------------


def test_get_chain(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    # Store with slightly different timestamps to guarantee ordering
    a1 = create_artifact(
        work_id="w1",
        phase_id="p1",
        agent_id="a1",
        artifact_type="input",
        content={"step": 1},
    )
    a1.timestamp = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    a2 = create_artifact(
        work_id="w1",
        phase_id="p1",
        agent_id="a1",
        artifact_type="output",
        content={"step": 2},
    )
    a2.timestamp = datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc)

    a3 = create_artifact(
        work_id="w1",
        phase_id="p2",
        agent_id="a2",
        artifact_type="critic_feedback",
        content={"step": 3},
    )
    a3.timestamp = datetime(2025, 1, 1, 0, 0, 2, tzinfo=timezone.utc)

    store.store(a2)  # store out of order
    store.store(a1)
    store.store(a3)

    chain = store.get_chain("w1")
    assert len(chain) == 3
    assert chain[0].content == {"step": 1}
    assert chain[1].content == {"step": 2}
    assert chain[2].content == {"step": 3}


def test_get_chain_empty(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    assert store.get_chain("nonexistent") == []


# ------------------------------------------------------------------
# Count
# ------------------------------------------------------------------


def test_count(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    assert store.count() == 0

    store.store(_make_artifact(content={"a": 1}))
    store.store(_make_artifact(content={"b": 2}))
    store.store(_make_artifact(content={"c": 3}))
    assert store.count() == 3


# ------------------------------------------------------------------
# Factory function
# ------------------------------------------------------------------


def test_create_artifact_helper() -> None:
    artifact = create_artifact(
        work_id="w1",
        phase_id="p1",
        agent_id="a1",
        artifact_type="input",
        content={"data": "test"},
        run_id="run-42",
        app_id="app-7",
        version=2,
    )

    assert artifact.work_id == "w1"
    assert artifact.phase_id == "p1"
    assert artifact.agent_id == "a1"
    assert artifact.artifact_type == "input"
    assert artifact.content == {"data": "test"}
    assert artifact.run_id == "run-42"
    assert artifact.app_id == "app-7"
    assert artifact.version == 2
    assert artifact.artifact_id  # non-empty UUID
    assert artifact.content_hash  # non-empty hash
    assert artifact.timestamp.tzinfo is not None


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


def test_get_by_hash_not_found(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    assert store.get_by_hash("0000dead0000") is None
