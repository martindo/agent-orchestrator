"""Tests for MCP Server Governance — GovernedToolDispatcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from agent_orchestrator.mcp.server_governance import GovernedToolDispatcher


def _mock_engine(resolution: str = "allow", reason: str = "") -> MagicMock:
    """Create a mock engine with governor and audit logger."""
    engine = MagicMock()

    # Mock governor
    governor = MagicMock()
    decision = MagicMock()
    decision.resolution = MagicMock()
    decision.resolution.value = resolution

    # Set the Resolution enum comparison behavior
    from agent_orchestrator.governance.governor import Resolution
    if resolution == "allow":
        decision.resolution = Resolution.ALLOW
    elif resolution == "allow_with_warning":
        decision.resolution = Resolution.ALLOW_WITH_WARNING
        decision.warnings = ["test warning"]
    elif resolution == "queue_for_review":
        decision.resolution = Resolution.QUEUE_FOR_REVIEW
    elif resolution == "abort":
        decision.resolution = Resolution.ABORT

    decision.reason = reason
    decision.confidence = 0.5
    governor.evaluate = MagicMock(return_value=decision)
    engine.governor = governor

    # Mock audit logger
    engine.audit_logger = MagicMock()

    # Mock review queue
    engine.review_queue = MagicMock()
    engine.review_queue.enqueue = MagicMock(return_value="review-123")

    return engine


class TestGovernedToolDispatcher:
    @pytest.mark.asyncio
    async def test_allow(self) -> None:
        engine = _mock_engine("allow")
        dispatcher = GovernedToolDispatcher(engine)
        result = await dispatcher.dispatch("my_tool", {"key": "val"}, "sess-1")
        assert result["governance_resolution"] == "allow"
        engine.audit_logger.append.assert_called()

    @pytest.mark.asyncio
    async def test_abort(self) -> None:
        engine = _mock_engine("abort", reason="Too dangerous")
        dispatcher = GovernedToolDispatcher(engine)
        result = await dispatcher.dispatch("dangerous_tool", {}, "sess-1")
        assert "error" in result
        assert result["governance_resolution"] == "abort"
        assert "Too dangerous" in result["error"]

    @pytest.mark.asyncio
    async def test_queue_for_review(self) -> None:
        engine = _mock_engine("queue_for_review", reason="Needs approval")
        dispatcher = GovernedToolDispatcher(engine)
        result = await dispatcher.dispatch("sensitive_tool", {}, "sess-1")
        assert result["governance_resolution"] == "queue_for_review"
        assert result["review_id"] == "review-123"

    @pytest.mark.asyncio
    async def test_allow_with_warning(self) -> None:
        engine = _mock_engine("allow_with_warning")
        dispatcher = GovernedToolDispatcher(engine)
        result = await dispatcher.dispatch("risky_tool", {}, "sess-1")
        assert result["governance_resolution"] == "allow"

    @pytest.mark.asyncio
    async def test_no_governor(self) -> None:
        engine = MagicMock()
        engine.governor = None
        engine.audit_logger = MagicMock()
        dispatcher = GovernedToolDispatcher(engine)
        result = await dispatcher.dispatch("any_tool", {}, "sess-1")
        assert result["governance_resolution"] == "allow"

    @pytest.mark.asyncio
    async def test_no_audit_logger(self) -> None:
        engine = MagicMock()
        engine.governor = None
        engine.audit_logger = None
        dispatcher = GovernedToolDispatcher(engine)
        # Should not raise even without audit logger
        result = await dispatcher.dispatch("tool", {}, "")
        assert result["governance_resolution"] == "allow"

    @pytest.mark.asyncio
    async def test_audit_records_tool_name(self) -> None:
        engine = _mock_engine("allow")
        dispatcher = GovernedToolDispatcher(engine)
        await dispatcher.dispatch("specific_tool", {"a": 1}, "sess-x")
        call_args = engine.audit_logger.append.call_args
        assert "specific_tool" in call_args.kwargs.get("action", "") or "specific_tool" in str(call_args)
