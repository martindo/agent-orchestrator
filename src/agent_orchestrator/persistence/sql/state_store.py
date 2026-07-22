"""SqlStateStore — SQL-backed namespaced runtime-state persistence.

Drop-in equivalent of the file-based
:class:`~agent_orchestrator.persistence.state_store.StateStore`: a namespaced
key/value store (save/load/delete/list/clear) with upsert semantics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Engine, select

from agent_orchestrator.exceptions import PersistenceError
from agent_orchestrator.persistence.sql.tables import state

logger = logging.getLogger(__name__)


class SqlStateStore:
    """Namespaced runtime-state persistence backed by a SQLAlchemy engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, namespace: str, data: Any) -> None:
        """Upsert JSON-serializable state under a namespace."""
        now = datetime.now(timezone.utc)
        try:
            with self._engine.begin() as conn:
                updated = conn.execute(
                    state.update()
                    .where(state.c.namespace == namespace)
                    .values(data=data, updated_at=now)
                )
                if updated.rowcount == 0:
                    conn.execute(
                        state.insert().values(
                            namespace=namespace, data=data, updated_at=now,
                        )
                    )
        except Exception as exc:
            raise PersistenceError(f"Failed to save state '{namespace}': {exc}") from exc

    def load(self, namespace: str) -> Any:
        """Return the state under a namespace, or None if absent."""
        with self._engine.connect() as conn:
            row = conn.execute(
                select(state.c.data).where(state.c.namespace == namespace)
            ).first()
        return row[0] if row is not None else None

    def delete(self, namespace: str) -> bool:
        """Delete a namespace; return True if it existed."""
        with self._engine.begin() as conn:
            result = conn.execute(state.delete().where(state.c.namespace == namespace))
        return result.rowcount > 0

    def list_namespaces(self) -> list[str]:
        """List all saved namespaces."""
        with self._engine.connect() as conn:
            rows = conn.execute(select(state.c.namespace)).all()
        return [r[0] for r in rows]

    def clear(self) -> None:
        """Delete all state."""
        with self._engine.begin() as conn:
            conn.execute(state.delete())
