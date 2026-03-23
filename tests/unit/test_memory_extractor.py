"""Tests for MemoryExtractor — parse agent outputs and auto-extract completions."""
from __future__ import annotations

from typing import Any

import pytest

from agent_orchestrator.knowledge.extractor import MemoryExtractor
from agent_orchestrator.knowledge.models import MemoryType


class TestExtractFromAgentOutput:
    """Extract explicit memories from agent output."""

    def test_extract_valid_memories(self) -> None:
        output: dict[str, Any] = {
            "response": "Analysis complete",
            "confidence": 0.9,
            "memories": [
                {
                    "type": "decision",
                    "title": "Approved vendor X",
                    "content": {"vendor": "X", "rationale": "Best price"},
                    "tags": ["vendor-selection"],
                    "confidence": 0.95,
                },
                {
                    "type": "evidence",
                    "title": "Source verified",
                    "content": {"url": "https://example.com", "credibility": 0.8},
                },
            ],
        }
        records = MemoryExtractor.extract_from_agent_output(
            agent_id="agent-1",
            work_id="work-1",
            phase_id="research",
            run_id="run-1",
            app_id="app-1",
            output=output,
        )
        assert len(records) == 2
        assert records[0].memory_type == MemoryType.DECISION
        assert records[0].title == "Approved vendor X"
        assert records[0].confidence == 0.95
        assert records[0].source_agent_id == "agent-1"
        assert records[1].memory_type == MemoryType.EVIDENCE
        # Second memory should use output-level confidence as default
        assert records[1].confidence == 0.9

    def test_extract_no_memories_key(self) -> None:
        output: dict[str, Any] = {"response": "No memories here"}
        records = MemoryExtractor.extract_from_agent_output(
            agent_id="a", work_id="w", phase_id="p",
            run_id="r", app_id="app", output=output,
        )
        assert records == []

    def test_extract_empty_memories_list(self) -> None:
        output: dict[str, Any] = {"response": "ok", "memories": []}
        records = MemoryExtractor.extract_from_agent_output(
            agent_id="a", work_id="w", phase_id="p",
            run_id="r", app_id="app", output=output,
        )
        assert records == []

    def test_extract_skips_invalid_entries(self) -> None:
        output: dict[str, Any] = {
            "response": "ok",
            "confidence": 0.7,
            "memories": [
                {"type": "decision"},  # missing title and content
                {
                    "type": "strategy",
                    "title": "Valid one",
                    "content": {"approach": "incremental"},
                },
                "not a dict",  # invalid
            ],
        }
        records = MemoryExtractor.extract_from_agent_output(
            agent_id="a", work_id="w", phase_id="p",
            run_id="r", app_id="app", output=output,
        )
        assert len(records) == 1
        assert records[0].title == "Valid one"

    def test_extract_memories_not_a_list(self) -> None:
        output: dict[str, Any] = {"response": "ok", "memories": "not a list"}
        records = MemoryExtractor.extract_from_agent_output(
            agent_id="a", work_id="w", phase_id="p",
            run_id="r", app_id="app", output=output,
        )
        assert records == []

    def test_extract_default_confidence(self) -> None:
        output: dict[str, Any] = {
            "response": "ok",
            "memories": [
                {
                    "type": "artifact",
                    "title": "Report",
                    "content": {"report": "data"},
                },
            ],
        }
        records = MemoryExtractor.extract_from_agent_output(
            agent_id="a", work_id="w", phase_id="p",
            run_id="r", app_id="app", output=output,
        )
        assert len(records) == 1
        assert records[0].confidence == 0.5  # default when no output confidence


class TestExtractCompletionMemories:
    """Auto-extract from work item completion."""

    def test_extract_decision_and_strategy(self) -> None:
        results: dict[str, Any] = {
            "agent-1": {"response": "done", "confidence": 0.9},
            "agent-2": {"response": "done", "confidence": 0.8},
        }
        records = MemoryExtractor.extract_completion_memories(
            work_id="work-1",
            run_id="run-1",
            app_id="app-1",
            results=results,
            phases_completed=["research", "analysis"],
        )
        assert len(records) == 2

        decision = next(r for r in records if r.memory_type == MemoryType.DECISION)
        assert "completion" in decision.tags
        assert "auto-extracted" in decision.tags
        assert decision.source_agent_id == "system"

        strategy = next(r for r in records if r.memory_type == MemoryType.STRATEGY)
        assert "strategy" in strategy.tags
        assert strategy.content["phases_completed"] == ["research", "analysis"]

    def test_extract_empty_results(self) -> None:
        records = MemoryExtractor.extract_completion_memories(
            work_id="w", run_id="r", app_id="a",
            results={}, phases_completed=[],
        )
        assert len(records) == 2  # still creates decision + strategy
