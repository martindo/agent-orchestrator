"""Tests for engine knowledge integration — injection, extraction, round-trip."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    GovernanceConfig,
    LLMConfig,
    ProfileConfig,
    SettingsConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
)
from agent_orchestrator.core.engine import OrchestrationEngine
from agent_orchestrator.core.event_bus import Event, EventType
from agent_orchestrator.core.work_queue import WorkItem
from agent_orchestrator.knowledge.models import MemoryQuery, MemoryRecord, MemoryType
from agent_orchestrator.knowledge.store import KnowledgeStore


def _make_config_mgr(workspace_dir: Path) -> MagicMock:
    """Create a mock ConfigurationManager for engine tests."""
    config_mgr = MagicMock()
    config_mgr.workspace_dir = workspace_dir

    profile = ProfileConfig(
        name="test",
        agents=[
            AgentDefinition(
                id="worker",
                name="Worker",
                system_prompt="You are a worker",
                phases=["process"],
                llm=LLMConfig(provider="openai", model="gpt-4o"),
            ),
        ],
        workflow=WorkflowConfig(
            name="test-workflow",
            phases=[
                WorkflowPhaseConfig(
                    id="process", name="Process", order=1,
                    agents=["worker"], on_success="done",
                ),
                WorkflowPhaseConfig(
                    id="done", name="Done", order=2,
                    agents=[], is_terminal=True,
                ),
            ],
        ),
        governance=GovernanceConfig(),
    )
    config_mgr.get_profile.return_value = profile
    config_mgr.get_settings.return_value = SettingsConfig(active_profile="test")
    return config_mgr


async def _mock_llm_call(
    system_prompt: str, user_prompt: str, llm_config: Any,
) -> dict[str, Any]:
    return {"response": "mock", "confidence": 0.85}


class TestKnowledgeStoreInit:
    """Engine initializes KnowledgeStore on start."""

    @pytest.mark.asyncio()
    async def test_knowledge_store_created_on_start(self, tmp_path: Path) -> None:
        config_mgr = _make_config_mgr(tmp_path)
        engine = OrchestrationEngine(config_mgr, llm_call_fn=_mock_llm_call)
        await engine.start()
        try:
            assert engine.knowledge_store is not None
            assert isinstance(engine.knowledge_store, KnowledgeStore)
        finally:
            await engine.stop()


class TestKnowledgeInjection:
    """Knowledge is injected into phase context."""

    @pytest.mark.asyncio()
    async def test_build_knowledge_context_returns_records(self, tmp_path: Path) -> None:
        config_mgr = _make_config_mgr(tmp_path)
        engine = OrchestrationEngine(config_mgr, llm_call_fn=_mock_llm_call)
        await engine.start()
        try:
            store = engine.knowledge_store
            assert store is not None

            # Store a memory with matching tag
            import hashlib
            import json
            from uuid import uuid4

            content = {"finding": "important"}
            record = MemoryRecord(
                memory_id=str(uuid4()),
                memory_type=MemoryType.EVIDENCE,
                title="Prior finding",
                content=content,
                content_hash=hashlib.sha256(
                    json.dumps(content, sort_keys=True, default=str).encode()
                ).hexdigest(),
                tags=["process"],  # matches phase id
                confidence=0.9,
                source_agent_id="prev-agent",
                source_work_id="prev-work",
                source_phase_id="research",
                source_run_id="prev-run",
                app_id="app-1",
                timestamp=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
                expires_at=None,
                superseded_by=None,
                version=1,
                metadata={},
            )
            store.store(record)

            # Build knowledge context for a matching phase
            phase = config_mgr.get_profile().workflow.phases[0]
            work_item = WorkItem(
                id="test-work-1",
                type_id="test",
                title="Test work",
                data={},
                app_id="app-1",
            )
            ctx = engine._build_knowledge_context(work_item, phase)
            assert len(ctx) == 1
            assert ctx[0]["title"] == "Prior finding"
        finally:
            await engine.stop()


class TestAgentMemoryExtraction:
    """Agent outputs with memories key trigger extraction."""

    @pytest.mark.asyncio()
    async def test_extract_agent_memories_on_event(self, tmp_path: Path) -> None:
        config_mgr = _make_config_mgr(tmp_path)
        engine = OrchestrationEngine(config_mgr, llm_call_fn=_mock_llm_call)
        await engine.start()
        try:
            store = engine.knowledge_store
            assert store is not None

            # Simulate AGENT_COMPLETED event with memories
            event = Event(
                type=EventType.AGENT_COMPLETED,
                data={
                    "agent_id": "worker",
                    "work_id": "w1",
                    "phase_id": "process",
                    "output": {
                        "response": "done",
                        "confidence": 0.9,
                        "memories": [
                            {
                                "type": "decision",
                                "title": "Key decision",
                                "content": {"choice": "A"},
                                "tags": ["test-tag"],
                                "confidence": 0.95,
                            }
                        ],
                    },
                },
                source="test",
                run_id="run-1",
                app_id="app-1",
            )
            await engine._extract_agent_memories(event)

            # Verify stored
            results = store.retrieve(MemoryQuery(tags=["test-tag"]))
            assert len(results) == 1
            assert results[0].title == "Key decision"
        finally:
            await engine.stop()


class TestCompletionExtraction:
    """Work completion triggers auto-extraction."""

    @pytest.mark.asyncio()
    async def test_auto_extract_on_work_completed(self, tmp_path: Path) -> None:
        config_mgr = _make_config_mgr(tmp_path)
        engine = OrchestrationEngine(config_mgr, llm_call_fn=_mock_llm_call)
        await engine.start()
        try:
            store = engine.knowledge_store
            assert store is not None

            # Create a work item with results
            work_item = WorkItem(
                id="completed-work-1",
                type_id="test", title="Completed work",
                data={}, app_id="app-1", run_id="run-1",
            )
            work_item.results = {
                "worker": {"response": "done", "confidence": 0.9},
            }
            # Submit to queue so engine can find it
            await engine.submit_work(work_item)

            # Simulate WORK_COMPLETED event
            event = Event(
                type=EventType.WORK_COMPLETED,
                data={"work_id": work_item.id},
                source="test",
                run_id="run-1",
                app_id="app-1",
            )
            await engine._auto_extract_completion_memories(event)

            # Should have decision + strategy memories
            results = store.retrieve(MemoryQuery(tags=["auto-extracted"]))
            assert len(results) == 2
            types = {r.memory_type for r in results}
            assert MemoryType.DECISION in types
            assert MemoryType.STRATEGY in types
        finally:
            await engine.stop()
