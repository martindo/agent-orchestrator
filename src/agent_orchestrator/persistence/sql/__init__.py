"""SQL persistence backend (SQLite + PostgreSQL) via SQLAlchemy Core.

This package provides the SQL-backed implementations of the persistence stores.
Selection between file / sqlite / postgresql is driven by the
``persistence_backend`` setting and resolved in
:mod:`agent_orchestrator.persistence.backend`.

The tables here are managed by SQLAlchemy ``metadata.create_all`` (portable
across SQLite and PostgreSQL) and are namespaced with an ``ao_`` prefix so they
never collide with the hand-written ``db/init/01_schema.sql`` relational schema.
Reconciling the two is tracked as a follow-up.
"""
