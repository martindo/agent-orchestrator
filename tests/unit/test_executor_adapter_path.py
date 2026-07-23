"""End-to-end AgentExecutor → LLMAdapter → provider tests (audit 5.4).

The existing core-execution tests run AgentExecutor with no llm_call_fn and
assert the mock stub's value (confidence == 0.85). These exercise the *real*
adapter path: a real LLMAdapter routing to a mocked provider SDK, so the
executor→adapter→provider wiring (model, messages, params, response, parsed
confidence) is covered.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent_orchestrator.adapters.llm_adapter import LLMAdapter
from agent_orchestrator.configuration.models import (
    AgentDefinition,
    LLMConfig,
    SettingsConfig,
)
from agent_orchestrator.core.agent_executor import AgentExecutor
from agent_orchestrator.core.agent_pool import AgentInstance
from agent_orchestrator.core.work_queue import WorkItem


def _instance(provider: str = "openai", model: str = "gpt-4o") -> AgentInstance:
    defn = AgentDefinition(
        id="a", name="A", system_prompt="You are A.", phases=["p1"],
        llm=LLMConfig(provider=provider, model=model, temperature=0.4, max_tokens=1234),
    )
    return AgentInstance(instance_id="a-1", definition=defn)


@pytest.mark.asyncio
async def test_executor_runs_through_real_adapter_to_provider():
    adapter = LLMAdapter(SettingsConfig(active_profile="test"))
    provider = AsyncMock()
    provider.complete = AsyncMock(return_value={
        "response": "real answer\nCONFIDENCE: 0.42",
        "model": "gpt-4o",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })
    adapter.register_provider("openai", provider)

    executor = AgentExecutor(llm_call_fn=adapter.call)
    result = await executor.execute(
        _instance(), WorkItem(id="w1", type_id="task", title="T"), "p1",
    )

    assert result.success
    # Output came from the provider, not the 0.85 stub.
    assert result.output["response"] == "real answer\nCONFIDENCE: 0.42"
    assert result.output["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}
    # Confidence parsed from the real response (audit 3.1 wiring).
    assert result.output["confidence"] == 0.42


@pytest.mark.asyncio
async def test_provider_receives_model_messages_and_params():
    adapter = LLMAdapter(SettingsConfig(active_profile="test"))
    provider = AsyncMock()
    provider.complete = AsyncMock(return_value={"response": "ok", "model": "gpt-4o"})
    adapter.register_provider("openai", provider)

    await AgentExecutor(llm_call_fn=adapter.call).execute(
        _instance(), WorkItem(id="w1", type_id="task", title="T"), "p1",
    )

    provider.complete.assert_awaited_once()
    kwargs = provider.complete.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["temperature"] == 0.4
    assert kwargs["max_tokens"] == 1234
    roles = [m["role"] for m in kwargs["messages"]]
    assert roles == ["system", "user"]
    assert kwargs["messages"][0]["content"] == "You are A."


@pytest.mark.asyncio
async def test_unregistered_provider_fails_loudly_through_adapter():
    # Real adapter with no provider registered → agent execution fails (no stub).
    adapter = LLMAdapter(SettingsConfig(active_profile="test"))
    executor = AgentExecutor(llm_call_fn=adapter.call)
    result = await executor.execute(
        _instance(provider="openai"),
        WorkItem(id="w1", type_id="task", title="T"), "p1",
    )
    assert result.success is False
    assert "No LLM provider registered" in (result.error or "")
