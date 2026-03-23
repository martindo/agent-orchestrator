"""Tests for runtime gap detection — signal collection and analysis."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from agent_orchestrator.core.event_bus import Event, EventBus, EventType
from agent_orchestrator.core.gap_detector import (
    CapabilityGap,
    GapAnalyzer,
    GapDetectionThresholds,
    GapSeverity,
    GapSignalCollector,
    GapSource,
    SignalWindow,
)


@pytest.fixture()
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def collector(event_bus: EventBus) -> GapSignalCollector:
    return GapSignalCollector(event_bus, window_seconds=3600.0)


class TestGapSignalCollector:
    """Tests for signal collection from EventBus events."""

    @pytest.mark.asyncio
    async def test_agent_error_increments_failure(
        self, event_bus: EventBus, collector: GapSignalCollector,
    ) -> None:
        """AGENT_ERROR events increment failure_count."""
        await event_bus.emit(Event(
            type=EventType.AGENT_ERROR,
            data={"phase_id": "analysis", "agent_id": "agent-1"},
            source="test",
        ))
        windows = collector.get_windows()
        assert len(windows) == 1
        assert windows[0].failure_count == 1
        assert windows[0].total_count == 1

    @pytest.mark.asyncio
    async def test_phase_failure_tracked(
        self, event_bus: EventBus, collector: GapSignalCollector,
    ) -> None:
        """WORK_PHASE_EXITED with success=false increments phase failure."""
        await event_bus.emit(Event(
            type=EventType.WORK_PHASE_EXITED,
            data={"phase_id": "review", "success": False},
            source="test",
        ))
        windows = collector.get_windows()
        phase_windows = [w for w in windows if w.agent_id == "__phase__"]
        assert len(phase_windows) == 1
        assert phase_windows[0].failure_count == 1

    @pytest.mark.asyncio
    async def test_phase_success_not_tracked(
        self, event_bus: EventBus, collector: GapSignalCollector,
    ) -> None:
        """WORK_PHASE_EXITED with success=true does not create a window."""
        await event_bus.emit(Event(
            type=EventType.WORK_PHASE_EXITED,
            data={"phase_id": "review", "success": True},
            source="test",
        ))
        windows = collector.get_windows()
        assert len(windows) == 0

    @pytest.mark.asyncio
    async def test_low_confidence_tracked(
        self, event_bus: EventBus, collector: GapSignalCollector,
    ) -> None:
        """AGENT_COMPLETED with low confidence increments low_confidence_count."""
        await event_bus.emit(Event(
            type=EventType.AGENT_COMPLETED,
            data={"phase_id": "analysis", "agent_id": "a1", "confidence": 0.2},
            source="test",
        ))
        windows = collector.get_windows()
        assert len(windows) == 1
        assert windows[0].low_confidence_count == 1
        assert windows[0].total_count == 1

    @pytest.mark.asyncio
    async def test_high_confidence_not_flagged(
        self, event_bus: EventBus, collector: GapSignalCollector,
    ) -> None:
        """AGENT_COMPLETED with high confidence does not increment low_confidence_count."""
        await event_bus.emit(Event(
            type=EventType.AGENT_COMPLETED,
            data={"phase_id": "analysis", "agent_id": "a1", "confidence": 0.9},
            source="test",
        ))
        windows = collector.get_windows()
        assert len(windows) == 1
        assert windows[0].low_confidence_count == 0
        assert windows[0].total_count == 1

    @pytest.mark.asyncio
    async def test_multiple_events_accumulate(
        self, event_bus: EventBus, collector: GapSignalCollector,
    ) -> None:
        """Multiple events for same (phase, agent) accumulate in one window."""
        for _ in range(5):
            await event_bus.emit(Event(
                type=EventType.AGENT_ERROR,
                data={"phase_id": "p1", "agent_id": "a1"},
                source="test",
            ))
        windows = collector.get_windows()
        assert len(windows) == 1
        assert windows[0].failure_count == 5
        assert windows[0].total_count == 5


class TestGapAnalyzer:
    """Tests for threshold-based gap analysis."""

    def _make_window(
        self,
        phase_id: str = "test-phase",
        agent_id: str = "test-agent",
        total: int = 10,
        failures: int = 0,
        low_confidence: int = 0,
        retries: int = 0,
        critic_rejections: int = 0,
        human_overrides: int = 0,
        governance_escalations: int = 0,
    ) -> SignalWindow:
        return SignalWindow(
            phase_id=phase_id,
            agent_id=agent_id,
            window_start=datetime.now(timezone.utc),
            total_count=total,
            failure_count=failures,
            low_confidence_count=low_confidence,
            retry_count=retries,
            critic_rejection_count=critic_rejections,
            human_override_count=human_overrides,
            governance_escalation_count=governance_escalations,
        )

    def test_below_threshold_no_gaps(self) -> None:
        """Windows below all thresholds produce no gaps."""
        analyzer = GapAnalyzer(GapDetectionThresholds())
        window = self._make_window(total=10, failures=1)
        gaps = analyzer.analyze([window])
        assert len(gaps) == 0

    def test_below_min_sample_size_ignored(self) -> None:
        """Windows with too few events are skipped."""
        analyzer = GapAnalyzer(GapDetectionThresholds(min_sample_size=10))
        window = self._make_window(total=5, failures=5)
        gaps = analyzer.analyze([window])
        assert len(gaps) == 0

    def test_critical_failure_rate(self) -> None:
        """60%+ failure rate produces CRITICAL gap."""
        analyzer = GapAnalyzer(GapDetectionThresholds())
        window = self._make_window(total=10, failures=7)
        gaps = analyzer.analyze([window])
        failure_gaps = [g for g in gaps if g.gap_source == GapSource.RUNTIME_REPEATED_FAILURE]
        assert len(failure_gaps) == 1
        assert failure_gaps[0].severity == GapSeverity.CRITICAL

    def test_warning_failure_rate(self) -> None:
        """30-59% failure rate produces WARNING gap."""
        analyzer = GapAnalyzer(GapDetectionThresholds())
        window = self._make_window(total=10, failures=4)
        gaps = analyzer.analyze([window])
        failure_gaps = [g for g in gaps if g.gap_source == GapSource.RUNTIME_REPEATED_FAILURE]
        assert len(failure_gaps) == 1
        assert failure_gaps[0].severity == GapSeverity.WARNING

    def test_low_confidence_gap(self) -> None:
        """High low-confidence rate triggers gap."""
        analyzer = GapAnalyzer(GapDetectionThresholds(low_confidence_threshold=0.3))
        window = self._make_window(total=10, low_confidence=5)
        gaps = analyzer.analyze([window])
        conf_gaps = [g for g in gaps if g.gap_source == GapSource.RUNTIME_LOW_CONFIDENCE]
        assert len(conf_gaps) == 1

    def test_multiple_signals_multiple_gaps(self) -> None:
        """Multiple threshold violations produce multiple gaps."""
        analyzer = GapAnalyzer(GapDetectionThresholds())
        window = self._make_window(
            total=10, failures=7, low_confidence=5, human_overrides=3,
        )
        gaps = analyzer.analyze([window])
        sources = {g.gap_source for g in gaps}
        assert GapSource.RUNTIME_REPEATED_FAILURE in sources
        assert GapSource.RUNTIME_LOW_CONFIDENCE in sources
        assert GapSource.RUNTIME_HUMAN_OVERRIDE in sources

    def test_gap_has_evidence(self) -> None:
        """Detected gaps include evidence dict with rates and counts."""
        analyzer = GapAnalyzer(GapDetectionThresholds())
        window = self._make_window(total=10, failures=7)
        gaps = analyzer.analyze([window])
        assert len(gaps) >= 1
        gap = gaps[0]
        assert "failure_rate" in gap.evidence
        assert "failure_count" in gap.evidence
        assert gap.evidence["failure_count"] == 7

    def test_run_id_propagated(self) -> None:
        """Run ID is attached to detected gaps."""
        analyzer = GapAnalyzer(GapDetectionThresholds())
        window = self._make_window(total=10, failures=7)
        gaps = analyzer.analyze([window], run_id="run-123")
        assert all(g.run_id == "run-123" for g in gaps)

    def test_gap_id_format(self) -> None:
        """Gap IDs follow expected format."""
        analyzer = GapAnalyzer(GapDetectionThresholds())
        window = self._make_window(total=10, failures=7)
        gaps = analyzer.analyze([window])
        assert len(gaps) >= 1
        assert gaps[0].id.startswith("gap-runtime_repeated_failure-")
