"""Tests for KnowledgeStore — CRUD, query, supersede, expiry, dedup, stats."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_orchestrator.knowledge.models import MemoryQuery, MemoryRecord, MemoryType
from agent_orchestrator.knowledge.store import KnowledgeStore


def _make_record(
    title: str = "Test memory",
    memory_type: MemoryType = MemoryType.DECISION,
    content: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    confidence: float = 0.9,
    expires_at: datetime | None = None,
    agent_id: str = "agent-1",
    work_id: str = "work-1",
    phase_id: str = "phase-1",
    run_id: str = "run-1",
    app_id: str = "app-1",
) -> MemoryRecord:
    """Create a MemoryRecord for testing."""
    from uuid import uuid4
    import hashlib

    content = content or {"key": "value"}
    content_hash = hashlib.sha256(
        json.dumps(content, sort_keys=True, default=str).encode()
    ).hexdigest()

    return MemoryRecord(
        memory_id=str(uuid4()),
        memory_type=memory_type,
        title=title,
        content=content,
        content_hash=content_hash,
        tags=tags or ["test"],
        confidence=confidence,
        source_agent_id=agent_id,
        source_work_id=work_id,
        source_phase_id=phase_id,
        source_run_id=run_id,
        app_id=app_id,
        timestamp=datetime.now(timezone.utc),
        expires_at=expires_at,
        superseded_by=None,
        version=1,
        metadata={},
    )


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    """Create a KnowledgeStore in a temp directory."""
    return KnowledgeStore(tmp_path)


class TestStoreAndGet:
    """Store and retrieve individual records."""

    def test_store_returns_memory_id(self, store: KnowledgeStore) -> None:
        record = _make_record()
        memory_id = store.store(record)
        assert memory_id == record.memory_id

    def test_get_by_id(self, store: KnowledgeStore) -> None:
        record = _make_record(title="findme")
        store.store(record)
        result = store.get(record.memory_id)
        assert result is not None
        assert result.title == "findme"
        assert result.content == record.content

    def test_get_missing_returns_none(self, store: KnowledgeStore) -> None:
        assert store.get("nonexistent") is None

    def test_dedup_same_content(self, store: KnowledgeStore) -> None:
        content = {"same": "data"}
        r1 = _make_record(title="first", content=content)
        r2 = _make_record(title="second", content=content)
        store.store(r1)
        store.store(r2)
        # Two index entries but only one content file
        knowledge_dir = store._knowledge_dir
        content_files = list(knowledge_dir.glob("*.json"))
        assert len(content_files) == 1


class TestRetrieve:
    """Query-based retrieval with filtering and scoring."""

    def test_retrieve_by_type(self, store: KnowledgeStore) -> None:
        store.store(_make_record(memory_type=MemoryType.DECISION))
        store.store(_make_record(memory_type=MemoryType.STRATEGY))
        results = store.retrieve(MemoryQuery(memory_type=MemoryType.DECISION))
        assert len(results) == 1
        assert results[0].memory_type == MemoryType.DECISION

    def test_retrieve_by_tags(self, store: KnowledgeStore) -> None:
        store.store(_make_record(tags=["alpha", "beta"]))
        store.store(_make_record(tags=["gamma"]))
        results = store.retrieve(MemoryQuery(tags=["alpha"]))
        assert len(results) == 1
        assert "alpha" in results[0].tags

    def test_retrieve_by_keywords(self, store: KnowledgeStore) -> None:
        store.store(_make_record(title="Vendor approval decision"))
        store.store(_make_record(title="Unrelated stuff"))
        results = store.retrieve(MemoryQuery(keywords=["vendor"]))
        assert len(results) == 1
        assert "Vendor" in results[0].title

    def test_retrieve_by_agent_id(self, store: KnowledgeStore) -> None:
        store.store(_make_record(agent_id="agent-A"))
        store.store(_make_record(agent_id="agent-B"))
        results = store.retrieve(MemoryQuery(agent_id="agent-A"))
        assert len(results) == 1

    def test_retrieve_by_app_id(self, store: KnowledgeStore) -> None:
        store.store(_make_record(app_id="app-X"))
        store.store(_make_record(app_id="app-Y"))
        results = store.retrieve(MemoryQuery(app_id="app-X"))
        assert len(results) == 1

    def test_retrieve_min_confidence(self, store: KnowledgeStore) -> None:
        store.store(_make_record(confidence=0.3))
        store.store(_make_record(confidence=0.9))
        results = store.retrieve(MemoryQuery(min_confidence=0.5))
        assert len(results) == 1
        assert results[0].confidence >= 0.5

    def test_retrieve_limit(self, store: KnowledgeStore) -> None:
        for i in range(5):
            store.store(_make_record(
                title=f"Record {i}",
                content={"idx": i},
            ))
        results = store.retrieve(MemoryQuery(limit=3))
        assert len(results) == 3

    def test_retrieve_excludes_expired_by_default(self, store: KnowledgeStore) -> None:
        expired = _make_record(
            title="expired",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        store.store(expired)
        store.store(_make_record(title="active"))
        results = store.retrieve(MemoryQuery())
        assert all(r.title != "expired" for r in results)

    def test_retrieve_includes_expired_when_requested(self, store: KnowledgeStore) -> None:
        expired = _make_record(
            title="expired",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        store.store(expired)
        results = store.retrieve(MemoryQuery(include_expired=True))
        assert any(r.title == "expired" for r in results)

    def test_retrieve_scored_by_relevance(self, store: KnowledgeStore) -> None:
        store.store(_make_record(
            title="Highly relevant",
            tags=["search-tag", "extra"],
            confidence=0.95,
        ))
        store.store(_make_record(
            title="Less relevant",
            tags=["other"],
            confidence=0.5,
        ))
        results = store.retrieve(MemoryQuery(tags=["search-tag"]))
        assert results[0].title == "Highly relevant"


class TestSupersede:
    """Version chaining via supersede."""

    def test_supersede_creates_new_version(self, store: KnowledgeStore) -> None:
        old = _make_record(title="v1", content={"version": 1})
        store.store(old)
        new = _make_record(title="v2", content={"version": 2})
        new_id = store.supersede(old.memory_id, new)
        assert new_id == new.memory_id

        # New record has incremented version
        new_record = store.get(new_id)
        assert new_record is not None
        assert new_record.version == 2

        # Old record links to new
        old_record = store.get(old.memory_id)
        assert old_record is not None
        assert old_record.superseded_by == new_id

    def test_supersede_nonexistent_raises(self, store: KnowledgeStore) -> None:
        new = _make_record()
        with pytest.raises(Exception):
            store.supersede("nonexistent", new)


class TestDelete:
    """Soft deletion via expires_at."""

    def test_delete_sets_expiry(self, store: KnowledgeStore) -> None:
        record = _make_record()
        store.store(record)
        assert store.delete(record.memory_id) is True
        # Should be excluded from default queries
        results = store.retrieve(MemoryQuery())
        assert len(results) == 0

    def test_delete_nonexistent_returns_false(self, store: KnowledgeStore) -> None:
        assert store.delete("nonexistent") is False


class TestStats:
    """Stats reporting."""

    def test_stats_counts_by_type(self, store: KnowledgeStore) -> None:
        store.store(_make_record(memory_type=MemoryType.DECISION))
        store.store(_make_record(memory_type=MemoryType.DECISION, content={"d": 2}))
        store.store(_make_record(memory_type=MemoryType.STRATEGY, content={"s": 1}))
        stats = store.stats()
        assert stats["total"] == 3
        assert stats["by_type"]["decision"] == 2
        assert stats["by_type"]["strategy"] == 1
