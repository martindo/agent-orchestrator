"""Organizational Skill Map — data models.

Defines SkillRecord, SkillMetrics, and SkillCoverage for mapping
organizational capabilities to agents, teams, evidence, and success rates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SkillMaturity(str, Enum):
    """Maturity level of an organizational skill."""

    NASCENT = "nascent"          # <10 executions, untested
    DEVELOPING = "developing"    # 10-50 executions, inconsistent
    ESTABLISHED = "established"  # 50-200 executions, reliable
    EXPERT = "expert"            # 200+ executions, high success


@dataclass
class SkillMetrics:
    """Aggregated performance metrics for a skill.

    Updated incrementally as agents execute work.
    """

    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    total_confidence: float = 0.0
    total_duration_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        """Success rate as a fraction (0.0-1.0)."""
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions

    @property
    def average_confidence(self) -> float:
        """Average confidence across executions."""
        if self.total_executions == 0:
            return 0.0
        return self.total_confidence / self.total_executions

    @property
    def average_duration(self) -> float:
        """Average execution duration in seconds."""
        if self.total_executions == 0:
            return 0.0
        return self.total_duration_seconds / self.total_executions

    @property
    def maturity(self) -> SkillMaturity:
        """Derive maturity from execution count and success rate."""
        if self.total_executions < 10:
            return SkillMaturity.NASCENT
        if self.total_executions < 50 or self.success_rate < 0.7:
            return SkillMaturity.DEVELOPING
        if self.total_executions < 200 or self.success_rate < 0.85:
            return SkillMaturity.ESTABLISHED
        return SkillMaturity.EXPERT

    def record_execution(
        self, *, success: bool, confidence: float, duration_seconds: float,
    ) -> None:
        """Record a new execution observation.

        Args:
            success: Whether the execution succeeded.
            confidence: Confidence score of the execution.
            duration_seconds: Duration of the execution.
        """
        self.total_executions += 1
        if success:
            self.successful_executions += 1
        else:
            self.failed_executions += 1
        self.total_confidence += confidence
        self.total_duration_seconds += duration_seconds


@dataclass
class SkillRecord:
    """A registered organizational skill mapping agents and evidence.

    Tracks which agents provide a skill, their collective performance,
    and what knowledge sources back the skill.
    """

    skill_id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)

    # Agents that provide this skill
    agent_ids: list[str] = field(default_factory=list)

    # Phases where this skill is exercised
    phase_ids: list[str] = field(default_factory=list)

    # Knowledge sources backing this skill
    knowledge_sources: list[str] = field(default_factory=list)

    # Aggregated metrics
    metrics: SkillMetrics = field(default_factory=SkillMetrics)

    # Per-agent breakdown
    agent_metrics: dict[str, SkillMetrics] = field(default_factory=dict)

    # Timestamps
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def record_agent_execution(
        self,
        agent_id: str,
        *,
        success: bool,
        confidence: float,
        duration_seconds: float,
    ) -> None:
        """Record an execution for a specific agent under this skill.

        Updates both the aggregate metrics and per-agent metrics.

        Args:
            agent_id: The agent that executed.
            success: Whether the execution succeeded.
            confidence: Confidence score.
            duration_seconds: Execution duration.
        """
        self.metrics.record_execution(
            success=success, confidence=confidence, duration_seconds=duration_seconds,
        )
        if agent_id not in self.agent_metrics:
            self.agent_metrics[agent_id] = SkillMetrics()
        self.agent_metrics[agent_id].record_execution(
            success=success, confidence=confidence, duration_seconds=duration_seconds,
        )
        if agent_id not in self.agent_ids:
            self.agent_ids.append(agent_id)
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class SkillCoverage:
    """Summary of organizational skill coverage for reporting."""

    total_skills: int = 0
    covered_skills: int = 0
    weak_skills: list[str] = field(default_factory=list)
    strong_skills: list[str] = field(default_factory=list)
    unassigned_skills: list[str] = field(default_factory=list)
    maturity_distribution: dict[str, int] = field(default_factory=dict)

    @property
    def coverage_ratio(self) -> float:
        """Fraction of skills with at least one agent assigned."""
        if self.total_skills == 0:
            return 0.0
        return self.covered_skills / self.total_skills
