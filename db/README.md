# Database schema

## `schema.sql` — the live schema (generated)

`schema.sql` is the authoritative SQL persistence schema for the `sqlite` and
`postgresql` backends. It is **generated** from the SQLAlchemy metadata in
`src/agent_orchestrator/persistence/sql/tables.py` — the single source of truth.

Regenerate it after changing any table:

```bash
python -m agent_orchestrator.persistence.sql.schema postgresql > db/schema.sql
```

A drift-guard test (`tests/unit/test_persistence_backends.py`) fails if the
committed file and the metadata disagree.

You normally do **not** need to apply this file by hand: the application calls
`metadata.create_all` on startup, so the tables are created automatically for
whichever backend is selected. `schema.sql` exists for review and for DBAs who
want to pre-provision or inspect the schema.

The live schema currently covers the runtime stores that were moved onto SQL:
`ao_work_items`, `ao_artifacts`, `ao_state`. Configuration (profiles, agents,
workflows, governance) remains file/YAML-based, and some stores are
intentionally file-native (see `docs/AUDIT-TASKS.md` §4.4).

## `reference/` — aspirational full-relational design (not wired)

`reference/legacy_full_schema.sql` and `reference/legacy_seed.sql` are the
original hand-written ~30-table normalized schema. It modelled a future in which
*everything* — including configuration — lived in PostgreSQL. That design was
never wired to any code (no connection layer read it), so it is preserved here as
a **reference/design artifact**, not the live schema. It is not applied by the
app or by Docker. Pursuing it (e.g. moving configuration into the DB) is a
possible future project.
