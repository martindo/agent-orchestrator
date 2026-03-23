"""Benchmark Store and Runner — persistent benchmark suites with regression detection.

BenchmarkStore: JSONL persistence for suites and run results.
BenchmarkRunner: Executes benchmark suites, comparing actual vs expected outcomes.

Thread-safe: All public methods use internal lock.
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

from agent_orchestrator.exceptions import PersistenceError
from agent_orchestrator.simulation.models import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkRunResult,
    BenchmarkSuiteConfig,
    SimulationConfig,
)
from agent_orchestrator.simulation.sandbox import SimulationSandbox

logger = logging.getLogger(__name__)


def _suite_to_dict(suite: BenchmarkSuiteConfig) -> dict[str, Any]:
    """Serialize a BenchmarkSuiteConfig to a JSON-safe dict.

    Args:
        suite: The suite config to serialize.

    Returns:
        JSON-serializable dict.
    """
    return asdict(suite)


def _dict_to_suite(d: dict[str, Any]) -> BenchmarkSuiteConfig:
    """Deserialize a dict into a BenchmarkSuiteConfig.

    Args:
        d: Raw dict from JSONL.

    Returns:
        Reconstructed BenchmarkSuiteConfig.
    """
    cases = [BenchmarkCase(**c) for c in d.get("cases", [])]
    return BenchmarkSuiteConfig(
        suite_id=d["suite_id"],
        name=d["name"],
        description=d.get("description", ""),
        profile_name=d.get("profile_name", ""),
        cases=cases,
        created_at=d.get("created_at", ""),
        tags=d.get("tags", []),
    )


def _run_to_dict(result: BenchmarkRunResult) -> dict[str, Any]:
    """Serialize a BenchmarkRunResult to a JSON-safe dict.

    Args:
        result: The run result to serialize.

    Returns:
        JSON-serializable dict.
    """
    return asdict(result)


def _dict_to_run(d: dict[str, Any]) -> BenchmarkRunResult:
    """Deserialize a dict into a BenchmarkRunResult.

    Args:
        d: Raw dict from JSONL.

    Returns:
        Reconstructed BenchmarkRunResult.
    """
    case_results = [
        BenchmarkCaseResult(**cr) for cr in d.get("case_results", [])
    ]
    return BenchmarkRunResult(
        run_id=d["run_id"],
        suite_id=d["suite_id"],
        status=d.get("status", "completed"),
        started_at=d.get("started_at", ""),
        completed_at=d.get("completed_at", ""),
        duration_seconds=d.get("duration_seconds", 0.0),
        total_cases=d.get("total_cases", 0),
        passed=d.get("passed", 0),
        failed=d.get("failed", 0),
        pass_rate=d.get("pass_rate", 0.0),
        case_results=case_results,
    )


class BenchmarkStore:
    """JSONL-backed persistence for benchmark suites and run results.

    File layout::

        {workspace}/.agent-orchestrator/benchmarks/suites.jsonl
        {workspace}/.agent-orchestrator/benchmarks/runs.jsonl

    Each line is a full JSON snapshot (upsert semantics for suites --
    latest line for a given ID wins on load).

    Thread-safe: All public methods use internal lock.
    """

    def __init__(self, workspace_path: str = "") -> None:
        base = Path(workspace_path) if workspace_path else Path.cwd()
        self._dir = base / ".agent-orchestrator" / "benchmarks"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._suites_file = self._dir / "suites.jsonl"
        self._runs_file = self._dir / "runs.jsonl"
        for f in (self._suites_file, self._runs_file):
            if not f.exists():
                f.touch()
        self._lock = threading.Lock()
        logger.debug("BenchmarkStore initialized at %s", self._dir)

    def _load_suites_map(self) -> dict[str, dict[str, Any]]:
        """Read all suite lines, keeping latest entry per suite_id."""
        suites: dict[str, dict[str, Any]] = {}
        try:
            text = self._suites_file.read_text(encoding="utf-8").strip()
            if not text:
                return suites
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                suites[record["suite_id"]] = record
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read suites: %s", exc, exc_info=True)
        return suites

    def _load_runs_list(self) -> list[dict[str, Any]]:
        """Read all run lines as a list of dicts."""
        runs: list[dict[str, Any]] = []
        try:
            text = self._runs_file.read_text(encoding="utf-8").strip()
            if not text:
                return runs
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                runs.append(json.loads(line))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read runs: %s", exc, exc_info=True)
        return runs

    def save_suite(self, suite: BenchmarkSuiteConfig) -> None:
        """Append a suite snapshot to the persistent store.

        Args:
            suite: The benchmark suite to persist.
        """
        record = _suite_to_dict(suite)
        with self._lock:
            try:
                with open(self._suites_file, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            except OSError as exc:
                raise PersistenceError(f"Failed to save benchmark suite: {exc}") from exc

    def load_suite(self, suite_id: str) -> BenchmarkSuiteConfig | None:
        """Load a specific suite by ID (latest snapshot).

        Args:
            suite_id: The suite identifier.

        Returns:
            The suite config, or None if not found.
        """
        with self._lock:
            latest = self._load_suites_map()
        record = latest.get(suite_id)
        if record is None:
            return None
        return _dict_to_suite(record)

    def list_suites(self) -> list[BenchmarkSuiteConfig]:
        """List all benchmark suites.

        Returns:
            All suites, newest first by created_at.
        """
        with self._lock:
            latest = self._load_suites_map()
        suites = [_dict_to_suite(r) for r in latest.values()]
        suites.sort(key=lambda s: s.created_at, reverse=True)
        return suites

    def delete_suite(self, suite_id: str) -> bool:
        """Delete a suite by rewriting the JSONL without it.

        Args:
            suite_id: The suite to remove.

        Returns:
            True if found and removed, False otherwise.
        """
        with self._lock:
            latest = self._load_suites_map()
            if suite_id not in latest:
                return False
            del latest[suite_id]
            try:
                with open(self._suites_file, "w", encoding="utf-8") as fh:
                    for record in latest.values():
                        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            except OSError as exc:
                raise PersistenceError(f"Failed to delete suite: {exc}") from exc
        return True

    def save_run(self, result: BenchmarkRunResult) -> None:
        """Append a run result to the persistent store.

        Args:
            result: The benchmark run result to persist.
        """
        record = _run_to_dict(result)
        with self._lock:
            try:
                with open(self._runs_file, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            except OSError as exc:
                raise PersistenceError(f"Failed to save benchmark run: {exc}") from exc

    def get_runs(self, suite_id: str, limit: int = 20) -> list[BenchmarkRunResult]:
        """Get run results for a suite, newest first.

        Args:
            suite_id: The suite to filter by.
            limit: Maximum number of runs to return.

        Returns:
            Run results for the suite, newest first.
        """
        with self._lock:
            all_runs = self._load_runs_list()
        matching = [
            _dict_to_run(r) for r in all_runs
            if r.get("suite_id") == suite_id
        ]
        matching.sort(key=lambda r: r.started_at, reverse=True)
        return matching[:limit]

    def get_run(self, run_id: str) -> BenchmarkRunResult | None:
        """Get a single run result by run_id.

        Args:
            run_id: The run identifier.

        Returns:
            The run result, or None if not found.
        """
        with self._lock:
            all_runs = self._load_runs_list()
        for r in all_runs:
            if r.get("run_id") == run_id:
                return _dict_to_run(r)
        return None


class BenchmarkRunner:
    """Executes benchmark suites through SimulationSandbox.

    Compares actual execution outcomes against expected benchmark case
    criteria (status match, minimum confidence, output key presence).
    """

    def __init__(
        self,
        sandbox: SimulationSandbox,
        execute_fn: Any | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._execute_fn = execute_fn

    async def run_suite(
        self,
        suite: BenchmarkSuiteConfig,
    ) -> BenchmarkRunResult:
        """Execute all cases in a benchmark suite and compare outcomes.

        Args:
            suite: The benchmark suite to run.

        Returns:
            Complete BenchmarkRunResult with per-case pass/fail.
        """
        run_id = f"brun-{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc).isoformat()
        start_time = time.monotonic()

        case_results: list[BenchmarkCaseResult] = []
        passed_count = 0
        failed_count = 0

        for case in suite.cases:
            case_result = await self._run_case(case, suite.profile_name)
            case_results.append(case_result)
            if case_result.passed:
                passed_count += 1
            else:
                failed_count += 1

        duration = time.monotonic() - start_time
        total = len(suite.cases)
        pass_rate = passed_count / total if total > 0 else 0.0

        result = BenchmarkRunResult(
            run_id=run_id,
            suite_id=suite.suite_id,
            status="completed",
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=round(duration, 3),
            total_cases=total,
            passed=passed_count,
            failed=failed_count,
            pass_rate=round(pass_rate, 4),
            case_results=case_results,
        )

        logger.info(
            "Benchmark suite %s run %s: %d/%d passed (%.1f%%)",
            suite.suite_id,
            run_id,
            passed_count,
            total,
            pass_rate * 100,
        )
        return result

    async def _run_case(
        self,
        case: BenchmarkCase,
        profile_name: str,
    ) -> BenchmarkCaseResult:
        """Run a single benchmark case through the sandbox.

        Args:
            case: The benchmark case to execute.
            profile_name: Profile name from the suite config.

        Returns:
            BenchmarkCaseResult with pass/fail and reasons.
        """
        case_start = time.monotonic()
        failure_reasons: list[str] = []
        actual_status = "unknown"
        actual_confidence = 0.0

        try:
            config = SimulationConfig(
                simulation_id=f"bench-{uuid.uuid4().hex[:8]}",
                name=f"benchmark-case-{case.case_id}",
                profile_name=profile_name,
                max_items=1,
                dry_run=(self._execute_fn is None),
            )

            historical_item = {
                "id": case.case_id,
                "data": copy.deepcopy(case.work_item_data),
                "status": "pending",
                "results": {},
                "confidence": 0.0,
                "phases_completed": 0,
            }

            result = await self._sandbox.run_simulation(
                config=config,
                historical_items=[historical_item],
                execute_fn=self._execute_fn,
            )

            if result.comparisons:
                comparison = result.comparisons[0]
                actual_status = comparison.simulated_status
                actual_confidence = comparison.simulated_confidence
                agent_results = comparison.agent_results
            else:
                actual_status = "no_result"
                agent_results = {}

            failure_reasons = self._check_expectations(
                case, actual_status, actual_confidence, agent_results,
            )

        except Exception as exc:
            actual_status = "error"
            failure_reasons.append(f"Execution error: {exc}")
            logger.warning(
                "Benchmark case %s failed with error: %s",
                case.case_id, exc, exc_info=True,
            )

        duration = time.monotonic() - case_start
        return BenchmarkCaseResult(
            case_id=case.case_id,
            passed=len(failure_reasons) == 0,
            actual_status=actual_status,
            actual_confidence=actual_confidence,
            failure_reasons=failure_reasons,
            duration_seconds=round(duration, 3),
        )

    @staticmethod
    def _check_expectations(
        case: BenchmarkCase,
        actual_status: str,
        actual_confidence: float,
        agent_results: dict[str, Any],
    ) -> list[str]:
        """Compare actual outcomes against case expectations.

        Args:
            case: The benchmark case with expected values.
            actual_status: Actual execution status.
            actual_confidence: Actual confidence score.
            agent_results: Actual agent output dict.

        Returns:
            List of failure reason strings (empty if all passed).
        """
        reasons: list[str] = []

        if actual_status != case.expected_status:
            reasons.append(
                f"Status mismatch: expected '{case.expected_status}', "
                f"got '{actual_status}'",
            )

        if actual_confidence < case.expected_min_confidence:
            reasons.append(
                f"Confidence too low: expected >= {case.expected_min_confidence}, "
                f"got {actual_confidence}",
            )

        for key in case.expected_output_keys:
            if key not in agent_results:
                reasons.append(f"Missing expected output key: '{key}'")

        return reasons

    @staticmethod
    def create_suite_from_history(
        items: list[dict[str, Any]],
        suite_name: str,
        min_confidence: float = 0.0,
    ) -> BenchmarkSuiteConfig:
        """Convert completed work items into a benchmark suite.

        Uses historical outcomes as expected results so that future
        workflow changes can be tested for regressions.

        Args:
            items: List of work item dicts with id, data, status, results,
                and optional confidence.
            suite_name: Name for the new suite.
            min_confidence: Minimum confidence threshold for cases.

        Returns:
            BenchmarkSuiteConfig with cases derived from history.
        """
        cases: list[BenchmarkCase] = []
        for item in items:
            status = item.get("status", "")
            if status not in ("completed", "COMPLETED"):
                continue
            confidence = float(item.get("confidence", 0.0))
            output_keys = list(item.get("results", {}).keys())

            cases.append(BenchmarkCase(
                case_id=item.get("id", f"case-{uuid.uuid4().hex[:8]}"),
                work_item_data=item.get("data", {}),
                expected_status="completed",
                expected_min_confidence=max(min_confidence, confidence * 0.9),
                expected_output_keys=output_keys,
            ))

        return BenchmarkSuiteConfig(
            suite_id=f"suite-{uuid.uuid4().hex[:8]}",
            name=suite_name,
            description=f"Auto-generated from {len(cases)} historical items",
            cases=cases,
        )
