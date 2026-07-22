"""Render the persistence schema DDL from the SQLAlchemy metadata.

The metadata in :mod:`agent_orchestrator.persistence.sql.tables` is the single
source of truth for the SQL persistence schema. At runtime the app materializes
it with ``metadata.create_all``; this module renders the equivalent DDL as text
for review / ops (``db/schema.sql`` is generated from it and kept in sync by a
drift-guard test).

Usage::

    python -m agent_orchestrator.persistence.sql.schema [postgresql|sqlite]
"""

from __future__ import annotations

import sys

from sqlalchemy import create_mock_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from agent_orchestrator.persistence.sql.tables import metadata

_DRIVERS = {
    "postgresql": "postgresql+psycopg://",
    "sqlite": "sqlite://",
}

_HEADER = (
    "-- =============================================================================\n"
    "-- Agent Orchestrator -- SQL persistence schema ({dialect})\n"
    "-- =============================================================================\n"
    "-- GENERATED from agent_orchestrator/persistence/sql/tables.py -- do not edit by\n"
    "-- hand. Regenerate with:\n"
    "--   python -m agent_orchestrator.persistence.sql.schema {dialect} > db/schema.sql\n"
    "-- The application also creates these tables on startup via metadata.create_all,\n"
    "-- so applying this file is optional (it exists for review and ops).\n"
    "-- =============================================================================\n\n"
)


def render_create_sql(dialect: str = "postgresql") -> str:
    """Return the CREATE TABLE/INDEX DDL for the persistence schema.

    Output is deterministic: tables in metadata (dependency) order, and each
    table's indexes sorted by name — so the generated file is stable across
    processes (index emission from create_all is otherwise set-ordered).
    """
    if dialect not in _DRIVERS:
        raise ValueError(f"Unsupported dialect: {dialect!r} (expected one of {list(_DRIVERS)})")

    engine = create_mock_engine(_DRIVERS[dialect], lambda *a, **k: None)
    dial = engine.dialect

    statements: list[str] = []
    for table in metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dial)).strip())
        for index in sorted(table.indexes, key=lambda ix: ix.name or ""):
            statements.append(str(CreateIndex(index).compile(dialect=dial)).strip())

    body = ";\n\n".join(s for s in statements if s)
    return _HEADER.format(dialect=dialect) + body + ";\n"


def main() -> None:
    dialect = sys.argv[1] if len(sys.argv) > 1 else "postgresql"
    sys.stdout.write(render_create_sql(dialect))


if __name__ == "__main__":
    main()
