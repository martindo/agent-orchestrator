"""SQLAlchemy table definitions for the SQL persistence backends.

One shared ``MetaData`` covers every SQL-backed store. Tables use portable
column types (``JSON`` renders as JSONB on PostgreSQL and TEXT on SQLite) so a
single definition serves both backends via ``metadata.create_all``.

Document-style stores (work items, artifacts, ...) keep the canonical JSON
payload in a ``payload`` column plus a few promoted, indexed columns for the
filters the store API actually exposes. This gives real cross-process ACID
concurrency — the reason to move off the in-process-locked file stores — without
re-modelling the entire 30-table relational schema up front.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
)

metadata = MetaData()

# ---- Work items -------------------------------------------------------------

work_items = Table(
    "ao_work_items",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("type_id", String(128), nullable=False, default=""),
    Column("app_id", String(128), nullable=False, default="default"),
    Column("run_id", String(128), nullable=False, default=""),
    Column("status", String(32), nullable=False, index=True),
    Column("submitted_at", DateTime(timezone=True), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Index("ix_ao_work_items_type", "type_id"),
    Index("ix_ao_work_items_app", "app_id"),
    Index("ix_ao_work_items_run", "run_id"),
)

# ---- Artifacts --------------------------------------------------------------
#
# Content-addressable, append-per-store semantics (matching the file store's
# JSONL index): each store() is one row. The autoincrement row_id preserves
# insertion order for "latest entry" lookups and stable ordering on ties.

artifacts = Table(
    "ao_artifacts",
    metadata,
    Column("row_id", Integer, primary_key=True, autoincrement=True),
    Column("artifact_id", String(64), nullable=False),
    Column("work_id", String(128), nullable=False, index=True),
    Column("phase_id", String(128), nullable=False, default=""),
    Column("agent_id", String(128), nullable=False, default=""),
    Column("artifact_type", String(64), nullable=False, index=True),
    Column("content_hash", String(64), nullable=False, index=True),
    Column("version", Integer, nullable=False, default=1),
    Column("timestamp", DateTime(timezone=True), nullable=False, index=True),
    Column("run_id", String(128), nullable=False, default=""),
    Column("app_id", String(128), nullable=False, default=""),
    Column("content", JSON, nullable=False),
)
