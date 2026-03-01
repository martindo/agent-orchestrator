"""PipelineManager — Tracks work items through user-defined phases.

Replaces v2's hardcoded Phase.REVIEW -> Phase.SECURITY -> Phase.TEST
with a configurable phase graph built from workflow.yaml.

Supports linear and branching phase flows (on_success/on_failure),
skip flags, and work item locking during phase execution.

Thread-safe: All public methods use internal lock.

State Ownership:
- PipelineManager owns work item phase positions and locks.
- WorkQueue owns work item queue ordering.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from agent_orchestrator.configuration.models import WorkflowConfig, WorkflowPhaseConfig
from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus
from agent_orchestrator.exceptions import WorkflowError

logger = logging.getLogger(__name__)


class PhaseResult(str, Enum):
    """Result of phase execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"


@dataclass
class PipelineEntry:
    """Tracks a work item's position in the pipeline."""

    work_item: WorkItem
    current_phase_id: str
    locked: bool = False
    locked_by: str | None = None
    phase_attempts: dict[str, int] = field(default_factory=dict)
    phase_history: list[dict[str, Any]] = field(default_factory=list)
    entered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PipelineManager:
    """Manages work item progression through workflow phases.

    Thread-safe: All public methods use internal lock.

    Usage:
        pm = PipelineManager(workflow_config)
        pm.enter_pipeline(work_item)
        next_phase = pm.get_current_phase("work-id")
        pm.complete_phase("work-id", PhaseResult.SUCCESS)
    """

    def __init__(self, workflow: WorkflowConfig) -> None:
        self._workflow = workflow
        self._phases: dict[str, WorkflowPhaseConfig] = {
            p.id: p for p in workflow.phases
        }
        self._entries: dict[str, PipelineEntry] = {}
        self._lock = threading.Lock()

        if workflow.phases:
            self._initial_phase_id = workflow.phases[0].id
        else:
            self._initial_phase_id = ""

    def enter_pipeline(self, work_item: WorkItem) -> str:
        """Add a work item to the pipeline at the initial phase.

        Args:
            work_item: The work item to enter.

        Returns:
            The initial phase ID.

        Raises:
            WorkflowError: If no phases defined or item already in pipeline.
        """
        with self._lock:
            if not self._initial_phase_id:
                msg = "Workflow has no phases defined"
                raise WorkflowError(msg)

            if work_item.id in self._entries:
                msg = f"Work item '{work_item.id}' already in pipeline"
                raise WorkflowError(msg)

            # Skip to first non-skipped phase
            phase_id = self._find_next_active_phase(self._initial_phase_id)

            entry = PipelineEntry(
                work_item=work_item,
                current_phase_id=phase_id,
            )
            self._entries[work_item.id] = entry
            work_item.current_phase = phase_id
            work_item.status = WorkItemStatus.IN_PROGRESS

            logger.info(
                "Work item '%s' entered pipeline at phase '%s'",
                work_item.id, phase_id,
            )
            return phase_id

    def get_current_phase(self, work_id: str) -> WorkflowPhaseConfig | None:
        """Get the current phase config for a work item.

        Args:
            work_id: Work item ID.

        Returns:
            Current phase config, or None if not in pipeline.
        """
        with self._lock:
            entry = self._entries.get(work_id)
            if entry is None:
                return None
            return self._phases.get(entry.current_phase_id)

    def complete_phase(
        self,
        work_id: str,
        result: PhaseResult,
        phase_data: dict[str, Any] | None = None,
    ) -> str | None:
        """Complete the current phase and advance to next.

        Args:
            work_id: Work item ID.
            result: Phase execution result.
            phase_data: Optional data from phase execution.

        Returns:
            Next phase ID, or None if pipeline is complete.

        Raises:
            WorkflowError: If work item not in pipeline.
        """
        with self._lock:
            entry = self._entries.get(work_id)
            if entry is None:
                msg = f"Work item '{work_id}' not in pipeline"
                raise WorkflowError(msg)

            current_phase = self._phases.get(entry.current_phase_id)
            if current_phase is None:
                msg = f"Phase '{entry.current_phase_id}' not found in workflow"
                raise WorkflowError(msg)

            # Record history
            entry.phase_history.append({
                "phase_id": entry.current_phase_id,
                "result": result.value,
                "data": phase_data or {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # Track attempts
            attempt_key = entry.current_phase_id
            entry.phase_attempts[attempt_key] = entry.phase_attempts.get(attempt_key, 0) + 1

            # Determine next phase
            if current_phase.is_terminal:
                return self._finish_pipeline(entry, result)

            if result == PhaseResult.SUCCESS:
                next_phase_id = current_phase.on_success
            elif result == PhaseResult.FAILURE:
                next_phase_id = current_phase.on_failure
            else:
                next_phase_id = current_phase.on_success

            if not next_phase_id:
                return self._finish_pipeline(entry, result)

            # Skip phases marked with skip=True
            next_phase_id = self._find_next_active_phase(next_phase_id)

            if not next_phase_id:
                return self._finish_pipeline(entry, result)

            entry.current_phase_id = next_phase_id
            entry.work_item.current_phase = next_phase_id
            entry.locked = False
            entry.locked_by = None

            logger.info(
                "Work item '%s' advanced to phase '%s' (result=%s)",
                work_id, next_phase_id, result.value,
            )
            return next_phase_id

    def _find_next_active_phase(self, phase_id: str) -> str:
        """Find the next non-skipped phase starting from phase_id."""
        visited: set[str] = set()
        current = phase_id

        while current and current not in visited:
            visited.add(current)
            phase = self._phases.get(current)
            if phase is None:
                return ""
            if not phase.skip:
                return current
            # Phase is skipped, follow on_success
            logger.debug("Skipping phase '%s'", current)
            current = phase.on_success

        return current

    def _finish_pipeline(self, entry: PipelineEntry, result: PhaseResult) -> None:
        """Mark pipeline as complete for a work item."""
        work_item = entry.work_item
        if result == PhaseResult.FAILURE:
            work_item.status = WorkItemStatus.FAILED
        else:
            work_item.status = WorkItemStatus.COMPLETED
        work_item.completed_at = datetime.now(timezone.utc)
        entry.locked = False
        entry.locked_by = None
        logger.info(
            "Work item '%s' completed pipeline (status=%s)",
            work_item.id, work_item.status.value,
        )
        return None

    def lock_for_execution(self, work_id: str, executor_id: str) -> bool:
        """Lock a work item for phase execution.

        Args:
            work_id: Work item ID.
            executor_id: ID of the executor claiming the lock.

        Returns:
            True if lock acquired, False if already locked.
        """
        with self._lock:
            entry = self._entries.get(work_id)
            if entry is None:
                return False
            if entry.locked:
                return False
            entry.locked = True
            entry.locked_by = executor_id
            return True

    def unlock(self, work_id: str) -> None:
        """Release execution lock on a work item."""
        with self._lock:
            entry = self._entries.get(work_id)
            if entry is not None:
                entry.locked = False
                entry.locked_by = None

    def get_entry(self, work_id: str) -> PipelineEntry | None:
        """Get pipeline entry for a work item."""
        with self._lock:
            return self._entries.get(work_id)

    def get_all_entries(self) -> list[PipelineEntry]:
        """Get all pipeline entries."""
        with self._lock:
            return list(self._entries.values())

    def remove_entry(self, work_id: str) -> None:
        """Remove a work item from the pipeline."""
        with self._lock:
            self._entries.pop(work_id, None)

    def get_stats(self) -> dict[str, Any]:
        """Get pipeline statistics."""
        with self._lock:
            by_phase: dict[str, int] = {}
            by_status: dict[str, int] = {}
            for entry in self._entries.values():
                phase = entry.current_phase_id
                by_phase[phase] = by_phase.get(phase, 0) + 1
                status = entry.work_item.status.value
                by_status[status] = by_status.get(status, 0) + 1
            return {
                "total_items": len(self._entries),
                "by_phase": by_phase,
                "by_status": by_status,
            }
