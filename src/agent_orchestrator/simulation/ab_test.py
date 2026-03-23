"""A/B Test Harness — compare two workflow variants head-to-head.

Runs the same dataset through two workflow configurations via
SimulationSandbox, then compares per-item and aggregate outcomes
to determine which variant performs better.

Thread-safe: Relies on SimulationSandbox's internal locking.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent_orchestrator.simulation.models import SimulationConfig, SimulationResult
from agent_orchestrator.simulation.sandbox import SimulationSandbox

logger = logging.getLogger(__name__)


@dataclass
class ABTestConfig:
    """Configuration for an A/B test comparing two workflow variants."""

    test_id: str
    name: str
    variant_a: dict[str, Any] = field(default_factory=dict)
    variant_b: dict[str, Any] = field(default_factory=dict)
    dataset_id: str = ""
    max_items: int = 100


@dataclass
class ABItemComparison:
    """Per-item comparison between variant A and variant B."""

    item_id: str
    a_confidence: float
    b_confidence: float
    a_status: str
    b_status: str
    winner: str  # "a", "b", or "tie"


@dataclass
class ABComparison:
    """Aggregate comparison between variant A and variant B."""

    winner: str  # "a", "b", or "tie"
    a_pass_rate: float
    b_pass_rate: float
    a_avg_confidence: float
    b_avg_confidence: float
    items_a_better: int
    items_b_better: int
    items_tied: int
    per_item: list[ABItemComparison] = field(default_factory=list)


@dataclass
class ABTestResult:
    """Complete result of an A/B test run."""

    test_id: str
    variant_a_results: SimulationResult
    variant_b_results: SimulationResult
    comparison: ABComparison
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0


class ABTestRunner:
    """Run A/B tests comparing two workflow variants.

    Uses SimulationSandbox to execute each variant against the same
    dataset, then produces a head-to-head comparison.

    Usage:
        runner = ABTestRunner(sandbox)
        result = await runner.run_test(config, historical_items)
        summary = runner.summarize(result)
    """

    def __init__(self, sandbox: SimulationSandbox) -> None:
        self._sandbox = sandbox

    async def run_test(
        self,
        config: ABTestConfig,
        historical_items: list[dict[str, Any]],
    ) -> ABTestResult:
        """Run an A/B test with two workflow variants.

        Args:
            config: Test configuration with variant overrides.
            historical_items: Dataset to test against.

        Returns:
            ABTestResult with per-item and aggregate comparisons.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        start_time = time.monotonic()

        items = historical_items[:config.max_items]

        # Run variant A
        config_a = SimulationConfig(
            simulation_id=f"ab-{config.test_id}-a-{uuid.uuid4().hex[:6]}",
            name=f"{config.name} — Variant A",
            workflow_overrides=config.variant_a,
            max_items=config.max_items,
            dry_run=True,
        )
        result_a = await self._sandbox.run_simulation(
            config=config_a,
            historical_items=items,
        )

        # Run variant B
        config_b = SimulationConfig(
            simulation_id=f"ab-{config.test_id}-b-{uuid.uuid4().hex[:6]}",
            name=f"{config.name} — Variant B",
            workflow_overrides=config.variant_b,
            max_items=config.max_items,
            dry_run=True,
        )
        result_b = await self._sandbox.run_simulation(
            config=config_b,
            historical_items=items,
        )

        comparison = self._compare_results(result_a, result_b)

        duration = time.monotonic() - start_time
        completed_at = datetime.now(timezone.utc).isoformat()

        result = ABTestResult(
            test_id=config.test_id,
            variant_a_results=result_a,
            variant_b_results=result_b,
            comparison=comparison,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=round(duration, 3),
        )

        logger.info(
            "A/B test %s completed: winner=%s, A pass=%.1f%%, B pass=%.1f%%",
            config.test_id,
            comparison.winner,
            comparison.a_pass_rate * 100,
            comparison.b_pass_rate * 100,
        )
        return result

    def _compare_results(
        self,
        result_a: SimulationResult,
        result_b: SimulationResult,
    ) -> ABComparison:
        """Compare two simulation results item-by-item.

        Args:
            result_a: Results from variant A.
            result_b: Results from variant B.

        Returns:
            ABComparison with aggregate and per-item breakdowns.
        """
        # Index comparisons by work item ID
        a_map: dict[str, Any] = {
            c.work_item_id: c for c in result_a.comparisons
        }
        b_map: dict[str, Any] = {
            c.work_item_id: c for c in result_b.comparisons
        }

        all_ids = list(dict.fromkeys(list(a_map.keys()) + list(b_map.keys())))

        per_item: list[ABItemComparison] = []
        items_a_better = 0
        items_b_better = 0
        items_tied = 0

        for item_id in all_ids:
            a_comp = a_map.get(item_id)
            b_comp = b_map.get(item_id)

            a_conf = a_comp.simulated_confidence if a_comp else 0.0
            b_conf = b_comp.simulated_confidence if b_comp else 0.0
            a_stat = a_comp.simulated_status if a_comp else "missing"
            b_stat = b_comp.simulated_status if b_comp else "missing"

            # Determine item winner by status (success beats failure),
            # then by confidence
            a_success = a_stat in ("completed", "COMPLETED")
            b_success = b_stat in ("completed", "COMPLETED")

            if a_success and not b_success:
                winner = "a"
            elif b_success and not a_success:
                winner = "b"
            elif a_conf > b_conf + 0.01:
                winner = "a"
            elif b_conf > a_conf + 0.01:
                winner = "b"
            else:
                winner = "tie"

            if winner == "a":
                items_a_better += 1
            elif winner == "b":
                items_b_better += 1
            else:
                items_tied += 1

            per_item.append(ABItemComparison(
                item_id=item_id,
                a_confidence=a_conf,
                b_confidence=b_conf,
                a_status=a_stat,
                b_status=b_stat,
                winner=winner,
            ))

        # Compute pass rates
        total_a = result_a.items_processed or 1
        total_b = result_b.items_processed or 1
        a_successes = sum(
            1 for c in result_a.comparisons
            if c.simulated_status in ("completed", "COMPLETED")
        )
        b_successes = sum(
            1 for c in result_b.comparisons
            if c.simulated_status in ("completed", "COMPLETED")
        )
        a_pass_rate = a_successes / total_a
        b_pass_rate = b_successes / total_b

        a_avg_conf = result_a.avg_simulated_confidence
        b_avg_conf = result_b.avg_simulated_confidence

        # Overall winner
        if items_a_better > items_b_better:
            overall_winner = "a"
        elif items_b_better > items_a_better:
            overall_winner = "b"
        else:
            overall_winner = "tie"

        return ABComparison(
            winner=overall_winner,
            a_pass_rate=round(a_pass_rate, 4),
            b_pass_rate=round(b_pass_rate, 4),
            a_avg_confidence=round(a_avg_conf, 4),
            b_avg_confidence=round(b_avg_conf, 4),
            items_a_better=items_a_better,
            items_b_better=items_b_better,
            items_tied=items_tied,
            per_item=per_item,
        )

    @staticmethod
    def summarize(result: ABTestResult) -> dict[str, Any]:
        """Create a summary dict suitable for API response.

        Args:
            result: The A/B test result to summarize.

        Returns:
            Summary dict with key metrics.
        """
        c = result.comparison
        return {
            "test_id": result.test_id,
            "winner": c.winner,
            "a_pass_rate": c.a_pass_rate,
            "b_pass_rate": c.b_pass_rate,
            "a_avg_confidence": c.a_avg_confidence,
            "b_avg_confidence": c.b_avg_confidence,
            "items_a_better": c.items_a_better,
            "items_b_better": c.items_b_better,
            "items_tied": c.items_tied,
            "duration_seconds": result.duration_seconds,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "total_items": len(c.per_item),
        }
