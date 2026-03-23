"""Tests for SimulationSandbox — workflow replay and comparison."""

from __future__ import annotations

from typing import Any

import pytest

from agent_orchestrator.simulation.models import (
    ComparisonResult,
    SimulationConfig,
    SimulationOutcome,
    SimulationResult,
    SimulationStatus,
)
from agent_orchestrator.simulation.sandbox import SimulationSandbox


def _make_config(
    simulation_id: str = "sim-001",
    *,
    max_items: int = 100,
    dry_run: bool = True,
) -> SimulationConfig:
    return SimulationConfig(
        simulation_id=simulation_id,
        name="Test Simulation",
        max_items=max_items,
        dry_run=dry_run,
    )


def _make_historical_items(
    count: int = 5,
    *,
    status: str = "completed",
    confidence: float = 0.7,
) -> list[dict[str, Any]]:
    return [
        {
            "id": f"wi-{i}",
            "type_id": "task",
            "data": {"query": f"test-{i}"},
            "status": status,
            "results": {"agent-1": {"output": f"result-{i}"}},
            "confidence": confidence,
            "phases_completed": 3,
        }
        for i in range(count)
    ]


class TestDryRun:
    """Test dry-run simulations (no LLM calls)."""

    @pytest.mark.asyncio()
    async def test_dry_run_mirrors_historical(self) -> None:
        sandbox = SimulationSandbox()
        config = _make_config(dry_run=True)
        items = _make_historical_items(3)

        result = await sandbox.run_simulation(
            config=config,
            historical_items=items,
        )

        assert result.status == SimulationStatus.COMPLETED
        assert result.items_processed == 3
        assert result.items_same == 3
        assert result.items_improved == 0
        assert result.items_regressed == 0
        assert result.confidence_improvement == pytest.approx(0.0)

    @pytest.mark.asyncio()
    async def test_dry_run_empty_items(self) -> None:
        sandbox = SimulationSandbox()
        result = await sandbox.run_simulation(
            config=_make_config(),
            historical_items=[],
        )
        assert result.items_processed == 0
        assert result.status == SimulationStatus.COMPLETED


class TestWithExecuteFn:
    """Test simulations with a custom execute function."""

    @pytest.mark.asyncio()
    async def test_improved_workflow(self) -> None:
        async def better_workflow(data: dict, config: SimulationConfig) -> dict:
            return {
                "status": "completed",
                "confidence": 0.95,  # Higher than historical 0.7
                "results": {"agent-1": {"output": "improved"}},
                "phases_completed": 3,
            }

        sandbox = SimulationSandbox()
        config = _make_config(dry_run=False)
        items = _make_historical_items(3, confidence=0.7)

        result = await sandbox.run_simulation(
            config=config,
            historical_items=items,
            execute_fn=better_workflow,
        )

        assert result.items_improved == 3
        assert result.confidence_improvement > 0
        assert result.avg_simulated_confidence == pytest.approx(0.95)

    @pytest.mark.asyncio()
    async def test_regressed_workflow(self) -> None:
        async def worse_workflow(data: dict, config: SimulationConfig) -> dict:
            return {
                "status": "completed",
                "confidence": 0.3,  # Lower than historical 0.7
                "results": {},
                "phases_completed": 2,
            }

        sandbox = SimulationSandbox()
        config = _make_config(dry_run=False)
        items = _make_historical_items(2, confidence=0.7)

        result = await sandbox.run_simulation(
            config=config,
            historical_items=items,
            execute_fn=worse_workflow,
        )

        assert result.items_regressed == 2
        assert result.confidence_improvement < 0

    @pytest.mark.asyncio()
    async def test_new_success(self) -> None:
        async def fixed_workflow(data: dict, config: SimulationConfig) -> dict:
            return {
                "status": "completed",
                "confidence": 0.8,
                "results": {},
                "phases_completed": 3,
            }

        sandbox = SimulationSandbox()
        config = _make_config(dry_run=False)
        items = _make_historical_items(1, status="failed", confidence=0.2)

        result = await sandbox.run_simulation(
            config=config,
            historical_items=items,
            execute_fn=fixed_workflow,
        )

        assert result.items_new_success == 1

    @pytest.mark.asyncio()
    async def test_new_failure(self) -> None:
        async def broken_workflow(data: dict, config: SimulationConfig) -> dict:
            return {
                "status": "failed",
                "confidence": 0.1,
                "results": {},
                "phases_completed": 1,
            }

        sandbox = SimulationSandbox()
        config = _make_config(dry_run=False)
        items = _make_historical_items(1, status="completed", confidence=0.8)

        result = await sandbox.run_simulation(
            config=config,
            historical_items=items,
            execute_fn=broken_workflow,
        )

        assert result.items_new_failure == 1


