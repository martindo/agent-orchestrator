"""Persistent cache for LLM-generated domain catalogs.

Supports three storage backends (matching the runtime's deployment profile):
- **file** (lite) — YAML file at {workspace}/recommend-domains.yaml
- **sqlite** (standard-lite) — SQLite database at {workspace}/recommend-domains.db
- **postgresql** (standard/enterprise) — PostgreSQL table `domain_catalogs`

Backend is selected from the runtime's settings.yaml `persistence_backend` field.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol

import yaml

from studio.recommend.archetypes import Archetype, DomainCatalog

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_store: DomainCacheStore | None = None


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------

class DomainCacheStore(Protocol):
    """Backend-agnostic interface for domain catalog persistence."""

    def load_all(self) -> dict[str, DomainCatalog]: ...
    def save(self, catalog: DomainCatalog) -> None: ...
    def delete(self, domain: str) -> None: ...
    def list_domains(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# Serialization helpers (shared across backends)
# ---------------------------------------------------------------------------

def _serialize_catalog(catalog: DomainCatalog) -> dict[str, Any]:
    """Convert a DomainCatalog to a serializable dict."""
    return {
        "domain": catalog.domain,
        "trigger_keywords": list(catalog.trigger_keywords),
        "phase_order": list(catalog.phase_order),
        "archetypes": [
            {
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "system_prompt": a.system_prompt,
                "keywords": list(a.keywords),
                "default_phase": a.default_phase,
                "category": a.category,
                "skills": list(a.skills),
                "domain": a.domain,
            }
            for a in catalog.archetypes
        ],
    }


def _deserialize_catalog(data: dict[str, Any]) -> DomainCatalog | None:
    """Convert a dict back into a DomainCatalog."""
    domain = data.get("domain", "")
    if not domain:
        return None
    archetypes = []
    for a in data.get("archetypes", []):
        if not isinstance(a, dict) or not a.get("id"):
            continue
        archetypes.append(Archetype(
            id=a["id"],
            name=a.get("name", ""),
            description=a.get("description", ""),
            system_prompt=a.get("system_prompt", ""),
            keywords=a.get("keywords", []),
            default_phase=a.get("default_phase", ""),
            category=a.get("category", "domain"),
            skills=a.get("skills", []),
            domain=a.get("domain", domain),
        ))
    if not archetypes:
        return None
    return DomainCatalog(
        domain=domain,
        trigger_keywords=data.get("trigger_keywords", [domain]),
        archetypes=archetypes,
        phase_order=data.get("phase_order", []),
    )


# ---------------------------------------------------------------------------
# File backend (lite)
# ---------------------------------------------------------------------------

class FileDomainCacheStore:
    """YAML file-based domain catalog persistence."""

    def __init__(self, workspace_dir: Path) -> None:
        self._path = workspace_dir / "recommend-domains.yaml"

    def load_all(self) -> dict[str, DomainCatalog]:
        if not self._path.exists():
            return {}
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "domains" not in data:
                return {}
            result: dict[str, DomainCatalog] = {}
            for entry in data["domains"]:
                catalog = _deserialize_catalog(entry)
                if catalog:
                    result[catalog.domain] = catalog
            return result
        except Exception as exc:
            logger.warning("Failed to load domain cache from %s: %s", self._path, exc)
            return {}

    def save(self, catalog: DomainCatalog) -> None:
        # Load existing, merge, write back
        all_catalogs = self.load_all()
        all_catalogs[catalog.domain] = catalog
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            domains = [_serialize_catalog(c) for c in all_catalogs.values()]
            self._path.write_text(
                yaml.safe_dump({"domains": domains}, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save domain cache to %s: %s", self._path, exc)

    def delete(self, domain: str) -> None:
        all_catalogs = self.load_all()
        all_catalogs.pop(domain.lower(), None)
        try:
            domains = [_serialize_catalog(c) for c in all_catalogs.values()]
            self._path.write_text(
                yaml.safe_dump({"domains": domains}, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to delete domain from cache: %s", exc)

    def list_domains(self) -> list[str]:
        return list(self.load_all().keys())


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

class SqliteDomainCacheStore:
    """SQLite-based domain catalog persistence."""

    def __init__(self, workspace_dir: Path) -> None:
        self._db_path = workspace_dir / "recommend-domains.db"
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS domain_catalogs (
                    domain      TEXT PRIMARY KEY,
                    data        TEXT NOT NULL,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

    def load_all(self) -> dict[str, DomainCatalog]:
        result: dict[str, DomainCatalog] = {}
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT domain, data FROM domain_catalogs").fetchall()
            for domain, data_json in rows:
                data = json.loads(data_json)
                catalog = _deserialize_catalog(data)
                if catalog:
                    result[catalog.domain] = catalog
        except Exception as exc:
            logger.warning("Failed to load domains from SQLite: %s", exc)
        return result

    def save(self, catalog: DomainCatalog) -> None:
        data_json = json.dumps(_serialize_catalog(catalog))
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO domain_catalogs (domain, data, updated_at)
                       VALUES (?, ?, datetime('now'))
                       ON CONFLICT(domain) DO UPDATE SET data=excluded.data, updated_at=datetime('now')""",
                    (catalog.domain, data_json),
                )
        except Exception as exc:
            logger.warning("Failed to save domain to SQLite: %s", exc)

    def delete(self, domain: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM domain_catalogs WHERE domain = ?", (domain.lower(),))
        except Exception as exc:
            logger.warning("Failed to delete domain from SQLite: %s", exc)

    def list_domains(self) -> list[str]:
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT domain FROM domain_catalogs ORDER BY domain").fetchall()
            return [r[0] for r in rows]
        except Exception as exc:
            logger.warning("Failed to list domains from SQLite: %s", exc)
            return []


# ---------------------------------------------------------------------------
# PostgreSQL backend (enterprise)
# ---------------------------------------------------------------------------

class PostgresqlDomainCacheStore:
    """PostgreSQL-based domain catalog persistence.

    Connects to the same database as the runtime, using the
    `domain_catalogs` table.
    """

    def __init__(self, connection_string: str) -> None:
        self._dsn = connection_string
        self._ensure_table()

    def _connect(self) -> Any:
        try:
            import psycopg2
        except ImportError:
            raise RuntimeError(
                "psycopg2 is required for PostgreSQL persistence. "
                "Install with: pip install psycopg2-binary"
            )
        return psycopg2.connect(self._dsn)

    def _ensure_table(self) -> None:
        try:
            conn = self._connect()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS domain_catalogs (
                            domain      VARCHAR(128) PRIMARY KEY,
                            data        JSONB NOT NULL,
                            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
            conn.close()
        except Exception as exc:
            logger.warning("Failed to ensure domain_catalogs table: %s", exc)

    def load_all(self) -> dict[str, DomainCatalog]:
        result: dict[str, DomainCatalog] = {}
        try:
            conn = self._connect()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT domain, data FROM domain_catalogs")
                    rows = cur.fetchall()
            conn.close()
            for domain, data in rows:
                if isinstance(data, str):
                    data = json.loads(data)
                catalog = _deserialize_catalog(data)
                if catalog:
                    result[catalog.domain] = catalog
        except Exception as exc:
            logger.warning("Failed to load domains from PostgreSQL: %s", exc)
        return result

    def save(self, catalog: DomainCatalog) -> None:
        data_json = json.dumps(_serialize_catalog(catalog))
        try:
            conn = self._connect()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO domain_catalogs (domain, data, updated_at)
                           VALUES (%s, %s::jsonb, NOW())
                           ON CONFLICT (domain) DO UPDATE
                           SET data = EXCLUDED.data, updated_at = NOW()""",
                        (catalog.domain, data_json),
                    )
            conn.close()
        except Exception as exc:
            logger.warning("Failed to save domain to PostgreSQL: %s", exc)

    def delete(self, domain: str) -> None:
        try:
            conn = self._connect()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM domain_catalogs WHERE domain = %s", (domain.lower(),))
            conn.close()
        except Exception as exc:
            logger.warning("Failed to delete domain from PostgreSQL: %s", exc)

    def list_domains(self) -> list[str]:
        try:
            conn = self._connect()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT domain FROM domain_catalogs ORDER BY domain")
                    rows = cur.fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception as exc:
            logger.warning("Failed to list domains from PostgreSQL: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Factory & initialization
# ---------------------------------------------------------------------------

def _detect_backend(workspace_dir: Path) -> tuple[str, str]:
    """Read the runtime's settings.yaml to determine persistence backend.

    Returns (backend_name, postgresql_dsn).
    """
    settings_path = workspace_dir / "settings.yaml"
    if not settings_path.exists():
        # Try parent (studio workspace may be nested)
        settings_path = workspace_dir.parent / "workspace" / "settings.yaml"

    backend = "file"
    dsn = ""

    if settings_path.exists():
        try:
            data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                backend = data.get("persistence_backend", "file")
        except Exception:
            pass

    # Build PostgreSQL DSN from environment if needed
    if backend == "postgresql":
        import os
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        user = os.environ.get("POSTGRES_USER", "agent_orch")
        password = os.environ.get("POSTGRES_PASSWORD", "agent_orch_dev")
        db = os.environ.get("POSTGRES_DB", "agent_orchestrator")
        dsn = f"host={host} port={port} dbname={db} user={user} password={password}"

    return backend, dsn


def _create_store(backend: str, workspace_dir: Path, dsn: str) -> DomainCacheStore:
    """Create the appropriate store implementation."""
    if backend == "postgresql":
        logger.info("Using PostgreSQL backend for domain catalog cache")
        return PostgresqlDomainCacheStore(dsn)
    if backend == "sqlite":
        logger.info("Using SQLite backend for domain catalog cache")
        return SqliteDomainCacheStore(workspace_dir)
    logger.info("Using file backend for domain catalog cache")
    return FileDomainCacheStore(workspace_dir)


# ---------------------------------------------------------------------------
# In-memory cache + store
# ---------------------------------------------------------------------------

_cached_catalogs: dict[str, DomainCatalog] = {}


def init_storage(workspace_dir: Path) -> None:
    """Initialize persistence backend and load existing domains into memory."""
    global _store
    backend, dsn = _detect_backend(workspace_dir)
    _store = _create_store(backend, workspace_dir, dsn)

    # Load persisted domains into memory
    with _lock:
        _cached_catalogs.clear()
        _cached_catalogs.update(_store.load_all())

    logger.info(
        "Domain cache initialized (%s backend, %d domains loaded)",
        backend,
        len(_cached_catalogs),
    )


def get_cached(domain: str) -> DomainCatalog | None:
    """Look up a cached domain catalog (memory-first, then store)."""
    with _lock:
        return _cached_catalogs.get(domain.lower())


def cache_from_llm_result(llm_result: dict[str, Any]) -> DomainCatalog | None:
    """Convert an LLM generation result into a DomainCatalog, cache it, and persist.

    Returns the new catalog, or None if the result is invalid.
    """
    domain = llm_result.get("domain", "").lower().strip()
    if not domain:
        return None

    agents_data = llm_result.get("agents", [])
    if not agents_data:
        return None

    archetypes: list[Archetype] = []
    for a in agents_data:
        if not isinstance(a, dict):
            continue
        arch = Archetype(
            id=a.get("id", ""),
            name=a.get("name", ""),
            description=a.get("description", ""),
            system_prompt=a.get("system_prompt", ""),
            keywords=[],
            default_phase=a.get("default_phase", ""),
            category="domain",
            skills=a.get("skills", []),
            domain=domain,
        )
        if arch.id and arch.name:
            archetypes.append(arch)

    if not archetypes:
        return None

    phases_data = llm_result.get("phases", [])
    sorted_phases = sorted(
        phases_data,
        key=lambda p: p.get("order", 0) if isinstance(p, dict) else 0,
    )
    phase_order = [
        p.get("id", "")
        for p in sorted_phases
        if isinstance(p, dict) and p.get("id")
    ]

    catalog = DomainCatalog(
        domain=domain,
        trigger_keywords=[domain],
        archetypes=archetypes,
        phase_order=phase_order,
    )

    # Cache in memory
    with _lock:
        _cached_catalogs[domain] = catalog

    # Persist to store
    if _store:
        _store.save(catalog)

    logger.info(
        "Cached and persisted domain catalog: %s (%d archetypes, %d phases)",
        domain,
        len(archetypes),
        len(phase_order),
    )
    return catalog


def list_cached_domains() -> list[str]:
    """Return all cached domain names."""
    with _lock:
        return list(_cached_catalogs.keys())
