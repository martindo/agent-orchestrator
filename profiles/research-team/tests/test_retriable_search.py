"""Unit tests for RetriableSearchService (research-team domain module).

Run from the repo root:
    pytest profiles/research-team/tests/ -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make profiles/research-team importable without installing it as a package.
_PROFILE_DIR = Path(__file__).parent.parent
if str(_PROFILE_DIR) not in sys.path:
    sys.path.insert(0, str(_PROFILE_DIR))

from retriable_search import (  # noqa: E402
    RetriableSearchService,
    TargetedQuery,
    UnverifiedClaim,
)
from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_work_item(results: dict | None = None) -> WorkItem:
    item = WorkItem(id="wi-1", type_id="research", title="Test item", data={})
    item.results = results or {}
    return item


def _verifier_result(
    findings: list[dict] | None = None,
    gaps: list[dict] | None = None,
    has_gaps: bool = False,
) -> dict:
    return {
        "verified_findings": findings or [],
        "gaps": gaps or [],
        "has_gaps": has_gaps,
    }


def _confirmed_finding(claim: str = "claim A") -> dict:
    return {
        "claim": claim,
        "status": "confirmed",
        "confidence": 0.9,
        "needs_review": False,
        "review_reason": "",
    }


def _uncertain_finding(claim: str = "claim B") -> dict:
    return {
        "claim": claim,
        "status": "uncertain",
        "confidence": 0.7,
        "needs_review": False,
        "review_reason": "only one source",
    }


# ── TestExtractVerifierOutput ─────────────────────────────────────────────────

class TestExtractVerifierOutput:

    def test_finds_output_by_both_keys(self) -> None:
        svc = RetriableSearchService()
        result = _verifier_result()
        item = _make_work_item({"critic-verifier": result})
        out = svc._extract_verifier_output(item)
        assert out is result

    def test_returns_none_when_not_present(self) -> None:
        svc = RetriableSearchService()
        item = _make_work_item({"other-agent": {"data": 1}})
        assert svc._extract_verifier_output(item) is None

    def test_requires_both_keys_not_just_one(self) -> None:
        svc = RetriableSearchService()
        item = _make_work_item({"agent": {"has_gaps": True}})
        assert svc._extract_verifier_output(item) is None
        item2 = _make_work_item({"agent": {"verified_findings": []}})
        assert svc._extract_verifier_output(item2) is None


# ── TestUnverifiedClaimExtraction ─────────────────────────────────────────────

class TestUnverifiedClaimExtraction:

    def test_empty_results_returns_empty_list(self) -> None:
        svc = RetriableSearchService()
        item = _make_work_item()
        assert svc.extract_unverified_claims(item) == []

    def test_all_confirmed_high_confidence_returns_empty(self) -> None:
        svc = RetriableSearchService()
        findings = [_confirmed_finding("A"), _confirmed_finding("B")]
        item = _make_work_item({"v": _verifier_result(findings=findings)})
        assert svc.extract_unverified_claims(item) == []

    def test_uncertain_finding_is_extracted(self) -> None:
        svc = RetriableSearchService()
        item = _make_work_item({"v": _verifier_result(findings=[_uncertain_finding()])})
        claims = svc.extract_unverified_claims(item)
        assert len(claims) == 1
        assert claims[0].status == "uncertain"

    def test_low_confidence_confirmed_is_extracted(self) -> None:
        svc = RetriableSearchService()
        finding = {"claim": "C", "status": "confirmed", "confidence": 0.5, "needs_review": False, "review_reason": ""}
        item = _make_work_item({"v": _verifier_result(findings=[finding])})
        claims = svc.extract_unverified_claims(item)
        assert len(claims) == 1
        assert claims[0].confidence == 0.5

    def test_needs_review_true_always_extracted(self) -> None:
        svc = RetriableSearchService()
        finding = {"claim": "D", "status": "confirmed", "confidence": 0.95, "needs_review": True, "review_reason": "single source"}
        item = _make_work_item({"v": _verifier_result(findings=[finding])})
        claims = svc.extract_unverified_claims(item)
        assert len(claims) == 1
        assert claims[0].needs_review is True

    def test_multiple_agents_identifies_verifier_correctly(self) -> None:
        svc = RetriableSearchService()
        findings = [_uncertain_finding()]
        results = {
            "search-specialist": {"queries": []},
            "critic-verifier": _verifier_result(findings=findings),
        }
        item = _make_work_item(results)
        claims = svc.extract_unverified_claims(item)
        assert len(claims) == 1

    def test_gap_suggested_queries_attached_to_claims(self) -> None:
        svc = RetriableSearchService()
        gaps = [{"description": "missing data", "suggested_queries": ["query X", "query Y", "query Z"]}]
        item = _make_work_item({"v": _verifier_result(findings=[_uncertain_finding()], gaps=gaps)})
        claims = svc.extract_unverified_claims(item)
        assert len(claims) == 1
        assert claims[0].suggested_queries == ["query X", "query Y"]


# ── TestBuildTargetedQueries ──────────────────────────────────────────────────

class TestBuildTargetedQueries:

    def test_empty_claims_returns_empty_list(self) -> None:
        svc = RetriableSearchService()
        assert svc.build_targeted_queries([], []) == []

    def test_uses_claim_suggested_queries_first(self) -> None:
        svc = RetriableSearchService()
        claim = UnverifiedClaim(
            claim="some claim",
            status="uncertain",
            confidence=0.5,
            needs_review=False,
            review_reason="",
            suggested_queries=["targeted query 1", "targeted query 2"],
        )
        queries = svc.build_targeted_queries([claim], [])
        texts = [q.text for q in queries]
        assert "targeted query 1" in texts
        assert "targeted query 2" in texts

    def test_constructs_query_from_claim_text_when_no_suggestions(self) -> None:
        svc = RetriableSearchService()
        claim = UnverifiedClaim(
            claim="the earth is round",
            status="uncertain",
            confidence=0.5,
            needs_review=False,
            review_reason="",
        )
        queries = svc.build_targeted_queries([claim], [])
        assert len(queries) == 1
        assert "the earth is round" in queries[0].text

    def test_deduplicates_identical_query_text(self) -> None:
        svc = RetriableSearchService()
        c1 = UnverifiedClaim("A", "uncertain", 0.5, False, "", ["same query"])
        c2 = UnverifiedClaim("B", "uncertain", 0.5, False, "", ["same query"])
        queries = svc.build_targeted_queries([c1, c2], [])
        texts = [q.text for q in queries]
        assert texts.count("same query") == 1

    def test_needs_review_true_sets_priority_high(self) -> None:
        svc = RetriableSearchService()
        claim = UnverifiedClaim("E", "confirmed", 0.9, True, "single source", ["q"])
        queries = svc.build_targeted_queries([claim], [])
        assert queries[0].priority == "high"

    def test_caps_output_at_20_queries(self) -> None:
        svc = RetriableSearchService()
        claims = [
            UnverifiedClaim(f"claim {i}", "uncertain", 0.5, False, "", [f"query {i}a", f"query {i}b"])
            for i in range(15)
        ]
        queries = svc.build_targeted_queries(claims, [])
        assert len(queries) <= 20


# ── TestBuildPhaseContext ─────────────────────────────────────────────────────

class TestBuildPhaseContext:

    def test_no_verifier_output_returns_empty_dict(self) -> None:
        svc = RetriableSearchService()
        item = _make_work_item()
        assert svc.build_phase_context(item) == {}

    def test_no_unverified_claims_returns_empty_dict(self) -> None:
        svc = RetriableSearchService()
        findings = [_confirmed_finding()]
        item = _make_work_item({"v": _verifier_result(findings=findings)})
        assert svc.build_phase_context(item) == {}

    def test_unverified_claims_returns_targeted_search_key(self) -> None:
        svc = RetriableSearchService()
        item = _make_work_item({"v": _verifier_result(findings=[_uncertain_finding()])})
        ctx = svc.build_phase_context(item)
        assert "targeted_search" in ctx

    def test_validates_all_required_keys(self) -> None:
        svc = RetriableSearchService()
        item = _make_work_item({"v": _verifier_result(findings=[_uncertain_finding()])})
        ctx = svc.build_phase_context(item)
        ts = ctx["targeted_search"]
        assert ts["mode"] == "targeted"
        assert "unverified_claims_count" in ts
        assert "claims" in ts
        assert "targeted_queries" in ts
