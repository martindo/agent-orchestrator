"""Tests that real agent confidence flows into governance (audit 3.1).

Previously providers returned no confidence, so extract_confidence always gave
the 0.5 default and confidence-gating governance was inert. Agents are now asked
to self-report `CONFIDENCE: <0..1>` and the executor parses it into the output
dict so extract_confidence / aggregate_confidence see real values.
"""

from __future__ import annotations

import pytest

from agent_orchestrator.configuration.models import AgentDefinition, LLMConfig
from agent_orchestrator.core.agent_executor import (
    AgentExecutor,
    _attach_confidence,
    _build_user_prompt,
)
from agent_orchestrator.core.agent_pool import AgentInstance
from agent_orchestrator.core.output_parser import (
    aggregate_confidence,
    extract_confidence,
    parse_confidence,
)
from agent_orchestrator.core.quality_gate import build_gate_context
from agent_orchestrator.core.work_queue import WorkItem
from agent_orchestrator.governance.governor import Governor, Resolution


# ---- parse_confidence -------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Answer.\nCONFIDENCE: 0.85", 0.85),
        ('{"result": "x", "confidence": 0.3}', 0.3),
        ("My confidence is 0.7 overall", 0.7),
        ("confidence=0.9", 0.9),
        ("CONFIDENCE: 1", 1.0),
        ("CONFIDENCE: 0", 0.0),
        ("Done. CONFIDENCE: .42", 0.42),
        ("no marker here", None),
        ("", None),
    ],
)
def test_parse_confidence(text, expected):
    assert parse_confidence(text) == expected


def test_parse_confidence_takes_last_and_clamps():
    # Restated values: the final marker wins; >1 is clamped.
    assert parse_confidence("confidence 0.2 ... final CONFIDENCE: 0.95") == 0.95
    assert parse_confidence("CONFIDENCE: 1.5") == 1.0


# ---- _attach_confidence -----------------------------------------------------


def test_attach_parses_from_response_text():
    out = _attach_confidence({"response": "Answer.\nCONFIDENCE: 0.2", "model": "m"})
    assert out["confidence"] == 0.2


def test_attach_leaves_existing_confidence():
    out = _attach_confidence({"response": "x\nCONFIDENCE: 0.2", "confidence": 0.9})
    assert out["confidence"] == 0.9  # explicit value not overwritten


def test_attach_adds_nothing_when_absent():
    out = _attach_confidence({"response": "plain answer", "model": "m"})
    assert "confidence" not in out  # not fabricated


# ---- prompt instruction -----------------------------------------------------


def test_prompt_requests_confidence():
    prompt = _build_user_prompt(WorkItem(id="w", type_id="t", title="T"), "p1", {})
    assert "CONFIDENCE:" in prompt


# ---- end-to-end through the executor ----------------------------------------


def _instance() -> AgentInstance:
    defn = AgentDefinition(
        id="a", name="A", system_prompt="sp", phases=["p1"],
        llm=LLMConfig(provider="openai", model="gpt-4o"),
    )
    return AgentInstance(instance_id="a-1", definition=defn)


@pytest.mark.asyncio
async def test_executor_attaches_real_confidence():
    async def llm(**kwargs) -> dict:
        return {"response": "I am not sure about this.\nCONFIDENCE: 0.15", "model": "m"}

    result = await AgentExecutor(llm_call_fn=llm).execute(
        _instance(), WorkItem(id="w1", type_id="task", title="T"), "p1",
    )
    assert result.success
    assert result.output["confidence"] == 0.15


@pytest.mark.asyncio
async def test_low_confidence_reaches_governance_signal():
    """A low self-reported confidence must survive extraction+aggregation
    (not be flattened to the 0.5 default) so governance can act on it."""
    async def llm(**kwargs) -> dict:
        return {"response": "unsure\nCONFIDENCE: 0.1", "model": "m"}

    result = await AgentExecutor(llm_call_fn=llm).execute(
        _instance(), WorkItem(id="w1", type_id="task", title="T"), "p1",
    )
    conf = extract_confidence(result.output)
    assert conf == 0.1
    assert aggregate_confidence([conf]) == 0.1  # not the inert 0.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker,expected",
    [
        ("CONFIDENCE: 0.05", Resolution.ABORT),            # < abort (0.2)
        ("CONFIDENCE: 0.3", Resolution.QUEUE_FOR_REVIEW),  # < review (0.5)
        ("CONFIDENCE: 0.95", Resolution.ALLOW),            # >= auto_approve (0.8)
    ],
)
async def test_confidence_drives_governance_end_to_end(marker, expected):
    """The whole path: agent self-report → executor → extract/aggregate →
    gate context → Governor. Before this wiring confidence was always 0.5, so
    the outcome was a fixed ALLOW_WITH_WARNING and ABORT/QUEUE never fired."""
    async def llm(**kwargs) -> dict:
        return {"response": f"answer\n{marker}", "model": "m"}

    result = await AgentExecutor(llm_call_fn=llm).execute(
        _instance(), WorkItem(id="w1", type_id="task", title="T"), "p1",
    )
    agg = aggregate_confidence([extract_confidence(result.output)])
    context = build_gate_context([result], agg)
    decision = Governor().evaluate(context)
    assert decision.resolution == expected
