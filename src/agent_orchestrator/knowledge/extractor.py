"""MemoryExtractor — extracts structured memory records from agent outputs.

Inspects agent output dicts for explicit memory declarations and
auto-extracts completion memories from successful work item runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from agent_orchestrator.knowledge.models import MemoryRecord, MemoryType

logger = logging.getLogger(__name__)


def _compute_content_hash(content: dict[str, Any]) -> str:
    """Compute SHA-256 hex digest for a content dict."""
    serialized = json.dumps(content, sort_keys=True, default=str).encode()
    return hashlib.sha256(serialized).hexdigest()


def _parse_memory_type(raw: str) -> MemoryType | None:
    """Convert a raw string to a MemoryType enum, returning None on failure."""
    try:
        return MemoryType(raw.lower())
    except ValueError:
        return None


class MemoryExtractor:
    """Static helper that converts agent output dicts into MemoryRecord lists."""

    @staticmethod
    def extract_from_agent_output(
        agent_id: str,
        work_id: str,
        phase_id: str,
        run_id: str,
        app_id: str,
        output: dict[str, Any],
    ) -> list[MemoryRecord]:
        """Extract declared memories from an agent output dict.

        Looks for a ``memories`` key containing a list of memory entries.
        Each entry must have at minimum ``type``, ``title``, and ``content``.
        Missing optional fields receive sensible defaults.

        Args:
            agent_id: The agent that produced the output.
            work_id: Work item identifier.
            phase_id: Phase identifier.
            run_id: Current run identifier.
            app_id: Application identifier.
            output: The full agent output dict (may contain a ``memories`` key).

        Returns:
            A list of MemoryRecord instances (empty if no valid memories found).
        """
        raw_memories = output.get("memories")
        if not isinstance(raw_memories, list):
            return []

        output_confidence: float = output.get("confidence", 0.5)
        if not isinstance(output_confidence, (int, float)):
            output_confidence = 0.5

        records: list[MemoryRecord] = []

        for idx, entry in enumerate(raw_memories):
            if not isinstance(entry, dict):
                logger.warning(
                    "Skipping non-dict memory entry at index %d from agent %s",
                    idx,
                    agent_id,
                )
                continue

            # Validate required fields
            raw_type = entry.get("type")
            title = entry.get("title")
            content = entry.get("content")

            if raw_type is None or title is None or content is None:
                logger.warning(
                    "Skipping memory entry at index %d from agent %s: "
                    "missing required field (type=%r, title=%r, content present=%s)",
                    idx,
                    agent_id,
                    raw_type,
                    title,
                    content is not None,
                )
                continue

            memory_type = _parse_memory_type(str(raw_type))
            if memory_type is None:
                logger.warning(
                    "Skipping memory entry at index %d from agent %s: "
                    "unknown memory type %r",
                    idx,
                    agent_id,
                    raw_type,
                )
                continue

            if not isinstance(title, str) or not title.strip():
                logger.warning(
                    "Skipping memory entry at index %d from agent %s: "
                    "title must be a non-empty string",
                    idx,
                    agent_id,
                )
                continue

            if not isinstance(content, dict):
                logger.warning(
                    "Skipping memory entry at index %d from agent %s: "
                    "content must be a dict, got %s",
                    idx,
                    agent_id,
                    type(content).__name__,
                )
                continue

            tags = entry.get("tags", [])
            if not isinstance(tags, list):
                tags = []

            confidence = entry.get("confidence", output_confidence)
            if not isinstance(confidence, (int, float)):
                confidence = output_confidence

            try:
                record = MemoryRecord(
                    memory_id=str(uuid.uuid4()),
                    memory_type=memory_type,
                    title=title.strip(),
                    content=content,
                    content_hash=_compute_content_hash(content),
                    tags=[str(t) for t in tags],
                    confidence=float(confidence),
                    source_agent_id=agent_id,
                    source_work_id=work_id,
                    source_phase_id=phase_id,
                    source_run_id=run_id,
                    app_id=app_id,
                    timestamp=datetime.now(timezone.utc),
                    expires_at=None,
                    superseded_by=None,
                    version=1,
                    metadata={},
                )
                records.append(record)
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "Failed to create MemoryRecord from entry at index %d "
                    "from agent %s: %s",
                    idx,
                    agent_id,
                    exc,
                    exc_info=True,
                )

        if records:
            logger.info(
                "Extracted %d memory records from agent %s output for work %s",
                len(records),
                agent_id,
                work_id,
            )

        return records

    @staticmethod
    def extract_completion_memories(
        work_id: str,
        run_id: str,
        app_id: str,
        results: dict[str, Any],
        phases_completed: list[str],
    ) -> list[MemoryRecord]:
        """Auto-extract memory records from a successful work item completion.

        Creates two memories:
        - A DECISION memory capturing the final aggregated results.
        - A STRATEGY memory summarising the phase execution.

        Args:
            work_id: The completed work item identifier.
            run_id: Current run identifier.
            app_id: Application identifier.
            results: Aggregated results dict from the work item execution.
            phases_completed: List of phase IDs that were executed.

        Returns:
            A list containing the two auto-extracted MemoryRecord instances.
        """
        now = datetime.now(timezone.utc)
        records: list[MemoryRecord] = []

        # --- Decision memory: final aggregated results ---
        avg_confidence = _average_confidence(results)

        decision_content = dict(results)
        decision_record = MemoryRecord(
            memory_id=str(uuid.uuid4()),
            memory_type=MemoryType.DECISION,
            title=f"Work completion: {work_id}",
            content=decision_content,
            content_hash=_compute_content_hash(decision_content),
            tags=["auto-extracted", "completion"],
            confidence=avg_confidence,
            source_agent_id="system",
            source_work_id=work_id,
            source_phase_id="completion",
            source_run_id=run_id,
            app_id=app_id,
            timestamp=now,
            expires_at=None,
            superseded_by=None,
            version=1,
            metadata={},
        )
        records.append(decision_record)

        # --- Strategy memory: phase execution summary ---
        strategy_content: dict[str, Any] = {
            "phases_completed": phases_completed,
            "agent_count": len(results),
        }
        strategy_record = MemoryRecord(
            memory_id=str(uuid.uuid4()),
            memory_type=MemoryType.STRATEGY,
            title=f"Execution strategy: {work_id}",
            content=strategy_content,
            content_hash=_compute_content_hash(strategy_content),
            tags=["auto-extracted", "strategy"],
            confidence=0.8,
            source_agent_id="system",
            source_work_id=work_id,
            source_phase_id="completion",
            source_run_id=run_id,
            app_id=app_id,
            timestamp=now,
            expires_at=None,
            superseded_by=None,
            version=1,
            metadata={},
        )
        records.append(strategy_record)

        logger.info(
            "Extracted %d completion memories for work %s (phases: %s)",
            len(records),
            work_id,
            ", ".join(phases_completed),
        )

        return records


def _average_confidence(results: dict[str, Any]) -> float:
    """Compute average confidence from a results dict.

    Scans top-level values for dicts containing a ``confidence`` key
    with a numeric value. Returns the mean, or 0.5 if no confidence
    values are found.
    """
    confidences: list[float] = []
    for value in results.values():
        if isinstance(value, dict):
            conf = value.get("confidence")
            if isinstance(conf, (int, float)):
                confidences.append(float(conf))

    if not confidences:
        return 0.5

    return sum(confidences) / len(confidences)
