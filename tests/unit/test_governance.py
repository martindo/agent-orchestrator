"""Unit tests for governance layer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from agent_orchestrator.configuration.models import (
    DelegatedAuthorityConfig,
    GovernanceConfig,
    PolicyConfig,
)
from agent_orchestrator.governance.audit_logger import AuditLogger, RecordType
from agent_orchestrator.governance.governor import Governor, Resolution
from agent_orchestrator.governance.review_queue import ReviewQueue


class TestGovernor:
    """Tests for Governor policy evaluation."""

    def _make_governor(self) -> Governor:
        config = GovernanceConfig(
            delegated_authority=DelegatedAuthorityConfig(
                auto_approve_threshold=0.8,
                review_threshold=0.5,
                abort_threshold=0.2,
                work_type_overrides={
                    "security": {
                        "auto_approve_threshold": 0.95,
                        "review_threshold": 0.7,
                    }
                },
            ),
            policies=[
                PolicyConfig(
                    id="auto-approve",
                    name="Auto Approve High Confidence",
                    action="allow",
                    conditions=["confidence >= 0.9", "failure_count == 0"],
                    priority=100,
                ),
                PolicyConfig(
                    id="reject-critical",
                    name="Reject Critical",
                    action="deny",
                    conditions=["risk_level == 'critical'"],
                    priority=200,
                ),
            ],
        )
        return Governor(config)

    def test_high_confidence_allow(self) -> None:
        gov = self._make_governor()
        decision = gov.evaluate({"confidence": 0.85})
        assert decision.resolution == Resolution.ALLOW

    def test_medium_confidence_warning(self) -> None:
        gov = self._make_governor()
        decision = gov.evaluate({"confidence": 0.6})
        assert decision.resolution == Resolution.ALLOW_WITH_WARNING

    def test_low_confidence_review(self) -> None:
        gov = self._make_governor()
        decision = gov.evaluate({"confidence": 0.3})
        assert decision.resolution == Resolution.QUEUE_FOR_REVIEW

    def test_very_low_confidence_abort(self) -> None:
        gov = self._make_governor()
        decision = gov.evaluate({"confidence": 0.1})
        assert decision.resolution == Resolution.ABORT

    def test_policy_match(self) -> None:
        gov = self._make_governor()
        decision = gov.evaluate({
            "confidence": 0.95,
            "failure_count": 0,
        })
        assert decision.resolution == Resolution.ALLOW
        assert decision.policy_id == "auto-approve"

    def test_deny_policy(self) -> None:
        gov = self._make_governor()
        decision = gov.evaluate({
            "confidence": 0.95,
            "risk_level": "critical",
        })
        assert decision.resolution == Resolution.ABORT
        assert decision.policy_id == "reject-critical"

    def test_work_type_override(self) -> None:
        gov = self._make_governor()
        # Without override: 0.85 would be ALLOW
        # With security override: auto_approve is 0.95, so 0.85 is warning
        decision = gov.evaluate({"confidence": 0.85}, work_type="security")
        assert decision.resolution == Resolution.ALLOW_WITH_WARNING

    def test_add_policy(self) -> None:
        gov = Governor()
        policy = PolicyConfig(
            id="new-policy", name="New", action="warn",
            conditions=["flag == 'true'"], priority=50,
        )
        gov.add_policy(policy)
        assert len(gov.list_policies()) == 1

    def test_remove_policy(self) -> None:
        gov = self._make_governor()
        assert gov.remove_policy("auto-approve")
        assert not gov.remove_policy("nonexistent")


class TestReviewQueue:
    """Tests for ReviewQueue."""

    def test_enqueue_and_pending(self) -> None:
        queue = ReviewQueue()
        review_id = queue.enqueue("w1", "phase-1", "Low confidence")
        assert review_id.startswith("review-")
        assert queue.pending_count() == 1

    def test_complete_review(self) -> None:
        queue = ReviewQueue()
        review_id = queue.enqueue("w1", "phase-1", "Low confidence")
        assert queue.complete_review(review_id, "admin", "Looks fine")
        assert queue.pending_count() == 0

    def test_complete_nonexistent(self) -> None:
        queue = ReviewQueue()
        assert not queue.complete_review("nonexistent", "admin")

    def test_get_all(self) -> None:
        queue = ReviewQueue()
        queue.enqueue("w1", "p1", "reason1")
        queue.enqueue("w2", "p2", "reason2")
        assert len(queue.get_all()) == 2


class TestAuditLogger:
    """Tests for AuditLogger."""

    def test_append_and_query(self, tmp_path: Path) -> None:
        audit = AuditLogger(tmp_path / ".audit")
        audit.append(
            RecordType.DECISION, "approve", "Approved review",
            work_id="w1",
        )
        records = audit.query(work_id="w1")
        assert len(records) == 1
        assert records[0]["action"] == "approve"

    def test_hash_chain(self, tmp_path: Path) -> None:
        audit = AuditLogger(tmp_path / ".audit")
        r1 = audit.append(RecordType.DECISION, "approve", "First")
        r2 = audit.append(RecordType.DECISION, "approve", "Second")
        assert r2.prev_hash == r1.hash
        assert audit.verify_chain()

    def test_query_by_type(self, tmp_path: Path) -> None:
        audit = AuditLogger(tmp_path / ".audit")
        audit.append(RecordType.DECISION, "approve", "Decision")
        audit.append(RecordType.ERROR, "fail", "Error")
        decisions = audit.query(record_type=RecordType.DECISION)
        assert len(decisions) == 1

    def test_empty_query(self, tmp_path: Path) -> None:
        audit = AuditLogger(tmp_path / ".audit")
        assert audit.query() == []

    def test_verify_empty_chain(self, tmp_path: Path) -> None:
        audit = AuditLogger(tmp_path / ".audit")
        assert audit.verify_chain()

    def test_sequence_continuity(self, tmp_path: Path) -> None:
        audit = AuditLogger(tmp_path / ".audit")
        r1 = audit.append(RecordType.DECISION, "a", "First")
        r2 = audit.append(RecordType.DECISION, "b", "Second")
        assert r1.sequence == 1
        assert r2.sequence == 2
