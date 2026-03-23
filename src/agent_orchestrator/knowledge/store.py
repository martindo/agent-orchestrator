"""KnowledgeStore — File-based shared memory store for agents.

Content-addressable storage with JSONL index and SHA-256 deduplication.
Follows the same pattern as ``persistence/artifact_store.py``.

Thread-safe: All public methods use an internal lock.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_orchestrator.exceptions import KnowledgeError
from agent_orchestrator.knowledge.models import MemoryQuery, MemoryRecord, MemoryType

if TYPE_CHECKING:
    from agent_orchestrator.knowledge.embedding import EmbeddingService

logger = logging.getLogger(__name__)


def _compute_hash(content: dict[str, Any]) -> str:
    """Compute SHA-256 hex digest for memory content."""
    serialized = json.dumps(content, sort_keys=True, default=str).encode()
    return hashlib.sha256(serialized).hexdigest()


class KnowledgeStore:
    """File-based content-addressable knowledge store.

    Stores memory record content as individual JSON files keyed by SHA-256
    hash. Maintains a JSONL index for querying record metadata.

    Thread-safe: All public methods use an internal lock.

    Directory layout::

        base_dir/knowledge/
          index.jsonl          — one JSON object per line (metadata, no content)
          {content_hash}.json  — full content dict
    """

    def __init__(
        self,
        base_dir: Path,
        event_bus: Any | None = None,
        embedding_service: "EmbeddingService | None" = None,
    ) -> None:
        self._knowledge_dir = base_dir / "knowledge"
        self._knowledge_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._knowledge_dir / "index.jsonl"
        if not self._index_path.exists():
            self._index_path.touch()
        self._event_bus = event_bus
        self._lock = threading.Lock()
        self._embedding_service = embedding_service
        self._embeddings: dict[str, list[float]] = {}
        self._embeddings_path = self._knowledge_dir / "embeddings.jsonl"
        self._load_embeddings()
        logger.debug("KnowledgeStore initialized at %s", self._knowledge_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, record: MemoryRecord) -> str:
        """Persist a memory record and return its memory_id.

        Computes the content hash from the record's content, writes the
        content file (skipping if it already exists for deduplication),
        and appends a metadata entry to the index.

        Args:
            record: The memory record to store.

        Returns:
            The memory_id of the stored record.

        Raises:
            KnowledgeError: If writing fails.
        """
        content_hash = _compute_hash(record.content)
        record.content_hash = content_hash

        if not record.memory_id:
            record.memory_id = str(uuid.uuid4())

        with self._lock:
            try:
                content_path = self._knowledge_dir / f"{content_hash}.json"
                if not content_path.exists():
                    content_path.write_text(
                        json.dumps(record.content, sort_keys=True, default=str),
                        encoding="utf-8",
                    )
                    logger.debug("Wrote content file %s", content_path.name)
                else:
                    logger.debug("Content file %s already exists, dedup", content_path.name)

                self._append_index(self._record_to_index_entry(record))
            except OSError as exc:
                raise KnowledgeError(f"Failed to store memory record: {exc}") from exc

        # Compute and cache embedding if service is available
        if self._embedding_service is not None and content_hash not in self._embeddings:
            try:
                import asyncio
                text = record.title + " " + json.dumps(record.content, default=str)
                loop: asyncio.AbstractEventLoop | None = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass
                if loop is not None and loop.is_running():
                    # Schedule embedding as a task — will be cached when complete
                    loop.create_task(self._compute_and_cache_embedding(content_hash, text))
                else:
                    # Run synchronously in a new event loop
                    vector = asyncio.run(self._embedding_service.embed(text))
                    if vector:
                        with self._lock:
                            self._embeddings[content_hash] = vector
                        self._persist_embeddings()
            except Exception:
                logger.debug("Embedding computation skipped", exc_info=True)

        logger.info("Stored memory record %s (type=%s)", record.memory_id, record.memory_type.value)
        return record.memory_id

    async def _compute_and_cache_embedding(self, content_hash: str, text: str) -> None:
        """Compute embedding asynchronously and cache it."""
        if self._embedding_service is None:
            return
        try:
            vector = await self._embedding_service.embed(text)
            if vector:
                with self._lock:
                    self._embeddings[content_hash] = vector
                self._persist_embeddings()
        except Exception:
            logger.debug("Async embedding computation failed", exc_info=True)

    def retrieve(self, query: MemoryQuery) -> list[MemoryRecord]:
        """Retrieve memory records matching the query with relevance scoring.

        Applies exact-match filters first, then scores remaining records
        by tag and keyword overlap weighted by confidence. Returns up to
        ``query.limit`` results sorted by descending score.

        Args:
            query: Filter and scoring criteria.

        Returns:
            List of matching MemoryRecord objects, highest score first.
        """
        with self._lock:
            entries = self._read_index()

        now = datetime.now(timezone.utc)
        candidates: list[tuple[float, dict[str, Any]]] = []

        for entry in entries:
            # --- exact-match filters ---
            if query.memory_type is not None and entry.get("memory_type") != query.memory_type.value:
                continue
            if query.agent_id is not None and entry.get("source_agent_id") != query.agent_id:
                continue
            if query.work_id is not None and entry.get("source_work_id") != query.work_id:
                continue
            if query.app_id is not None and entry.get("app_id") != query.app_id:
                continue

            confidence = float(entry.get("confidence", 0.0))
            if confidence < query.min_confidence:
                continue

            # --- expiry check ---
            if not query.include_expired:
                expires_raw = entry.get("expires_at")
                if expires_raw is not None:
                    try:
                        expires_at = datetime.fromisoformat(str(expires_raw))
                        if expires_at <= now:
                            continue
                    except (ValueError, TypeError):
                        pass

            # --- relevance scoring ---
            score = 0.0
            entry_tags = set(entry.get("tags", []))
            has_relevance_filter = bool(query.tags or query.keywords)

            tag_match_ratio = 0.0
            keyword_match_ratio = 0.0

            if query.tags:
                matching_tags = len(set(query.tags) & entry_tags)
                tag_match_ratio = matching_tags / len(query.tags)

            if query.keywords:
                searchable_text = self._build_searchable_text(entry)
                matching_keywords = sum(
                    1 for kw in query.keywords if kw.lower() in searchable_text
                )
                keyword_match_ratio = matching_keywords / len(query.keywords)

            # Skip records with no relevance match when tags/keywords are specified
            if has_relevance_filter and tag_match_ratio == 0.0 and keyword_match_ratio == 0.0:
                continue

            # Recency bonus: 1.0 for < 1 hour, decaying to 0.0 at 24 hours
            recency_bonus = 0.0
            timestamp_raw = entry.get("timestamp", "")
            if isinstance(timestamp_raw, str) and timestamp_raw:
                try:
                    entry_time = datetime.fromisoformat(timestamp_raw)
                    age_seconds = max(0.0, (now - entry_time).total_seconds())
                    age_hours = age_seconds / 3600.0
                    if age_hours < 1.0:
                        recency_bonus = 1.0
                    elif age_hours < 24.0:
                        recency_bonus = max(0.0, 1.0 - (age_hours - 1.0) / 23.0)
                except (ValueError, TypeError):
                    pass

            score = (tag_match_ratio * 3.0 + keyword_match_ratio * 2.0 + recency_bonus) * (confidence if confidence > 0 else 1.0)
            candidates.append((score, entry))

        # Sort by score descending, then by timestamp descending for ties
        candidates.sort(key=lambda pair: (pair[0], pair[1].get("timestamp", "")), reverse=True)
        top_entries = [entry for _, entry in candidates[: query.limit]]

        results: list[MemoryRecord] = []
        for entry in top_entries:
            content = self._read_content(entry["content_hash"])
            if content is not None:
                results.append(self._entry_to_record(entry, content))
        return results

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Retrieve a single memory record by its ID.

        Args:
            memory_id: The unique identifier of the record.

        Returns:
            The MemoryRecord if found, otherwise None.
        """
        with self._lock:
            entries = self._read_index()

        matching = [e for e in entries if e.get("memory_id") == memory_id]
        if not matching:
            return None

        entry = matching[-1]
        content = self._read_content(entry["content_hash"])
        if content is None:
            return None

        return self._entry_to_record(entry, content)

    def supersede(self, old_id: str, new_record: MemoryRecord) -> str:
        """Replace an existing record with a new version.

        Sets the old record's ``superseded_by`` to the new record's ID
        and stores the new record with an incremented version number.

        Args:
            old_id: The memory_id of the record to supersede.
            new_record: The replacement record.

        Returns:
            The memory_id of the newly stored record.

        Raises:
            KnowledgeError: If the old record is not found or write fails.
        """
        old_record = self.get(old_id)
        if old_record is None:
            raise KnowledgeError(f"Cannot supersede: record {old_id!r} not found")

        if not new_record.memory_id:
            new_record.memory_id = str(uuid.uuid4())

        new_record.version = old_record.version + 1

        # Update old record's superseded_by in the index
        with self._lock:
            try:
                entries = self._read_index()
                updated = False
                for entry in entries:
                    if entry.get("memory_id") == old_id:
                        entry["superseded_by"] = new_record.memory_id
                        updated = True

                if not updated:
                    raise KnowledgeError(f"Cannot supersede: record {old_id!r} not found in index")

                self._rewrite_index(entries)
            except OSError as exc:
                raise KnowledgeError(f"Failed to update superseded record: {exc}") from exc

        new_id = self.store(new_record)
        logger.info("Superseded record %s with %s (version %d)", old_id, new_id, new_record.version)
        return new_id

    def delete(self, memory_id: str) -> bool:
        """Soft-delete a memory record by setting expires_at to now.

        Args:
            memory_id: The unique identifier of the record to delete.

        Returns:
            True if the record was found and marked expired, False otherwise.
        """
        with self._lock:
            try:
                entries = self._read_index()
                found = False
                now_iso = datetime.now(timezone.utc).isoformat()
                for entry in entries:
                    if entry.get("memory_id") == memory_id:
                        entry["expires_at"] = now_iso
                        found = True

                if found:
                    self._rewrite_index(entries)
                    logger.info("Soft-deleted memory record %s", memory_id)
                return found
            except OSError as exc:
                raise KnowledgeError(f"Failed to delete memory record: {exc}") from exc

    def stats(self) -> dict[str, Any]:
        """Return summary statistics for the knowledge store.

        Returns:
            Dict with total count and per-type breakdown.
        """
        with self._lock:
            entries = self._read_index()

        counts_by_type: dict[str, int] = {}
        for entry in entries:
            mt = entry.get("memory_type", "unknown")
            counts_by_type[mt] = counts_by_type.get(mt, 0) + 1

        return {
            "total": len(entries),
            "by_type": counts_by_type,
        }

    async def semantic_query(
        self,
        query_text: str,
        limit: int = 10,
        min_similarity: float = 0.5,
    ) -> list[MemoryRecord]:
        """Search memory records using embedding-based semantic similarity.

        Embeds the query text, computes cosine similarity against all cached
        embeddings, and returns the top-k records above the minimum threshold.

        Args:
            query_text: Natural language query to search for.
            limit: Maximum number of results to return.
            min_similarity: Minimum cosine similarity threshold (0-1).

        Returns:
            List of matching MemoryRecord objects, highest similarity first.

        Raises:
            KnowledgeError: If embedding service is not configured.
        """
        if self._embedding_service is None:
            raise KnowledgeError("Embedding service not configured for semantic search")

        from agent_orchestrator.knowledge.embedding import cosine_similarity

        query_vector = await self._embedding_service.embed(query_text)
        if not query_vector:
            return []

        with self._lock:
            entries = self._read_index()
            embeddings_snapshot = dict(self._embeddings)

        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in entries:
            content_hash = entry.get("content_hash", "")
            vector = embeddings_snapshot.get(content_hash)
            if vector is None:
                continue

            similarity = cosine_similarity(query_vector, vector)
            if similarity >= min_similarity:
                scored.append((similarity, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        top_entries = scored[:limit]

        results: list[MemoryRecord] = []
        for _sim, entry in top_entries:
            content = self._read_content(entry["content_hash"])
            if content is not None:
                results.append(self._entry_to_record(entry, content))
        return results

    def cleanup_expired(self) -> int:
        """Remove expired records from the index.

        Scans the index for records where ``expires_at`` is in the past
        and removes them. Content files are not deleted as they may be
        shared via content-addressing.

        Returns:
            Count of cleaned (removed) records.
        """
        now = datetime.now(timezone.utc)
        cleaned = 0

        with self._lock:
            try:
                entries = self._read_index()
                kept: list[dict[str, Any]] = []
                for entry in entries:
                    expires_raw = entry.get("expires_at")
                    if expires_raw is not None:
                        try:
                            expires_at = datetime.fromisoformat(str(expires_raw))
                            if expires_at <= now:
                                cleaned += 1
                                continue
                        except (ValueError, TypeError):
                            pass
                    kept.append(entry)

                if cleaned > 0:
                    self._rewrite_index(kept)
                    logger.info("Cleaned up %d expired memory records", cleaned)
            except OSError as exc:
                raise KnowledgeError(f"Failed to clean up expired records: {exc}") from exc

        return cleaned

    def _load_embeddings(self) -> None:
        """Load cached embeddings from the JSONL file."""
        if not self._embeddings_path.exists():
            return
        try:
            text = self._embeddings_path.read_text(encoding="utf-8").strip()
            if not text:
                return
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                content_hash = data.get("content_hash", "")
                vector = data.get("vector", [])
                if content_hash and vector:
                    self._embeddings[content_hash] = vector
            logger.debug("Loaded %d cached embeddings", len(self._embeddings))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load embeddings: %s", exc, exc_info=True)

    def _persist_embeddings(self) -> None:
        """Write all cached embeddings to the JSONL file."""
        with self._lock:
            snapshot = dict(self._embeddings)
        try:
            with open(self._embeddings_path, "w", encoding="utf-8") as fh:
                for content_hash, vector in snapshot.items():
                    fh.write(
                        json.dumps(
                            {"content_hash": content_hash, "vector": vector},
                            sort_keys=True,
                        )
                        + "\n"
                    )
        except OSError as exc:
            logger.error("Failed to persist embeddings: %s", exc, exc_info=True)

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
            logger.error("Failed to read knowledge index: %s", exc, exc_info=True)
        return entries

    def _append_index(self, entry: dict[str, Any]) -> None:
        """Append a single entry to the JSONL index file."""
        with open(self._index_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    def _rewrite_index(self, entries: list[dict[str, Any]]) -> None:
        """Rewrite the entire JSONL index file with updated entries."""
        with open(self._index_path, "w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    def _read_content(self, content_hash: str) -> dict[str, Any] | None:
        """Read content from a content-addressed file."""
        content_path = self._knowledge_dir / f"{content_hash}.json"
        try:
            text = content_path.read_text(encoding="utf-8")
            return json.loads(text)  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read content %s: %s", content_hash, exc, exc_info=True)
            return None

    @staticmethod
    def _record_to_index_entry(record: MemoryRecord) -> dict[str, Any]:
        """Convert a MemoryRecord to an index entry dict (excludes content)."""
        return {
            "memory_id": record.memory_id,
            "memory_type": record.memory_type.value,
            "title": record.title,
            "content_hash": record.content_hash,
            "tags": record.tags,
            "confidence": record.confidence,
            "source_agent_id": record.source_agent_id,
            "source_work_id": record.source_work_id,
            "source_phase_id": record.source_phase_id,
            "source_run_id": record.source_run_id,
            "app_id": record.app_id,
            "timestamp": record.timestamp.isoformat(),
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            "superseded_by": record.superseded_by,
            "version": record.version,
            "metadata": record.metadata,
        }

    @staticmethod
    def _entry_to_record(entry: dict[str, Any], content: dict[str, Any]) -> MemoryRecord:
        """Reconstruct a MemoryRecord from an index entry and content dict."""
        timestamp_raw = entry.get("timestamp", "")
        if isinstance(timestamp_raw, str) and timestamp_raw:
            timestamp = datetime.fromisoformat(timestamp_raw)
        else:
            timestamp = datetime.now(timezone.utc)

        expires_raw = entry.get("expires_at")
        expires_at: datetime | None = None
        if expires_raw is not None and isinstance(expires_raw, str):
            try:
                expires_at = datetime.fromisoformat(expires_raw)
            except (ValueError, TypeError):
                pass

        return MemoryRecord(
            memory_id=entry["memory_id"],
            memory_type=MemoryType(entry["memory_type"]),
            title=entry.get("title", ""),
            content=content,
            content_hash=entry["content_hash"],
            tags=entry.get("tags", []),
            confidence=float(entry.get("confidence", 0.0)),
            source_agent_id=entry.get("source_agent_id", ""),
            source_work_id=entry.get("source_work_id", ""),
            source_phase_id=entry.get("source_phase_id", ""),
            source_run_id=entry.get("source_run_id", ""),
            app_id=entry.get("app_id", ""),
            timestamp=timestamp,
            expires_at=expires_at,
            superseded_by=entry.get("superseded_by"),
            version=entry.get("version", 1),
            metadata=entry.get("metadata", {}),
        )

    @staticmethod
    def _build_searchable_text(entry: dict[str, Any]) -> str:
        """Build a lowercase searchable string from an index entry.

        Combines the title and JSON-serialized metadata for keyword matching.
        """
        parts: list[str] = []
        title = entry.get("title", "")
        if title:
            parts.append(title)
        # Include tags in searchable text
        tags = entry.get("tags", [])
        if tags:
            parts.append(" ".join(tags))
        # Include metadata as serialized text
        metadata = entry.get("metadata", {})
        if metadata:
            parts.append(json.dumps(metadata, default=str))
        return " ".join(parts).lower()