class TestErrorHandling:
    """Test error handling during simulation."""

    @pytest.mark.asyncio()
    async def test_execute_fn_error(self) -> None:
        async def failing_workflow(data: dict, config: SimulationConfig) -> dict:
            raise RuntimeError("LLM unavailable")

        sandbox = SimulationSandbox()
        config = _make_config(dry_run=False)
        items = _make_historical_items(3)

        result = await sandbox.run_simulation(
            config=config,
            historical_items=items,
            execute_fn=failing_workflow,
        )

        assert result.items_errored == 3
        assert len(result.errors) == 3
        assert result.items_processed == 0


class TestMaxItems:
    """Test item limiting."""

    @pytest.mark.asyncio()
    async def test_max_items_limit(self) -> None:
        sandbox = SimulationSandbox()
        config = _make_config(max_items=2)
        items = _make_historical_items(10)

        result = await sandbox.run_simulation(
            config=config,
            historical_items=items,
        )

        assert result.items_processed == 2


class TestSimulationManagement:
    """Test simulation listing and retrieval."""

    @pytest.mark.asyncio()
    async def test_list_simulations(self) -> None:
        sandbox = SimulationSandbox()
        await sandbox.run_simulation(
            config=_make_config("sim-1"),
            historical_items=_make_historical_items(1),
        )
        await sandbox.run_simulation(
            config=_make_config("sim-2"),
            historical_items=_make_historical_items(1),
        )
        sims = sandbox.list_simulations()
        assert len(sims) == 2

    @pytest.mark.asyncio()
    async def test_get_simulation(self) -> None:
        sandbox = SimulationSandbox()
        await sandbox.run_simulation(
            config=_make_config("sim-get"),
            historical_items=_make_historical_items(1),
        )
        result = sandbox.get_simulation("sim-get")
        assert result is not None
        assert result.simulation_id == "sim-get"

    def test_get_nonexistent(self) -> None:
        sandbox = SimulationSandbox()
        assert sandbox.get_simulation("missing") is None


class TestOutcomeClassification:
    """Test the outcome classification logic."""

    def test_same(self) -> None:
        outcome = SimulationSandbox._classify_outcome("completed", "completed", 0.02)
        assert outcome == SimulationOutcome.SAME

    def test_improved(self) -> None:
        outcome = SimulationSandbox._classify_outcome("completed", "completed", 0.15)
        assert outcome == SimulationOutcome.IMPROVED

    def test_regressed(self) -> None:
        outcome = SimulationSandbox._classify_outcome("completed", "completed", -0.2)
        assert outcome == SimulationOutcome.REGRESSED

    def test_new_failure(self) -> None:
        outcome = SimulationSandbox._classify_outcome("completed", "failed", 0.0)
        assert outcome == SimulationOutcome.NEW_FAILURE

    def test_new_success(self) -> None:
        outcome = SimulationSandbox._classify_outcome("failed", "completed", 0.0)
        assert outcome == SimulationOutcome.NEW_SUCCESS


class TestSimulationResult:
    """Test SimulationResult computed properties."""

    def test_improvement_rate(self) -> None:
        result = SimulationResult(
            simulation_id="test",
            config=_make_config(),
            items_processed=10,
            items_improved=3,
        )
        assert result.improvement_rate == pytest.approx(0.3)

    def test_regression_rate(self) -> None:
        result = SimulationResult(
            simulation_id="test",
            config=_make_config(),
            items_processed=10,
            items_regressed=2,
        )
        assert result.regression_rate == pytest.approx(0.2)

    def test_empty_rates(self) -> None:
        result = SimulationResult(
            simulation_id="test",
            config=_make_config(),
        )
        assert result.improvement_rate == 0.0
        assert result.regression_rate == 0.0


class TestSummary:
    """Test simulation summary."""

    @pytest.mark.asyncio()
    async def test_summary(self) -> None:
        sandbox = SimulationSandbox()
        await sandbox.run_simulation(
            config=_make_config("sim-a"),
            historical_items=_make_historical_items(1),
        )
        summary = sandbox.summary()
        assert summary["total_simulations"] == 1
        assert summary["by_status"]["completed"] == 1
