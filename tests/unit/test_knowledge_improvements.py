"""Tests for knowledge subsystem improvements.

Covers:
1. EmbeddingService and cosine_similarity
2. ContextMemory conversation tracking
3. Improved relevance scoring in KnowledgeStore.retrieve()
4. Memory expiry cleanup (cleanup_expired)
5. Semantic query
6. CONVERSATION MemoryType
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_orchestrator.knowledge.context_memory import ContextMemory
from agent_orchestrator.knowledge.embedding import EmbeddingService, cosine_similarity
from agent_orchestrator.knowledge.models import MemoryQuery, MemoryRecord, MemoryType
from agent_orchestrator.knowledge.store import KnowledgeStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_hash(content: dict[str, Any]) -> str:
    serialized = json.dumps(content, sort_keys=True, default=str).encode()
    return hashlib.sha256(serialized).hexdigest()


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
    timestamp: datetime | None = None,
) -> MemoryRecord:
    from uuid import uuid4

    content = content or {"key": "value"}
    return MemoryRecord(
        memory_id=str(uuid4()),
        memory_type=memory_type,
        title=title,
        content=content,
        content_hash=_compute_hash(content),
        tags=tags or ["test"],
        confidence=confidence,
        source_agent_id=agent_id,
        source_work_id=work_id,
        source_phase_id=phase_id,
        source_run_id=run_id,
        app_id=app_id,
        timestamp=timestamp or datetime.now(timezone.utc),
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# 1. cosine_similarity tests
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_empty_vectors(self) -> None:
        assert cosine_similarity([], []) == 0.0

    def test_different_length_vectors(self) -> None:
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vector(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_known_similarity(self) -> None:
        a = [1.0, 1.0]
        b = [1.0, 0.0]
        expected = 1.0 / math.sqrt(2)
        assert cosine_similarity(a, b) == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# 2. EmbeddingService tests
# ---------------------------------------------------------------------------


class TestEmbeddingService:
    def test_constructor_defaults(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        assert svc._model == "text-embedding-3-small"
        assert svc._base_url == "https://api.openai.com/v1"

    def test_constructor_custom(self) -> None:
        svc = EmbeddingService(
            api_key="k", model="custom-model", base_url="http://localhost:8080/v1/"
        )
        assert svc._model == "custom-model"
        assert svc._base_url == "http://localhost:8080/v1"

    @pytest.mark.asyncio
    async def test_embed_empty_text(self) -> None:
        svc = EmbeddingService(api_key="k")
        result = await svc.embed("")
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_success(self) -> None:
        svc = EmbeddingService(api_key="k")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.embed("hello world")
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_failure_returns_empty(self) -> None:
        svc = EmbeddingService(api_key="k")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("network error"))
        svc._client = mock_client

        result = await svc.embed("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self) -> None:
        svc = EmbeddingService(api_key="k")
        result = await svc.embed_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_batch_success(self) -> None:
        svc = EmbeddingService(api_key="k")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2], "index": 0},
                {"embedding": [0.3, 0.4], "index": 1},
            ]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.embed_batch(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]

    @pytest.mark.asyncio
    async def test_embed_batch_with_empty_strings(self) -> None:
        svc = EmbeddingService(api_key="k")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.5, 0.6], "index": 0}]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        svc._client = mock_client

        result = await svc.embed_batch(["", "hello", ""])
        assert len(result) == 3
        assert result[0] == []
        assert result[1] == [0.5, 0.6]
        assert result[2] == []

    @pytest.mark.asyncio
    async def test_embed_batch_failure(self) -> None:
        svc = EmbeddingService(api_key="k")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("fail"))
        svc._client = mock_client

        result = await svc.embed_batch(["a", "b"])
        assert result == [[], []]

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        svc = EmbeddingService(api_key="k")
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        svc._client = mock_client
        await svc.close()
        assert svc._client is None
        mock_client.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. CONVERSATION MemoryType
# ---------------------------------------------------------------------------


class TestConversationMemoryType:
    def test_conversation_enum_exists(self) -> None:
        assert MemoryType.CONVERSATION == "conversation"
        assert MemoryType("conversation") == MemoryType.CONVERSATION

    def test_all_types_still_exist(self) -> None:
        assert MemoryType.EVIDENCE == "evidence"
        assert MemoryType.DECISION == "decision"
        assert MemoryType.STRATEGY == "strategy"
        assert MemoryType.ARTIFACT == "artifact"
        assert MemoryType.CONVERSATION == "conversation"


# ---------------------------------------------------------------------------
# 4. ContextMemory tests
# ---------------------------------------------------------------------------


class TestContextMemory:
    def test_add_turn(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        ctx = ContextMemory(store)

        record = ctx.add_turn(
            work_id="w1",
            agent_id="a1",
            phase_id="p1",
            role="user",
            content="Hello agent",
            run_id="r1",
            app_id="app1",
        )

        assert record.memory_type == MemoryType.CONVERSATION
        assert record.content["role"] == "user"
        assert record.content["content"] == "Hello agent"
        assert "conversation" in record.tags
        assert "w1" in record.tags

    def test_get_history(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        ctx = ContextMemory(store)

        ctx.add_turn("w1", "a1", "p1", "user", "msg1", "r1", "app1")
        ctx.add_turn("w1", "a1", "p1", "assistant", "reply1", "r1", "app1")
        ctx.add_turn("w2", "a2", "p2", "user", "other work", "r1", "app1")

        history = ctx.get_history("w1")
        assert len(history) == 2
        # Should be chronologically ordered
        assert history[0].timestamp <= history[1].timestamp

    def test_get_agent_history(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        ctx = ContextMemory(store)

        ctx.add_turn("w1", "a1", "p1", "user", "from a1", "r1", "app1")
        ctx.add_turn("w1", "a2", "p1", "user", "from a2", "r1", "app1")
        ctx.add_turn("w1", "a1", "p1", "assistant", "reply a1", "r1", "app1")

        history = ctx.get_agent_history("w1", "a1")
        assert len(history) == 2
        for r in history:
            assert r.source_agent_id == "a1"

    def test_format_history(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        ctx = ContextMemory(store)

        ctx.add_turn("w1", "a1", "p1", "user", "hello", "r1", "app1")
        ctx.add_turn("w1", "a1", "p1", "assistant", "hi there", "r1", "app1")

        history = ctx.get_history("w1")
        formatted = ctx.format_history(history)

        assert "[a1] user: hello" in formatted
        assert "[a1] assistant: hi there" in formatted

    def test_empty_history(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        ctx = ContextMemory(store)

        history = ctx.get_history("nonexistent")
        assert history == []

    def test_format_empty_history(self) -> None:
        assert ContextMemory.format_history([]) == ""


# ---------------------------------------------------------------------------
# 5. Improved relevance scoring tests
# ---------------------------------------------------------------------------


class TestImprovedScoring:
    def test_tag_match_ratio_scoring(self, tmp_path: Path) -> None:
        """Records matching more query tags should score higher."""
        store = KnowledgeStore(tmp_path)

        r1 = _make_record(title="partial", tags=["alpha"], confidence=1.0)
        r2 = _make_record(
            title="full",
            tags=["alpha", "beta"],
            confidence=1.0,
            content={"k": "full"},
        )

        store.store(r1)
        store.store(r2)

        results = store.retrieve(MemoryQuery(tags=["alpha", "beta"], limit=10))
        assert len(results) == 2
        # r2 should score higher (matches both tags)
        assert results[0].title == "full"

    def test_keyword_match_ratio_scoring(self, tmp_path: Path) -> None:
        """Records matching more keywords should rank higher."""
        store = KnowledgeStore(tmp_path)

        r1 = _make_record(title="machine", tags=["test"], confidence=1.0)
        r2 = _make_record(
            title="machine learning",
            tags=["test"],
            confidence=1.0,
            content={"k": "ml"},
        )

        store.store(r1)
        store.store(r2)

        results = store.retrieve(
            MemoryQuery(keywords=["machine", "learning"], limit=10)
        )
        assert len(results) == 2
        assert results[0].title == "machine learning"

    def test_recency_bonus(self, tmp_path: Path) -> None:
        """Recent records should score higher than old ones."""
        store = KnowledgeStore(tmp_path)

        old_record = _make_record(
            title="old record",
            tags=["topic"],
            confidence=1.0,
            content={"age": "old"},
            timestamp=datetime.now(timezone.utc) - timedelta(hours=20),
        )
        new_record = _make_record(
            title="new record",
            tags=["topic"],
            confidence=1.0,
            content={"age": "new"},
            timestamp=datetime.now(timezone.utc),
        )

        store.store(old_record)
        store.store(new_record)

        results = store.retrieve(MemoryQuery(tags=["topic"], limit=10))
        assert len(results) == 2
        assert results[0].title == "new record"

    def test_confidence_weighting(self, tmp_path: Path) -> None:
        """Higher confidence should improve score."""
        store = KnowledgeStore(tmp_path)

        low = _make_record(
            title="low conf",
            tags=["tag"],
            confidence=0.3,
            content={"c": "low"},
        )
        high = _make_record(
            title="high conf",
            tags=["tag"],
            confidence=1.0,
            content={"c": "high"},
        )

        store.store(low)
        store.store(high)

        results = store.retrieve(MemoryQuery(tags=["tag"], limit=10))
        assert results[0].title == "high conf"

    def test_backward_compatible_no_tags_no_keywords(self, tmp_path: Path) -> None:
        """Retrieve without tags/keywords still returns results."""
        store = KnowledgeStore(tmp_path)
        r = _make_record(title="any")
        store.store(r)

        results = store.retrieve(MemoryQuery(limit=10))
        assert len(results) == 1


# ---------------------------------------------------------------------------
# 6. cleanup_expired tests
# ---------------------------------------------------------------------------


class TestCleanupExpired:
    def test_removes_expired_records(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)

        expired = _make_record(
            title="expired",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            content={"k": "expired"},
        )
        valid = _make_record(
            title="valid",
            content={"k": "valid"},
        )

        store.store(expired)
        store.store(valid)

        cleaned = store.cleanup_expired()
        assert cleaned == 1

        # Only the valid record should remain
        results = store.retrieve(MemoryQuery(limit=100, include_expired=True))
        assert len(results) == 1
        assert results[0].title == "valid"

    def test_no_expired_records(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        r = _make_record(title="fresh")
        store.store(r)

        cleaned = store.cleanup_expired()
        assert cleaned == 0

    def test_cleanup_future_expiry_not_removed(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        future = _make_record(
            title="future",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        store.store(future)

        cleaned = store.cleanup_expired()
        assert cleaned == 0

    def test_cleanup_returns_count(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        past = datetime.now(timezone.utc) - timedelta(hours=1)

        for i in range(5):
            r = _make_record(
                title=f"expired-{i}",
                expires_at=past,
                content={"idx": i},
            )
            store.store(r)

        cleaned = store.cleanup_expired()
        assert cleaned == 5


# ---------------------------------------------------------------------------
# 7. Embedding persistence tests
# ---------------------------------------------------------------------------


class TestEmbeddingPersistence:
    def test_persist_and_load_embeddings(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)

        # Manually add embeddings
        store._embeddings["hash1"] = [0.1, 0.2, 0.3]
        store._embeddings["hash2"] = [0.4, 0.5, 0.6]
        store._persist_embeddings()

        # Create a new store and verify embeddings were loaded
        store2 = KnowledgeStore(tmp_path)
        assert store2._embeddings["hash1"] == [0.1, 0.2, 0.3]
        assert store2._embeddings["hash2"] == [0.4, 0.5, 0.6]

    def test_load_embeddings_missing_file(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        assert store._embeddings == {}

    def test_embeddings_file_format(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        store._embeddings["abc"] = [1.0, 2.0]
        store._persist_embeddings()

        embeddings_path = tmp_path / "knowledge" / "embeddings.jsonl"
        assert embeddings_path.exists()
        lines = embeddings_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["content_hash"] == "abc"
        assert data["vector"] == [1.0, 2.0]


# ---------------------------------------------------------------------------
# 8. Semantic query tests
# ---------------------------------------------------------------------------


class TestSemanticQuery:
    @pytest.mark.asyncio
    async def test_semantic_query_no_service_raises(self, tmp_path: Path) -> None:
        from agent_orchestrator.exceptions import KnowledgeError

        store = KnowledgeStore(tmp_path)
        with pytest.raises(KnowledgeError, match="Embedding service not configured"):
            await store.semantic_query("test")

    @pytest.mark.asyncio
    async def test_semantic_query_returns_similar(self, tmp_path: Path) -> None:
        mock_service = AsyncMock()
        # Return a query vector
        mock_service.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])

        store = KnowledgeStore(tmp_path, embedding_service=mock_service)

        # Store a record and manually add its embedding
        r = _make_record(title="relevant", content={"k": "v"})
        store.store(r)
        store._embeddings[r.content_hash] = [0.9, 0.1, 0.0]

        results = await store.semantic_query("test query", limit=5, min_similarity=0.5)
        assert len(results) == 1
        assert results[0].title == "relevant"

    @pytest.mark.asyncio
    async def test_semantic_query_filters_below_threshold(
        self, tmp_path: Path,
    ) -> None:
        mock_service = AsyncMock()
        mock_service.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])

        store = KnowledgeStore(tmp_path, embedding_service=mock_service)

        r = _make_record(title="irrelevant", content={"k": "irr"})
        store.store(r)
        # Orthogonal vector — similarity near 0
        store._embeddings[r.content_hash] = [0.0, 1.0, 0.0]

        results = await store.semantic_query("test", min_similarity=0.5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_semantic_query_empty_embedding(self, tmp_path: Path) -> None:
        mock_service = AsyncMock()
        mock_service.embed = AsyncMock(return_value=[])

        store = KnowledgeStore(tmp_path, embedding_service=mock_service)

        results = await store.semantic_query("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_semantic_query_ordering(self, tmp_path: Path) -> None:
        mock_service = AsyncMock()
        mock_service.embed = AsyncMock(return_value=[1.0, 0.0])

        store = KnowledgeStore(tmp_path, embedding_service=mock_service)

        r1 = _make_record(title="less similar", content={"s": 1})
        r2 = _make_record(title="more similar", content={"s": 2})
        store.store(r1)
        store.store(r2)

        store._embeddings[r1.content_hash] = [0.7, 0.7]
        store._embeddings[r2.content_hash] = [0.99, 0.1]

        results = await store.semantic_query("q", limit=10, min_similarity=0.0)
        assert len(results) == 2
        assert results[0].title == "more similar"


# ---------------------------------------------------------------------------
# 9. KnowledgeStore backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_constructor_without_embedding_service(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        assert store._embedding_service is None
        assert store._embeddings == {}

    def test_store_without_embedding(self, tmp_path: Path) -> None:
        store = KnowledgeStore(tmp_path)
        r = _make_record(title="no embedding")
        mid = store.store(r)
        assert mid
        assert store._embeddings == {}

    def test_existing_retrieve_unchanged(self, tmp_path: Path) -> None:
        """The existing query() / retrieve() still works."""
        store = KnowledgeStore(tmp_path)
        r = _make_record(title="test", tags=["mytag"])
        store.store(r)

        results = store.retrieve(MemoryQuery(tags=["mytag"], limit=5))
        assert len(results) == 1
        assert results[0].title == "test"


# ---------------------------------------------------------------------------
# 10. Engine integration with ContextMemory
# ---------------------------------------------------------------------------


class TestEngineContextMemoryIntegration:
    def test_engine_has_context_memory_attribute(self) -> None:
        """Engine should declare _context_memory attribute."""
        from agent_orchestrator.core.engine import OrchestrationEngine

        # Just verify the attribute is declared in __init__
        assert hasattr(OrchestrationEngine, "context_memory")
