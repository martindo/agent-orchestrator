"""Capability gap detection for multi-agent orchestration.

Detects gaps between what agents can do and what workflows require,
both statically (configuration analysis) and at runtime (signal analysis).

Two main components:
- GapSignalCollector: subscribes to EventBus events and aggregates
  failure/confidence/rejection signals into time-windowed counters.
- GapAnalyzer: examines collected signal windows and produces
  CapabilityGap records when thresholds are exceeded.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from agent_orchestrator.core.event_bus import Event, EventBus, EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GapSource(str, Enum):
    """Origin of a detected capability gap."""

    STATIC_SKILL_MISMATCH = "static_skill_mismatch"
    STATIC_UNCOVERED_PHASE = "static_uncovered_phase"
    STATIC_OUTPUT_MISMATCH = "static_output_mismatch"
    RUNTIME_REPEATED_FAILURE = "runtime_repeated_failure"
    RUNTIME_LOW_CONFIDENCE = "runtime_low_confidence"
    RUNTIME_CRITIC_REJECTION = "runtime_critic_rejection"
    RUNTIME_GATE_FAILURE = "runtime_gate_failure"
    RUNTIME_EXCESSIVE_RETRY = "runtime_excessive_retry"
    RUNTIME_HUMAN_OVERRIDE = "runtime_human_override"
    RUNTIME_GOVERNANCE_ESCALATION = "runtime_governance_escalation"


class GapSeverity(str, Enum):
    """Severity level of a detected gap."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityGap:
    """An identified gap between required and available capabilities."""

    id: str
    phase_id: str
    agent_id: str | None
    gap_source: GapSource
    severity: GapSeverity
    description: str
    evidence: dict[str, Any]
    suggested_capabilities: list[str]
    detected_at: datetime
    run_id: str = ""


@dataclass
class SignalWindow:
    """Mutable counters for a time-bounded observation window."""

    phase_id: str
    agent_id: str
    window_start: datetime
    total_count: int = 0
    failure_count: int = 0
    retry_count: int = 0
    low_confidence_count: int = 0
    critic_rejection_count: int = 0
    gate_failure_count: int = 0
    human_override_count: int = 0
    governance_escalation_count: int = 0


@dataclass(frozen=True)
class GapDetectionThresholds:
    """Configurable thresholds for gap detection."""

    min_sample_size: int = 5
    failure_rate_warning: float = 0.3
    failure_rate_critical: float = 0.6
    low_confidence_threshold: float = 0.4
    retry_rate_warning: float = 0.5
    critic_rejection_rate_warning: float = 0.3
    human_override_rate_warning: float = 0.2
    governance_escalation_rate_warning: float = 0.3


# ---------------------------------------------------------------------------
# GapSignalCollector
# ---------------------------------------------------------------------------


