"""ContextMemory — per-work-item conversation history tracking.

Stores conversation turns as CONVERSATION memory records in the
KnowledgeStore, enabling agents to access prior conversation context.

Thread-safe: Delegates all persistence to KnowledgeStore (which is thread-safe).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from agent_orchestrator.knowledge.models import MemoryQuery, MemoryRecord, MemoryType
from agent_orchestrator.knowledge.store import KnowledgeStore

logger = logging.getLogger(__name__)


def _compute_content_hash(content: dict[str, Any]) -> str:
    """Compute SHA-256 hex digest for a content dict."""
    serialized = json.dumps(content, sort_keys=True, default=str).encode()
    return hashlib.sha256(serialized).hexdigest()


class ContextMemory:
    """Per-work-item conversation history backed by KnowledgeStore.

    Each conversation turn is stored as a CONVERSATION-type memory record
    with tags that enable efficient filtering by work_id, phase_id, and
    agent_id.

    Args:
        knowledge_store: The backing knowledge store for persistence.
    """

    def __init__(self, knowledge_store: KnowledgeStore) -> None:
        self._store = knowledge_store

    def add_turn(
        self,
        work_id: str,
        agent_id: str,
        phase_id: str,
        role: str,
        content: str,
        run_id: str = "",
        app_id: str = "",
    ) -> MemoryRecord:
        """Store a conversation turn as a CONVERSATION memory record.

        Args:
            work_id: Work item identifier.
            agent_id: Agent that produced or received the turn.
            phase_id: Phase during which the turn occurred.
            role: Role of the speaker (e.g., "user", "assistant", "system").
            content: The text content of the turn.
            run_id: Current run identifier.
            app_id: Application identifier.

        Returns:
            The stored MemoryRecord.
        """
        turn_content: dict[str, Any] = {
            "role": role,
            "content": content,
            "agent_id": agent_id,
            "phase_id": phase_id,
            "work_id": work_id,
        }

        record = MemoryRecord(
            memory_id=str(uuid.uuid4()),
            memory_type=MemoryType.CONVERSATION,
            title=f"Turn: {role} ({agent_id})",
            content=turn_content,
            content_hash=_compute_content_hash(turn_content),
            tags=["conversation", work_id, phase_id],
            confidence=1.0,
            source_agent_id=agent_id,
            source_work_id=work_id,
            source_phase_id=phase_id,
            source_run_id=run_id,
            app_id=app_id,
            timestamp=datetime.now(timezone.utc),
        )

        self._store.store(record)
        logger.debug(
            "Stored conversation turn for work=%s agent=%s role=%s",
            work_id,
            agent_id,
            role,
        )
        return record

    def get_history(self, work_id: str, limit: int = 50) -> list[MemoryRecord]:
        """Retrieve conversation turns for a work item in chronological order.

        Args:
            work_id: Work item identifier.
            limit: Maximum number of turns to return.

        Returns:
            List of MemoryRecord objects sorted by timestamp ascending.
        """
        query = MemoryQuery(
            memory_type=MemoryType.CONVERSATION,
            work_id=work_id,
            tags=["conversation", work_id],
            limit=limit,
        )
        records = self._store.retrieve(query)
        # Sort chronologically (retrieve returns by score descending)
        records.sort(key=lambda r: r.timestamp)
        return records

    def get_agent_history(
        self, work_id: str, agent_id: str, limit: int = 20,
    ) -> list[MemoryRecord]:
        """Retrieve conversation turns for a specific agent on a work item.

        Args:
            work_id: Work item identifier.
            agent_id: Agent identifier to filter by.
            limit: Maximum number of turns to return.

        Returns:
            List of MemoryRecord objects sorted by timestamp ascending.
        """
        query = MemoryQuery(
            memory_type=MemoryType.CONVERSATION,
            work_id=work_id,
            agent_id=agent_id,
            tags=["conversation", work_id],
            limit=limit,
        )
        records = self._store.retrieve(query)
        records.sort(key=lambda r: r.timestamp)
        return records

    @staticmethod
    def format_history(records: list[MemoryRecord]) -> str:
        """Format conversation records as a readable transcript.

        Args:
            records: List of MemoryRecord objects to format.

        Returns:
            Multi-line string with each turn on its own line in the format
            ``[agent_id] role: content``.
        """
        lines: list[str] = []
        for record in records:
            role = record.content.get("role", "unknown")
            content = record.content.get("content", "")
            agent_id = record.content.get("agent_id", record.source_agent_id)
            lines.append(f"[{agent_id}] {role}: {content}")
        return "\n".join(lines)
