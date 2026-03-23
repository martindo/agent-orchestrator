"""Data models for the knowledge subsystem.

Defines memory record types, query filters, and the core MemoryRecord
dataclass used by KnowledgeStore for persistence and retrieval.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MemoryType(str, Enum):
    """Classification of memory records stored in the knowledge subsystem."""

    EVIDENCE = "evidence"
    DECISION = "decision"
    STRATEGY = "strategy"
    ARTIFACT = "artifact"
    CONVERSATION = "conversation"


@dataclass
class MemoryRecord:
    """A single knowledge record persisted by the knowledge store.

    Records are content-addressed (via content_hash) and support
    versioning through the superseded_by chain.
    """

    memory_id: str
    memory_type: MemoryType
    title: str
    content: dict[str, Any]
    content_hash: str
    tags: list[str]
    confidence: float
    source_agent_id: str
    source_work_id: str
    source_phase_id: str
    source_run_id: str
    app_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    superseded_by: str | None = None
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryQuery:
    """Filter criteria for retrieving memory records from the knowledge store.

    All filter fields are optional; when set they narrow the result set.
    Results are scored by tag/keyword overlap weighted by confidence.
    """

    memory_type: MemoryType | None = None
    tags: list[str] | None = None
    keywords: list[str] | None = None
    agent_id: str | None = None
    work_id: str | None = None
    app_id: str | None = None
    min_confidence: float = 0.0
    include_expired: bool = False
    limit: int = 20
