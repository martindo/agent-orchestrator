"""SqlWorkItemStore — SQL-backed work item persistence (SQLite + PostgreSQL).

Implements the same interface as the file-based
:class:`~agent_orchestrator.persistence.work_item_store.WorkItemStore` and reuses
its serialization helpers, so the two are drop-in interchangeable. Selection is
handled by :mod:`agent_orchestrator.persistence.backend`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, and_, func, select

from agent_orchestrator.core.work_queue import TERMINAL_STATUSES, WorkItem, WorkItemStatus
from agent_orchestrator.exceptions import PersistenceError
from agent_orchestrator.persistence.sql.tables import work_items
from agent_orchestrator.persistence.work_item_store import (
    _dict_to_work_item,
    _work_item_to_dict,
)

logger = logging.getLogger(__name__)


class SqlWorkItemStore:
    """Work item persistence backed by a SQLAlchemy engine.

    Each work item is stored as one row: a small set of promoted, indexed
    columns for querying plus the canonical JSON payload. ``save`` is an upsert
    keyed on the work item id.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _row_from_item(item: WorkItem) -> dict[str, Any]:
        record = _work_item_to_dict(item)
        return {
            "id": record["id"],
            "type_id": record.get("type_id", ""),
            "app_id": record.get("app_id", "default"),
            "run_id": record.get("run_id", ""),
            "status": record["status"],
            "submitted_at": datetime.fromisoformat(record["submitted_at"]),
            "payload": record,
        }

    def save(self, work_item: WorkItem) -> None:
        """Insert or update a work item (upsert on id)."""
        row = self._row_from_item(work_item)
        try:
            with self._engine.begin() as conn:
                updated = conn.execute(
                    work_items.update()
                    .where(work_items.c.id == row["id"])
                    .values(**{k: v for k, v in row.items() if k != "id"})
                )
                if updated.rowcount == 0:
                    conn.execute(work_items.insert().values(**row))
        except Exception as exc:  # SQLAlchemyError and friends
            raise PersistenceError(f"Failed to save work item: {exc}") from exc

    def load(self, work_id: str) -> WorkItem | None:
        """Load a specific work item by id."""
        with self._engine.connect() as conn:
            row = conn.execute(
                select(work_items.c.payload).where(work_items.c.id == work_id)
            ).first()
        if row is None:
            return None
        return _dict_to_work_item(row[0])

    def query(
        self,
        *,
        status: WorkItemStatus | None = None,
        type_id: str | None = None,
        app_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[WorkItem]:
        """Query work items with optional filters, newest first."""
        conditions = []
        if status is not None:
            conditions.append(work_items.c.status == status.value)
        if type_id is not None:
            conditions.append(work_items.c.type_id == type_id)
        if app_id is not None:
            conditions.append(work_items.c.app_id == app_id)
        if run_id is not None:
            conditions.append(work_items.c.run_id == run_id)

        stmt = select(work_items.c.payload)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(work_items.c.submitted_at.desc()).limit(limit)

        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return [_dict_to_work_item(r[0]) for r in rows]

    def get_incomplete(self) -> list[WorkItem]:
        """Get all non-terminal work items (for crash recovery), oldest first."""
        stmt = (
            select(work_items.c.payload)
            .where(work_items.c.status.notin_(tuple(TERMINAL_STATUSES)))
            .order_by(work_items.c.submitted_at.asc())
        )
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return [_dict_to_work_item(r[0]) for r in rows]

    def summary(self) -> dict[str, Any]:
        """Return counts by status and type."""
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        with self._engine.connect() as conn:
            total = conn.execute(
                select(func.count()).select_from(work_items)
            ).scalar_one()
            for value, count in conn.execute(
                select(work_items.c.status, func.count()).group_by(work_items.c.status)
            ).all():
                by_status[value] = count
            for value, count in conn.execute(
                select(work_items.c.type_id, func.count()).group_by(work_items.c.type_id)
            ).all():
                by_type[value] = count

        return {"total": total, "by_status": by_status, "by_type": by_type}
