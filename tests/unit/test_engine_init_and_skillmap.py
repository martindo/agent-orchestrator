"""Engine init-failure logging (1.3) + skill-map learns from real runs (3.7)."""

from __future__ import annotations

import asyncio
import logging

import pytest

from agent_orchestrator.catalog.skill_models import SkillRecord
from agent_orchestrator.core.engine import OrchestrationEngine
from agent_orchestrator.core.event_bus import Event, EventType

from .test_core import _make_test_config_manager


# ---- 1.3: init failures are logged loudly, not swallowed at debug ------------


@pytest.mark.asyncio
async def test_failed_store_init_logs_error(tmp_path, monkeypatch, caplog):
    def _boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    # Make the rubric store init fail; the engine must continue but log ERROR.
    monkeypatch.setattr(
        "agent_orchestrator.simulation.rubric_store.RubricStore", _boom,
    )
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    with caplog.at_level(logging.ERROR, logger="agent_orchestrator.core.engine"):
        await engine.start()
        try:
            assert engine._rubric_store is None  # degraded, but…
            assert any(
                "Rubric store initialization failed" in r.message
                and r.levelno == logging.ERROR
                for r in caplog.records
            ), "init failure should be logged at ERROR, not swallowed at debug"
        finally:
            await engine.stop()


# ---- 3.7: agent completion feeds the skill map ------------------------------


@pytest.mark.asyncio
async def test_agent_completion_records_skill_and_emits_update(tmp_path):
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    await engine.start()
    try:
        assert engine._skill_map is not None
        engine._skill_map.register_skill(SkillRecord(skill_id="python", name="Python"))

        updates: list[Event] = []

        async def _capture(event: Event) -> None:
            updates.append(event)

        engine._event_bus.subscribe(EventType.SKILL_UPDATED, _capture)

        await engine._event_bus.emit(Event(
            type=EventType.AGENT_COMPLETED,
            data={
                "agent_id": "agent-1",
                "skills": ["python"],
                "success": True,
                "confidence": 0.9,
                "duration": 1.5,
            },
            source="test",
        ))
        await asyncio.sleep(0.05)  # let async handlers run

        # SKILL_UPDATED emitted, and the skill recorded the agent's execution.
        assert len(updates) == 1
        assert updates[0].data["skills"] == ["python"]
        skill = engine._skill_map.get_skill("python")
        assert "agent-1" in skill.agent_metrics
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_unknown_skill_is_ignored(tmp_path):
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    await engine.start()
    try:
        updates: list[Event] = []

        async def _capture(event: Event) -> None:
            updates.append(event)

        engine._event_bus.subscribe(EventType.SKILL_UPDATED, _capture)
        await engine._event_bus.emit(Event(
            type=EventType.AGENT_COMPLETED,
            data={"agent_id": "agent-1", "skills": ["nonexistent"], "success": True,
                  "confidence": 0.5, "duration": 1.0},
            source="test",
        ))
        await asyncio.sleep(0.05)
        assert updates == []  # nothing recorded → no SKILL_UPDATED
    finally:
        await engine.stop()
