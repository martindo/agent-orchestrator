"""The engine wires a real EmbeddingService into the knowledge store (audit 4.1).

EmbeddingService existed but was never instantiated, so semantic_query always
raised and retrieval fell back to keyword/tag overlap. The store's semantic
machinery is covered by test_knowledge_improvements.py; these cover the wiring.
"""

from __future__ import annotations

import pytest

from agent_orchestrator.configuration.models import SettingsConfig
from agent_orchestrator.core.engine import OrchestrationEngine
from agent_orchestrator.knowledge.embedding import EmbeddingService

from .test_core import _make_test_config_manager

_ENV_KEY = "AGENT_ORCH_EMBEDDING_API_KEY"


def test_no_key_means_no_service(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV_KEY, raising=False)
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    # Default test settings have no api_keys → semantic search stays disabled.
    assert engine._build_embedding_service() is None


def test_env_key_builds_service(tmp_path, monkeypatch):
    monkeypatch.setenv(_ENV_KEY, "sk-embed")
    monkeypatch.setenv("AGENT_ORCH_EMBEDDING_MODEL", "text-embedding-3-large")
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    svc = engine._build_embedding_service()
    assert isinstance(svc, EmbeddingService)
    assert svc._model == "text-embedding-3-large"


def test_settings_openai_key_builds_service(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV_KEY, raising=False)
    config = _make_test_config_manager(tmp_path)
    config.get_settings.return_value = SettingsConfig(
        active_profile="test", api_keys={"openai": "sk-openai"},
    )
    engine = OrchestrationEngine(config)
    assert isinstance(engine._build_embedding_service(), EmbeddingService)


@pytest.mark.asyncio
async def test_engine_start_wires_service_into_store(tmp_path, monkeypatch):
    monkeypatch.setenv(_ENV_KEY, "sk-embed")
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    await engine.start()
    try:
        assert engine._knowledge_store is not None
        # The store now has a real embedding service → semantic_query is live.
        assert engine._knowledge_store._embedding_service is not None
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_engine_start_without_key_leaves_store_keyword_only(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV_KEY, raising=False)
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    await engine.start()
    try:
        assert engine._knowledge_store is not None
        assert engine._knowledge_store._embedding_service is None  # honest fallback
    finally:
        await engine.stop()