class GapSignalCollector:
    """Collects runtime signals from EventBus into time-windowed counters.

    Thread-safe: all mutable state is protected by a lock.

    Args:
        event_bus: The event bus to subscribe to.
        window_seconds: Duration of each observation window in seconds.
    """

    def __init__(
        self,
        event_bus: EventBus,
        window_seconds: float = 3600.0,
    ) -> None:
        self._event_bus = event_bus
        self._window_seconds = window_seconds
        self._windows: dict[tuple[str, str], SignalWindow] = {}
        self._lock = threading.Lock()
        self._confidence_threshold = 0.4

        self._subscribe()

    # -- subscriptions -------------------------------------------------------

    def _subscribe(self) -> None:
        """Register async handlers on the event bus."""
        self._event_bus.subscribe(EventType.AGENT_ERROR, self._on_agent_error)
        self._event_bus.subscribe(EventType.WORK_PHASE_EXITED, self._on_phase_exited)
        self._event_bus.subscribe(EventType.AGENT_COMPLETED, self._on_agent_completed)
        self._event_bus.subscribe(
            EventType.GOVERNANCE_DECISION, self._on_governance_decision,
        )
        self._event_bus.subscribe(
            EventType.GOVERNANCE_REVIEW_COMPLETED, self._on_review_completed,
        )

    # -- window management ---------------------------------------------------

    def _get_or_create_window(
        self, phase_id: str, agent_id: str,
    ) -> SignalWindow:
        """Return existing window or create a new one if expired/missing.

        Must be called while holding ``self._lock``.
        """
        key = (phase_id, agent_id)
        now = datetime.now(timezone.utc)
        existing = self._windows.get(key)
        if existing is not None:
            elapsed = (now - existing.window_start).total_seconds()
            if elapsed < self._window_seconds:
                return existing
        window = SignalWindow(
            phase_id=phase_id,
            agent_id=agent_id,
            window_start=now,
        )
        self._windows[key] = window
        return window

    # -- event handlers ------------------------------------------------------

    async def _on_agent_error(self, event: Event) -> None:
        """Handle AGENT_ERROR: increment failure_count."""
        phase_id = event.data.get("phase_id", "")
        agent_id = event.data.get("agent_id", "")
        with self._lock:
            window = self._get_or_create_window(phase_id, agent_id)
            window.total_count += 1
            window.failure_count += 1
        logger.debug(
            "Recorded agent error for phase=%s agent=%s", phase_id, agent_id,
        )

    async def _on_phase_exited(self, event: Event) -> None:
        """Handle WORK_PHASE_EXITED: increment failure_count on failure."""
        if event.data.get("success", True):
            return
        phase_id = event.data.get("phase_id", "")
        agent_id = "__phase__"
        with self._lock:
            window = self._get_or_create_window(phase_id, agent_id)
            window.total_count += 1
            window.failure_count += 1
        logger.debug("Recorded phase failure for phase=%s", phase_id)

    async def _on_agent_completed(self, event: Event) -> None:
        """Handle AGENT_COMPLETED: track low-confidence results."""
        phase_id = event.data.get("phase_id", "")
        agent_id = event.data.get("agent_id", "")
        confidence = event.data.get("confidence", 1.0)
        with self._lock:
            window = self._get_or_create_window(phase_id, agent_id)
            window.total_count += 1
            if confidence < self._confidence_threshold:
                window.low_confidence_count += 1
        logger.debug(
            "Recorded agent completion for phase=%s agent=%s confidence=%.2f",
            phase_id, agent_id, confidence,
        )

    async def _on_governance_decision(self, event: Event) -> None:
        """Handle GOVERNANCE_DECISION: track escalations and aborts."""
        resolution = event.data.get("resolution", "")
        if resolution not in ("escalate", "abort"):
            return
        phase_id = event.data.get("phase_id", "")
        agent_id = event.data.get("agent_id", "")
        with self._lock:
            window = self._get_or_create_window(phase_id, agent_id)
            window.total_count += 1
            window.governance_escalation_count += 1
        logger.debug(
            "Recorded governance escalation for phase=%s agent=%s",
            phase_id, agent_id,
        )

    async def _on_review_completed(self, event: Event) -> None:
        """Handle GOVERNANCE_REVIEW_COMPLETED: track overrides/rejections."""
        decision = event.data.get("decision", "")
        overridden = event.data.get("overridden", False)
        if decision != "rejected" and not overridden:
            return
        phase_id = event.data.get("phase_id", "")
        agent_id = event.data.get("agent_id", "")
        with self._lock:
            window = self._get_or_create_window(phase_id, agent_id)
            window.total_count += 1
            window.human_override_count += 1
        logger.debug(
            "Recorded human override for phase=%s agent=%s",
            phase_id, agent_id,
        )

    # -- public API ----------------------------------------------------------

    def get_windows(self) -> list[SignalWindow]:
        """Return a snapshot of all active signal windows."""
        with self._lock:
            return list(self._windows.values())

    def prune_expired(self) -> None:
        """Remove windows whose age exceeds window_seconds."""
        now = datetime.now(timezone.utc)
        with self._lock:
            expired_keys = [
                key
                for key, win in self._windows.items()
                if (now - win.window_start).total_seconds() >= self._window_seconds
            ]
            for key in expired_keys:
                del self._windows[key]
        if expired_keys:
            logger.info("Pruned %d expired signal window(s)", len(expired_keys))


