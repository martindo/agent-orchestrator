"""Simulation Sandbox — replay historical work items against new workflows.

Provides a safe, isolated execution environment where new workflows can
be tested against historical data without side effects.  Compares simulated
outcomes against historical results to identify improvements and regressions.

Thread-safe: Simulation state is protected by an internal lock.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_orchestrator.simulation.models import (
    ComparisonResult,
    SimulationConfig,
    SimulationOutcome,
    SimulationResult,
    SimulationStatus,
)

logger = logging.getLogger(__name__)

# Confidence improvement threshold to classify as "improved"
IMPROVEMENT_THRESHOLD = 0.05
REGRESSION_THRESHOLD = -0.05


class SimulationSandbox:
    """Sandbox for simulating workflows against historical work items.

    Replays work items through a modified workflow using a provided
    execution function, then compares outcomes against historical results.

    Usage:
        sandbox = SimulationSandbox()

        config = SimulationConfig(
            simulation_id="sim-001",
            name="Test workflow v2",
            profile_name="content-moderation-v2",
            max_items=100,
        )
        result = await sandbox.run_simulation(
            config=config,
            historical_items=items,
            execute_fn=my_execute_fn,
        )
        print(f"Improvement rate: {result.improvement_rate:.1%}")
    """

    def __init__(self, persistence_dir: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._simulations: dict[str, SimulationResult] = {}
        self._persistence_dir = persistence_dir
        self._persistence_file: Path | None = None
        if persistence_dir is not None:
            persistence_dir.mkdir(parents=True, exist_ok=True)
            self._persistence_file = persistence_dir / "simulations.jsonl"
            if not self._persistence_file.exists():
                self._persistence_file.touch()
            self._load_simulations()

    def get_simulation(self, simulation_id: str) -> SimulationResult | None:
        """Get a simulation result by ID.

        Args:
            simulation_id: The simulation identifier.

        Returns:
            The simulation result, or None if not found.
        """
        with self._lock:
            return self._simulations.get(simulation_id)

    def list_simulations(self) -> list[SimulationResult]:
        """List all simulation results.

        Returns:
            All simulation results, newest first.
        """
        with self._lock:
            return sorted(
                self._simulations.values(),
                key=lambda s: s.started_at or s.config.created_at,
                reverse=True,
            )

    def cancel_simulation(self, simulation_id: str) -> bool:
        """Mark a simulation as cancelled.

        Args:
            simulation_id: The simulation to cancel.

        Returns:
            True if found and cancelled, False otherwise.
        """
        with self._lock:
            sim = self._simulations.get(simulation_id)
            if sim is None:
                return False
            if sim.status == SimulationStatus.RUNNING:
                sim.status = SimulationStatus.CANCELLED
                return True
            return False

    async def run_simulation(
        self,
        *,
        config: SimulationConfig,
        historical_items: list[dict[str, Any]],
        execute_fn: Any | None = None,
    ) -> SimulationResult:
        """Run a simulation against historical work items.

        Each historical item should be a dict with at minimum:
        - ``id``: Work item identifier
        - ``data``: Original input data
        - ``status``: Historical outcome status (e.g., "completed", "failed")
        - ``results``: Historical agent outputs (dict)

        Optionally:
        - ``confidence``: Historical aggregate confidence
        - ``phases_completed``: Number of phases completed

        Args:
            config: Simulation configuration.
            historical_items: List of historical work item dicts.
            execute_fn: Async function(work_data, config) -> dict with
                keys: status, confidence, results, phases_completed.
                If None, a dry-run comparison is performed.

        Returns:
            Complete SimulationResult with per-item comparisons.
        """
        result = SimulationResult(
            simulation_id=config.simulation_id,
            config=config,
            status=SimulationStatus.RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
            total_items=len(historical_items),
        )

        with self._lock:
            self._simulations[config.simulation_id] = result

        start_time = time.monotonic()

        # Apply item limit
        items_to_process = historical_items[:config.max_items]

        # Filter by type if specified
        if config.include_types:
            items_to_process = [
                item for item in items_to_process
                if item.get("type_id", "") in config.include_types
            ]
            result.total_items = len(items_to_process)

        # Accumulate confidence sums for averaging
        hist_conf_sum = 0.0
        sim_conf_sum = 0.0

        for item in items_to_process:
            # Check for cancellation
            with self._lock:
                if result.status == SimulationStatus.CANCELLED:
                    break

            item_id = item.get("id", str(uuid.uuid4()))
            hist_status = item.get("status", "unknown")
            hist_confidence = float(item.get("confidence", 0.0))
            hist_phases = int(item.get("phases_completed", 0))

            try:
                if execute_fn is not None and not config.dry_run:
                    # Execute through the simulated workflow
                    sim_output = await execute_fn(
                        copy.deepcopy(item.get("data", {})),
                        config,
                    )
                    sim_status = sim_output.get("status", "unknown")
                    sim_confidence = float(sim_output.get("confidence", 0.0))
                    sim_phases = int(sim_output.get("phases_completed", 0))
                    agent_results = sim_output.get("results", {})
                else:
                    # Dry run — assume same outcome
                    sim_status = hist_status
                    sim_confidence = hist_confidence
                    sim_phases = hist_phases
                    agent_results = {}

                # Classify outcome
                conf_delta = sim_confidence - hist_confidence
                phase_delta = sim_phases - hist_phases
                outcome = self._classify_outcome(
                    hist_status, sim_status, conf_delta,
                )

                comparison = ComparisonResult(
                    work_item_id=item_id,
                    outcome=outcome,
                    historical_status=hist_status,
                    historical_confidence=hist_confidence,
                    historical_phases_completed=hist_phases,
                    simulated_status=sim_status,
                    simulated_confidence=sim_confidence,
                    simulated_phases_completed=sim_phases,
                    confidence_delta=conf_delta,
                    phase_delta=phase_delta,
                    agent_results=agent_results,
                )

                result.comparisons.append(comparison)
                result.items_processed += 1
                hist_conf_sum += hist_confidence
                sim_conf_sum += sim_confidence

                if outcome == SimulationOutcome.IMPROVED:
                    result.items_improved += 1
                elif outcome == SimulationOutcome.REGRESSED:
                    result.items_regressed += 1
                elif outcome == SimulationOutcome.SAME:
                    result.items_same += 1
                elif outcome == SimulationOutcome.NEW_SUCCESS:
                    result.items_new_success += 1
                elif outcome == SimulationOutcome.NEW_FAILURE:
                    result.items_new_failure += 1

            except Exception as exc:
                result.items_errored += 1
                result.errors.append(f"Item {item_id}: {exc}")
                logger.warning(
                    "Simulation error for item %s: %s", item_id, exc, exc_info=True,
                )

        # Compute averages
        if result.items_processed > 0:
            result.avg_historical_confidence = hist_conf_sum / result.items_processed
            result.avg_simulated_confidence = sim_conf_sum / result.items_processed
            result.confidence_improvement = (
                result.avg_simulated_confidence - result.avg_historical_confidence
            )

        result.duration_seconds = time.monotonic() - start_time
        result.completed_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            if result.status != SimulationStatus.CANCELLED:
                result.status = (
                    SimulationStatus.COMPLETED
                    if not result.errors
                    else SimulationStatus.COMPLETED
                )

        # Persist result if persistence is configured
        self._persist_simulation(result)

        logger.info(
            "Simulation %s completed: %d/%d processed, "
            "%d improved, %d regressed, %d same, "
            "confidence delta=%.3f",
            config.simulation_id,
            result.items_processed,
            result.total_items,
            result.items_improved,
            result.items_regressed,
            result.items_same,
            result.confidence_improvement,
        )

        return result

    @staticmethod
    def _classify_outcome(
        hist_status: str,
        sim_status: str,
        confidence_delta: float,
    ) -> SimulationOutcome:
        """Classify the outcome of a simulation comparison.

        Args:
            hist_status: Historical work item status.
            sim_status: Simulated work item status.
            confidence_delta: Simulated minus historical confidence.

        Returns:
            The classified outcome.
        """
        hist_success = hist_status in ("completed", "COMPLETED")
        sim_success = sim_status in ("completed", "COMPLETED")

        if hist_success and not sim_success:
            return SimulationOutcome.NEW_FAILURE
        if not hist_success and sim_success:
            return SimulationOutcome.NEW_SUCCESS
        if confidence_delta > IMPROVEMENT_THRESHOLD:
            return SimulationOutcome.IMPROVED
        if confidence_delta < REGRESSION_THRESHOLD:
            return SimulationOutcome.REGRESSED
        return SimulationOutcome.SAME

    def summary(self) -> dict[str, Any]:
        """Return summary of all simulations.

        Returns:
            Dict with total count, status breakdown, and recent IDs.
        """
        with self._lock:
            by_status: dict[str, int] = {}
            for sim in self._simulations.values():
                key = sim.status.value
                by_status[key] = by_status.get(key, 0) + 1
            return {
                "total_simulations": len(self._simulations),
                "by_status": by_status,
                "simulation_ids": list(self._simulations.keys()),
            }

    def _persist_simulation(self, result: SimulationResult) -> None:
        """Append a simulation result to the persistent store.

        Args:
            result: The simulation result to persist.
        """
        if self._persistence_file is None:
            return
        try:
            record = {
                "simulation_id": result.simulation_id,
                "status": result.status.value,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
                "duration_seconds": result.duration_seconds,
                "total_items": result.total_items,
                "items_processed": result.items_processed,
                "items_improved": result.items_improved,
                "items_regressed": result.items_regressed,
                "items_same": result.items_same,
                "items_new_success": result.items_new_success,
                "items_new_failure": result.items_new_failure,
                "items_errored": result.items_errored,
                "avg_historical_confidence": result.avg_historical_confidence,
                "avg_simulated_confidence": result.avg_simulated_confidence,
                "confidence_improvement": result.confidence_improvement,
                "errors": result.errors,
                "config": asdict(result.config),
            }
            with open(self._persistence_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        except OSError as exc:
            logger.warning("Failed to persist simulation: %s", exc)

    def _load_simulations(self) -> None:
        """Load existing simulations from persistent store."""
        if self._persistence_file is None or not self._persistence_file.exists():
            return
        try:
            text = self._persistence_file.read_text(encoding="utf-8").strip()
            if not text:
                return
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                config_data = record.get("config", {})
                config = SimulationConfig(
                    simulation_id=config_data.get("simulation_id", record.get("simulation_id", "")),
                    name=config_data.get("name", ""),
                    description=config_data.get("description", ""),
                    profile_name=config_data.get("profile_name", ""),
                    max_items=config_data.get("max_items", 100),
                    dry_run=config_data.get("dry_run", False),
                )
                result = SimulationResult(
                    simulation_id=record.get("simulation_id", ""),
                    config=config,
                    status=SimulationStatus(record.get("status", "completed")),
                    started_at=record.get("started_at", ""),
                    completed_at=record.get("completed_at", ""),
                    duration_seconds=record.get("duration_seconds", 0.0),
                    total_items=record.get("total_items", 0),
                    items_processed=record.get("items_processed", 0),
                    items_improved=record.get("items_improved", 0),
                    items_regressed=record.get("items_regressed", 0),
                    items_same=record.get("items_same", 0),
                    items_new_success=record.get("items_new_success", 0),
                    items_new_failure=record.get("items_new_failure", 0),
                    items_errored=record.get("items_errored", 0),
                    avg_historical_confidence=record.get("avg_historical_confidence", 0.0),
                    avg_simulated_confidence=record.get("avg_simulated_confidence", 0.0),
                    confidence_improvement=record.get("confidence_improvement", 0.0),
                    errors=record.get("errors", []),
                )
                self._simulations[result.simulation_id] = result
            logger.debug("Loaded %d simulations from disk", len(self._simulations))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load simulations: %s", exc)
