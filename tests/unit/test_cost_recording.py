"""Real LLM cost/tokens recorded into metrics from agent runs (audit 4.5).

Providers return usage and cost_optimizer prices it, but nothing recorded it —
metrics.total_cost / total_tokens stayed 0. The engine now prices each run's
usage and records it.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_orchestrator.core.engine import OrchestrationEngine
from agent_orchestrator.core.event_bus import Event, EventType

from .test_core import _make_test_config_manager


@pytest.mark.asyncio
async def test_agent_completion_records_cost_and_tokens(tmp_path):
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    await engine.start()
    try:
        assert engine._metrics.total_cost == 0.0
        assert engine._metrics.total_tokens == 0.0

        await engine._event_bus.emit(Event(
            type=EventType.AGENT_COMPLETED,
            data={
                "agent_id": "agent-1",
                "model": "gpt-4o",
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
            source="test",
        ))
        await asyncio.sleep(0.05)

        assert engine._metrics.total_tokens == 1500
        # gpt-4o: input 0.0025/1k, output 0.01/1k → 0.0025 + 0.005 = 0.0075
        assert engine._metrics.total_cost == pytest.approx(0.0075)
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_no_usage_records_nothing(tmp_path):
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    await engine.start()
    try:
        await engine._event_bus.emit(Event(
            type=EventType.AGENT_COMPLETED,
            data={"agent_id": "agent-1", "model": "gpt-4o"},  # no usage
            source="test",
        ))
        await asyncio.sleep(0.05)
        assert engine._metrics.total_tokens == 0.0
        assert engine._metrics.total_cost == 0.0
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_unknown_model_records_tokens_but_zero_cost(tmp_path):
    engine = OrchestrationEngine(_make_test_config_manager(tmp_path))
    await engine.start()
    try:
        await engine._event_bus.emit(Event(
            type=EventType.AGENT_COMPLETED,
            data={
                "agent_id": "agent-1",
                "model": "made-up-model",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
            source="test",
        ))
        await asyncio.sleep(0.05)
        assert engine._metrics.total_tokens == 150   # tokens still counted
        assert engine._metrics.total_cost == 0.0      # unknown model → no price
    finally:
        await engine.stop()
