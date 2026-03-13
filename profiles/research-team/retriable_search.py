"""Targeted re-search service for research/fact-checking domain workflows.

This module is a DOMAIN helper, not part of the platform runtime.
It lives here so the research-team profile stays self-contained.

To use it, import it from your research application and wire it into the
engine via the ``phase_context_hook`` parameter:

    from profiles.research_team.retriable_search import RetriableSearchService

    def phase_context_hook(work_item, phase):
        if phase.id == "search":
            return RetriableSearchService().build_phase_context(work_item)
        return {}

    engine = OrchestrationEngine(config_manager, phase_context_hook=phase_context_hook)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_orchestrator.core.work_queue import WorkItem

logger = logging.getLogger(__name__)

_UNVERIFIED_STATUSES = frozenset({"uncertain", "challenged", "refuted"})
_LOW_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class UnverifiedClaim:
    claim: str
    status: str
    confidence: float
    needs_review: bool
    review_reason: str
    suggested_queries: list[str] = field(default_factory=list)


@dataclass
class TargetedQuery:
    text: str
    intent: str
    expected_sources: str
    source_claim: str
    priority: str  # "high" | "medium" | "low"


class RetriableSearchService:

    def extract_unverified_claims(self, work_item: WorkItem) -> list[UnverifiedClaim]:
        verifier_out = self._extract_verifier_output(work_item)
        if not verifier_out:
            return []
        gap_queries: list[str] = []
        for gap in verifier_out.get("gaps", []):
            gap_queries.extend(gap.get("suggested_queries", []))
        claims: list[UnverifiedClaim] = []
        for f in verifier_out.get("verified_findings", []):
            if (
                f.get("status") in _UNVERIFIED_STATUSES
                or float(f.get("confidence", 1.0)) < _LOW_CONFIDENCE_THRESHOLD
                or f.get("needs_review") is True
            ):
                claims.append(UnverifiedClaim(
                    claim=f.get("claim", ""),
                    status=f.get("status", "uncertain"),
                    confidence=float(f.get("confidence", 0.0)),
                    needs_review=bool(f.get("needs_review", False)),
                    review_reason=f.get("review_reason", ""),
                    suggested_queries=gap_queries[:2],
                ))
        logger.info(
            "Extracted %d unverified claims from work item %s",
            len(claims), work_item.id,
        )
        return claims

    def build_targeted_queries(
        self,
        claims: list[UnverifiedClaim],
        gaps: list[dict[str, Any]],
    ) -> list[TargetedQuery]:
        seen: set[str] = set()
        queries: list[TargetedQuery] = []

        def _add(text: str, intent: str, sources: str, claim: str, priority: str) -> None:
            key = text.lower().strip()
            if key and key not in seen and len(queries) < 20:
                seen.add(key)
                queries.append(TargetedQuery(
                    text=text,
                    intent=intent,
                    expected_sources=sources,
                    source_claim=claim,
                    priority=priority,
                ))

        for c in claims:
            if c.needs_review:
                priority = "high"
            elif c.status in ("uncertain", "challenged"):
                priority = "medium"
            else:
                priority = "low"

            if c.suggested_queries:
                _add(c.suggested_queries[0], "verify claim", "academic, news", c.claim, priority)
                if len(c.suggested_queries) > 1:
                    _add(c.suggested_queries[1], "find contradicting evidence", "academic", c.claim, priority)
            else:
                _add(
                    f'evidence for "{c.claim[:80]}"',
                    "verify claim",
                    "academic, primary sources",
                    c.claim,
                    priority,
                )

        for gap in gaps:
            for q in gap.get("suggested_queries", []):
                _add(q, "fill knowledge gap", "research, news", gap.get("description", ""), "medium")

        return queries

    def build_phase_context(self, work_item: WorkItem) -> dict[str, Any]:
        """Return phase_context dict for injection into the search phase. Returns {} on first pass."""
        verifier_out = self._extract_verifier_output(work_item)
        if not verifier_out:
            return {}
        claims = self.extract_unverified_claims(work_item)
        if not claims:
            return {}
        queries = self.build_targeted_queries(claims, verifier_out.get("gaps", []))
        return {
            "targeted_search": {
                "mode": "targeted",
                "unverified_claims_count": len(claims),
                "claims": [
                    {
                        "claim": c.claim,
                        "status": c.status,
                        "confidence": c.confidence,
                        "needs_review": c.needs_review,
                        "suggested_queries": c.suggested_queries,
                    }
                    for c in claims
                ],
                "targeted_queries": [
                    {
                        "text": q.text,
                        "intent": q.intent,
                        "expected_sources": q.expected_sources,
                        "priority": q.priority,
                        "source_claim": q.source_claim,
                    }
                    for q in queries
                ],
            }
        }

    def _extract_verifier_output(self, work_item: WorkItem) -> dict[str, Any] | None:
        """Find the first agent result containing both 'verified_findings' and 'has_gaps'."""
        for value in work_item.results.values():
            if isinstance(value, dict) and "verified_findings" in value and "has_gaps" in value:
                return value
        return None