# ---------------------------------------------------------------------------
# GapAnalyzer
# ---------------------------------------------------------------------------


class GapAnalyzer:
    """Analyzes signal windows and emits CapabilityGap records.

    Args:
        thresholds: Detection thresholds to apply.
    """

    def __init__(
        self,
        thresholds: GapDetectionThresholds | None = None,
    ) -> None:
        self._thresholds = thresholds or GapDetectionThresholds()

    def analyze(
        self,
        windows: list[SignalWindow],
        run_id: str = "",
    ) -> list[CapabilityGap]:
        """Analyze windows and return detected gaps.

        Args:
            windows: Signal windows to examine.
            run_id: Optional run identifier to attach to gaps.

        Returns:
            List of detected capability gaps.
        """
        gaps: list[CapabilityGap] = []
        for window in windows:
            if window.total_count < self._thresholds.min_sample_size:
                continue
            gaps.extend(self._analyze_window(window, run_id))
        return gaps

    def _analyze_window(
        self,
        window: SignalWindow,
        run_id: str,
    ) -> list[CapabilityGap]:
        """Check a single window against all thresholds."""
        gaps: list[CapabilityGap] = []
        total = window.total_count

        gaps.extend(self._check_failure_rate(window, total, run_id))
        gaps.extend(self._check_low_confidence(window, total, run_id))
        gaps.extend(self._check_retry_rate(window, total, run_id))
        gaps.extend(self._check_critic_rejection(window, total, run_id))
        gaps.extend(self._check_human_override(window, total, run_id))
        gaps.extend(self._check_governance_escalation(window, total, run_id))

        return gaps

    # -- individual checks ---------------------------------------------------

    def _check_failure_rate(
        self, window: SignalWindow, total: int, run_id: str,
    ) -> list[CapabilityGap]:
        """Check failure rate against warning and critical thresholds."""
        rate = window.failure_count / total
        t = self._thresholds
        if rate >= t.failure_rate_critical:
            return [self._make_gap(
                window, run_id,
                source=GapSource.RUNTIME_REPEATED_FAILURE,
                severity=GapSeverity.CRITICAL,
                description=(
                    f"Critical failure rate ({rate:.0%}) for "
                    f"phase={window.phase_id} agent={window.agent_id}"
                ),
                evidence={"failure_rate": rate, "failure_count": window.failure_count,
                          "total_count": total},
                suggestions=["error_recovery", "fallback_agent", "retry_policy"],
            )]
        if rate >= t.failure_rate_warning:
            return [self._make_gap(
                window, run_id,
                source=GapSource.RUNTIME_REPEATED_FAILURE,
                severity=GapSeverity.WARNING,
                description=(
                    f"Elevated failure rate ({rate:.0%}) for "
                    f"phase={window.phase_id} agent={window.agent_id}"
                ),
                evidence={"failure_rate": rate, "failure_count": window.failure_count,
                          "total_count": total},
                suggestions=["error_recovery", "retry_policy"],
            )]
        return []

    def _check_low_confidence(
        self, window: SignalWindow, total: int, run_id: str,
    ) -> list[CapabilityGap]:
        """Check low-confidence completion rate."""
        rate = window.low_confidence_count / total
        if rate >= self._thresholds.low_confidence_threshold:
            return [self._make_gap(
                window, run_id,
                source=GapSource.RUNTIME_LOW_CONFIDENCE,
                severity=GapSeverity.WARNING,
                description=(
                    f"High low-confidence rate ({rate:.0%}) for "
                    f"phase={window.phase_id} agent={window.agent_id}"
                ),
                evidence={"low_confidence_rate": rate,
                          "low_confidence_count": window.low_confidence_count,
                          "total_count": total},
                suggestions=["prompt_refinement", "specialized_model", "few_shot_examples"],
            )]
        return []

    def _check_retry_rate(
        self, window: SignalWindow, total: int, run_id: str,
    ) -> list[CapabilityGap]:
        """Check excessive retry rate."""
        rate = window.retry_count / total
        if rate >= self._thresholds.retry_rate_warning:
            return [self._make_gap(
                window, run_id,
                source=GapSource.RUNTIME_EXCESSIVE_RETRY,
                severity=GapSeverity.WARNING,
                description=(
                    f"Excessive retry rate ({rate:.0%}) for "
                    f"phase={window.phase_id} agent={window.agent_id}"
                ),
                evidence={"retry_rate": rate, "retry_count": window.retry_count,
                          "total_count": total},
                suggestions=["prompt_refinement", "output_format_constraint"],
            )]
        return []

    def _check_critic_rejection(
        self, window: SignalWindow, total: int, run_id: str,
    ) -> list[CapabilityGap]:
        """Check critic rejection rate."""
        rate = window.critic_rejection_count / total
        if rate >= self._thresholds.critic_rejection_rate_warning:
            return [self._make_gap(
                window, run_id,
                source=GapSource.RUNTIME_CRITIC_REJECTION,
                severity=GapSeverity.WARNING,
                description=(
                    f"High critic rejection rate ({rate:.0%}) for "
                    f"phase={window.phase_id} agent={window.agent_id}"
                ),
                evidence={"critic_rejection_rate": rate,
                          "critic_rejection_count": window.critic_rejection_count,
                          "total_count": total},
                suggestions=["quality_criteria_alignment", "output_schema_enforcement"],
            )]
        return []

    def _check_human_override(
        self, window: SignalWindow, total: int, run_id: str,
    ) -> list[CapabilityGap]:
        """Check human override rate."""
        rate = window.human_override_count / total
        if rate >= self._thresholds.human_override_rate_warning:
            return [self._make_gap(
                window, run_id,
                source=GapSource.RUNTIME_HUMAN_OVERRIDE,
                severity=GapSeverity.WARNING,
                description=(
                    f"Frequent human overrides ({rate:.0%}) for "
                    f"phase={window.phase_id} agent={window.agent_id}"
                ),
                evidence={"human_override_rate": rate,
                          "human_override_count": window.human_override_count,
                          "total_count": total},
                suggestions=["policy_refinement", "training_data", "guardrail_tuning"],
            )]
        return []

    def _check_governance_escalation(
        self, window: SignalWindow, total: int, run_id: str,
    ) -> list[CapabilityGap]:
        """Check governance escalation rate."""
        rate = window.governance_escalation_count / total
        if rate >= self._thresholds.governance_escalation_rate_warning:
            return [self._make_gap(
                window, run_id,
                source=GapSource.RUNTIME_GOVERNANCE_ESCALATION,
                severity=GapSeverity.WARNING,
                description=(
                    f"Frequent governance escalations ({rate:.0%}) for "
                    f"phase={window.phase_id} agent={window.agent_id}"
                ),
                evidence={"governance_escalation_rate": rate,
                          "governance_escalation_count": window.governance_escalation_count,
                          "total_count": total},
                suggestions=["policy_adjustment", "agent_capability_upgrade"],
            )]
        return []

    # -- helpers -------------------------------------------------------------

    def _make_gap(
        self,
        window: SignalWindow,
        run_id: str,
        *,
        source: GapSource,
        severity: GapSeverity,
        description: str,
        evidence: dict[str, Any],
        suggestions: list[str],
    ) -> CapabilityGap:
        """Construct a CapabilityGap with a unique ID."""
        gap_id = (
            f"gap-{source.value}-{window.phase_id}"
            f"-{window.agent_id}-{uuid4().hex[:8]}"
        )
        return CapabilityGap(
            id=gap_id,
            phase_id=window.phase_id,
            agent_id=window.agent_id if window.agent_id != "__phase__" else None,
            gap_source=source,
            severity=severity,
            description=description,
            evidence=evidence,
            suggested_capabilities=suggestions,
            detected_at=datetime.now(timezone.utc),
            run_id=run_id,
        )
