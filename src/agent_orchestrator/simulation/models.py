"""Simulation models — configuration and result types for sandbox execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SimulationStatus(str, Enum):
    """Status of a simulation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SimulationOutcome(str, Enum):
    """Outcome classification for a simulated work item."""

    SAME = "same"                # Same result as historical
    IMPROVED = "improved"        # Better confidence or success
    REGRESSED = "regressed"      # Worse confidence or success
    NEW_FAILURE = "new_failure"  # Historical succeeded, simulation failed
    NEW_SUCCESS = "new_success"  # Historical failed, simulation succeeded


@dataclass
class SimulationConfig:
    """Configuration for a simulation run.

    Specifies the workflow to test and constraints on execution.
    """

    simulation_id: str
    name: str = ""
    description: str = ""

    # Workflow to simulate (profile name or inline config)
    profile_name: str = ""
    workflow_overrides: dict[str, Any] = field(default_factory=dict)

    # Historical data selection
    work_item_filter: dict[str, Any] = field(default_factory=dict)
    max_items: int = 100
    include_types: list[str] = field(default_factory=list)

    # Execution controls
    dry_run: bool = False
    record_decisions: bool = False
    timeout_seconds: float = 300.0

    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


@dataclass
class ComparisonResult:
    """Comparison of a single work item's simulation vs historical outcome."""

    work_item_id: str
    outcome: SimulationOutcome

    # Historical
    historical_status: str = ""
    historical_confidence: float = 0.0
    historical_phases_completed: int = 0

    # Simulated
    simulated_status: str = ""
    simulated_confidence: float = 0.0
    simulated_phases_completed: int = 0

    # Delta
    confidence_delta: float = 0.0
    phase_delta: int = 0

    # Details
    notes: list[str] = field(default_factory=list)
    agent_results: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationResult:
    """Complete result of a simulation run."""

    simulation_id: str
    config: SimulationConfig
    status: SimulationStatus = SimulationStatus.PENDING

    # Timing
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0

    # Aggregate stats
    total_items: int = 0
    items_processed: int = 0
    items_improved: int = 0
    items_regressed: int = 0
    items_same: int = 0
    items_new_success: int = 0
    items_new_failure: int = 0
    items_errored: int = 0

    # Average metrics
    avg_historical_confidence: float = 0.0
    avg_simulated_confidence: float = 0.0
    confidence_improvement: float = 0.0

    # Per-item comparisons
    comparisons: list[ComparisonResult] = field(default_factory=list)

    # Errors
    errors: list[str] = field(default_factory=list)

    @property
    def improvement_rate(self) -> float:
        """Fraction of items that improved."""
        if self.items_processed == 0:
            return 0.0
        return self.items_improved / self.items_processed

    @property
    def regression_rate(self) -> float:
        """Fraction of items that regressed."""
        if self.items_processed == 0:
            return 0.0
        return self.items_regressed / self.items_processed


@dataclass
class BenchmarkCase:
    """A single benchmark test case with expected outcomes."""

    case_id: str
    work_item_data: dict[str, Any] = field(default_factory=dict)
    expected_status: str = "completed"
    expected_min_confidence: float = 0.0
    expected_output_keys: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class BenchmarkSuiteConfig:
    """Configuration for a benchmark suite."""

    suite_id: str
    name: str
    description: str = ""
    profile_name: str = ""
    cases: list[BenchmarkCase] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    tags: list[str] = field(default_factory=list)


@dataclass
class BenchmarkCaseResult:
    """Result of running a single benchmark case."""

    case_id: str
    passed: bool
    actual_status: str = ""
    actual_confidence: float = 0.0
    failure_reasons: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class BenchmarkRunResult:
    """Complete result of running a benchmark suite."""

    run_id: str
    suite_id: str
    status: str = "completed"
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    case_results: list[BenchmarkCaseResult] = field(default_factory=list)
