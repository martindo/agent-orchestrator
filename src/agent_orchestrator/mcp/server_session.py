"""MCP Server Session Management — tracks active client sessions with TTL."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCPSessionContext:
    """Runtime context for an active MCP client session."""

    session_id: str
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_call_count: int = 0

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.monotonic()

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if session has exceeded TTL."""
        return (time.monotonic() - self.last_activity) > ttl_seconds


class MCPSessionRegistry:
    """Thread-safe registry for active MCP client sessions.

    Tracks session context and enforces TTL expiration and max session limits.
    """

    def __init__(self, ttl_seconds: int = 3600, max_sessions: int = 100) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, MCPSessionContext] = {}
        self._lock = threading.Lock()

    def create_session(self, session_id: str, metadata: dict[str, Any] | None = None) -> MCPSessionContext:
        """Create and register a new session.

        Args:
            session_id: Unique session identifier.
            metadata: Optional session metadata.

        Returns:
            The created MCPSessionContext.

        Raises:
            ValueError: If max sessions exceeded.
        """
        with self._lock:
            self._evict_expired()
            if len(self._sessions) >= self._max_sessions:
                msg = f"Maximum sessions ({self._max_sessions}) exceeded"
                raise ValueError(msg)
            session = MCPSessionContext(
                session_id=session_id,
                metadata=metadata or {},
            )
            self._sessions[session_id] = session
            logger.debug("Created MCP session '%s'", session_id)
            return session

    def get_session(self, session_id: str) -> MCPSessionContext | None:
        """Get a session by ID, returning None if expired or not found."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.is_expired(self._ttl_seconds):
                del self._sessions[session_id]
                return None
            session.touch()
            return session

    def remove_session(self, session_id: str) -> bool:
        """Remove a session.

        Returns:
            True if session was found and removed.
        """
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> list[MCPSessionContext]:
        """List all active (non-expired) sessions."""
        with self._lock:
            self._evict_expired()
            return list(self._sessions.values())

    @property
    def active_count(self) -> int:
        """Count of active sessions."""
        with self._lock:
            self._evict_expired()
            return len(self._sessions)

    def _evict_expired(self) -> None:
        """Remove expired sessions (must hold lock)."""
        expired = [
            sid for sid, s in self._sessions.items()
            if s.is_expired(self._ttl_seconds)
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.debug("Evicted expired MCP session '%s'", sid)
