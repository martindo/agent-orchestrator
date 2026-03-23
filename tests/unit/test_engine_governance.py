"""Tests for engine governance with real confidence scores and review completion."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    DelegatedAuthorityConfig,
    GovernanceConfig,
    LLMConfig,
    ProfileConfig,
    SettingsConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
)
from agent_orchestrator.core.engine import OrchestrationEngine
from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus
from agent_orchestrator.governance.review_queue import ReviewQueue


def _make_config_mgr(
    workspace_dir: Path,
    profile: ProfileConfig | None = None,
) -> MagicMock:
    """Create a mock ConfigurationManager for engine tests."""
    config_mgr = MagicMock()
    config_mgr.workspace_dir = workspace_dir

    if profile is None:
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
            governance=GovernanceConfig(
                delegated_authority=DelegatedAuthorityConfig(
                    auto_approve_threshold=0.8,
                    review_threshold=0.5,
                    abort_threshold=0.2,
                ),
            ),
        )

    config_mgr.get_profile.return_value = profile
    config_mgr.get_settings.return_value = SettingsConfig(active_profile="test")
    config_mgr.load.return_value = None
    return config_mgr


class TestReviewQueueDecision:
    """Tests for review queue with decision field."""

    def test_complete_review_approved(self) -> None:
        """Review completion with approved decision."""
        queue = ReviewQueue()
        review_id = queue.enqueue("w1", "phase1", "Low confidence")
        assert queue.complete_review(review_id, "admin", decision="approved")
        item = queue.get_item(review_id)
        assert item is not None
        assert item.decision == "approved"
        assert item.reviewed is True
        assert item.reviewed_by == "admin"

    def test_complete_review_rejected(self) -> None:
        """Review completion with rejected decision."""
        queue = ReviewQueue()
        review_id = queue.enqueue("w1", "phase1", "Suspicious")
        assert queue.complete_review(review_id, "reviewer", decision="rejected")
        item = queue.get_item(review_id)
        assert item is not None
        assert item.decision == "rejected"

    def test_complete_review_default_approved(self) -> None:
        """Default decision is 'approved' for backward compat."""
        queue = ReviewQueue()
        review_id = queue.enqueue("w1", "phase1", "Test")
        assert queue.complete_review(review_id, "admin")
        item = queue.get_item(review_id)
        assert item is not None
        assert item.decision == "approved"

    def test_complete_review_not_found(self) -> None:
        """Completing nonexistent review returns False."""
        queue = ReviewQueue()
        assert queue.complete_review("nonexistent", "admin") is False

    def test_get_completed(self) -> None:
        """get_completed returns only reviewed items."""
        queue = ReviewQueue()
        r1 = queue.enqueue("w1", "p1", "reason1")
        r2 = queue.enqueue("w2", "p2", "reason2")
        queue.complete_review(r1, "admin", decision="approved")

        completed = queue.get_completed()
        assert len(completed) == 1
        assert completed[0].id == r1

        pending = queue.get_pending()
        assert len(pending) == 1
        assert pending[0].id == r2

    def test_review_notes_preserved(self) -> None:
        """Review notes are stored."""
        queue = ReviewQueue()
        review_id = queue.enqueue("w1", "p1", "test")
        queue.complete_review(review_id, "admin", notes="Looks good", decision="approved")
        item = queue.get_item(review_id)
        assert item is not None
        assert item.review_notes == "Looks good"


class TestEngineRealConfidence:
    """Tests for engine passing real confidence to Governor."""

    @pytest.mark.asyncio
    async def test_high_confidence_auto_approved(self, tmp_path: Path) -> None:
        """Agent output with high confidence passes governance automatically."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "processed", "confidence": 0.95}

        config_mgr = _make_config_mgr(tmp_path)
        engine = OrchestrationEngine(config_mgr, llm_call_fn=mock_llm)
        await engine.start()

        try:
            work = WorkItem(id="w1", type_id="task", title="Test")
            await engine.submit_work(work)
            await asyncio.sleep(1.5)

            assert work.status == WorkItemStatus.COMPLETED
            assert engine.review_queue is not None
            assert engine.review_queue.pending_count() == 0
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_review(self, tmp_path: Path) -> None:
        """Agent output with low confidence triggers review queue."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "processed", "confidence": 0.35}

        config_mgr = _make_config_mgr(tmp_path)
        engine = OrchestrationEngine(config_mgr, llm_call_fn=mock_llm)
        await engine.start()

        try:
            work = WorkItem(id="w1", type_id="task", title="Test")
            await engine.submit_work(work)
            await asyncio.sleep(1.5)

            assert engine.review_queue is not None
            reviews = engine.review_queue.get_all()
            assert len(reviews) >= 1
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_very_low_confidence_aborts(self, tmp_path: Path) -> None:
        """Agent output with very low confidence triggers governance abort."""
        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            return {"response": "processed", "confidence": 0.1}

        config_mgr = _make_config_mgr(tmp_path)
        engine = OrchestrationEngine(config_mgr, llm_call_fn=mock_llm)
        await engine.start()

        try:
            work = WorkItem(id="w1", type_id="task", title="Test")
            await engine.submit_work(work)
            await asyncio.sleep(1.5)

            assert work.status == WorkItemStatus.FAILED
            assert "governance abort" in (work.error or "").lower()
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_prior_confidence_propagates(self, tmp_path: Path) -> None:
        """Confidence from first phase propagates to next phase governance."""
        call_count = 0

        async def mock_llm(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"response": "done", "confidence": 0.9}

        profile = ProfileConfig(
            name="test",
            agents=[
                AgentDefinition(
                    id="a1", name="A1", system_prompt="test",
                    phases=["p1"], llm=LLMConfig(provider="openai", model="gpt-4o"),
                ),
                AgentDefinition(
                    id="a2", name="A2", system_prompt="test",
                    phases=["p2"], llm=LLMConfig(provider="openai", model="gpt-4o"),
                ),
            ],
            workflow=WorkflowConfig(
                name="multi",
                phases=[
                    WorkflowPhaseConfig(id="p1", name="Phase1", order=1, agents=["a1"], on_success="p2"),
                    WorkflowPhaseConfig(id="p2", name="Phase2", order=2, agents=["a2"], on_success="done"),
                    WorkflowPhaseConfig(id="done", name="Done", order=3, agents=[], is_terminal=True),
                ],
            ),
            governance=GovernanceConfig(
                delegated_authority=DelegatedAuthorityConfig(
                    auto_approve_threshold=0.8,
                ),
            ),
        )

        config_mgr = _make_config_mgr(tmp_path, profile)
        engine = OrchestrationEngine(config_mgr, llm_call_fn=mock_llm)
        await engine.start()

        try:
            work = WorkItem(id="w1", type_id="task", title="Test")
            await engine.submit_work(work)
            await asyncio.sleep(2.0)

            assert work.status == WorkItemStatus.COMPLETED
            assert call_count == 2
        finally:
            await engine.stop()
