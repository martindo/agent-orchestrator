"""Organizational Skill Map — live registry of what the AI organization can do.

Maps skills to agents, tracks success rates and confidence, identifies
coverage gaps and underperforming areas.  Automatically updated from
agent execution events.

Thread-safe: All public methods use an internal reentrant lock.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from agent_orchestrator.catalog.skill_models import (
    SkillCoverage,
    SkillMaturity,
    SkillMetrics,
    SkillRecord,
)

logger = logging.getLogger(__name__)

# Thresholds for coverage analysis
WEAK_SKILL_SUCCESS_RATE = 0.6
STRONG_SKILL_SUCCESS_RATE = 0.85
MIN_EXECUTIONS_FOR_ASSESSMENT = 5


class SkillMap:
    """Live registry of organizational skills and agent capabilities.

    Provides:
    - Skill registration and lookup
    - Automatic metric aggregation from execution results
    - Coverage analysis (strong/weak/unassigned)
    - Per-agent skill performance breakdown

    Thread-safe: All public methods use an internal reentrant lock.

    Usage:
        skill_map = SkillMap(state_dir / "skills")
        skill_map.register_skill(SkillRecord(
            skill_id="regulatory_compliance",
            name="Regulatory Compliance",
            agent_ids=["compliance_agent"],
        ))
        skill_map.record_execution(
            skill_id="regulatory_compliance",
            agent_id="compliance_agent",
            success=True,
            confidence=0.85,
            duration_seconds=12.3,
        )
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._skills: dict[str, SkillRecord] = {}
        self._skills_dir = skills_dir

        if skills_dir is not None:
            skills_dir.mkdir(parents=True, exist_ok=True)
            self._load_state()

    def _load_state(self) -> None:
        """Load skill records from persistence directory."""
        if self._skills_dir is None:
            return
        skills_file = self._skills_dir / "skills.jsonl"
        if not skills_file.exists():
            return
        try:
            with open(skills_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    skill_id = data["skill_id"]

                    metrics_data = data.get("metrics", {})
                    metrics = SkillMetrics(
                        total_executions=metrics_data.get("total_executions", 0),
                        successful_executions=metrics_data.get("successful_executions", 0),
                        failed_executions=metrics_data.get("failed_executions", 0),
                        total_confidence=metrics_data.get("total_confidence", 0.0),
                        total_duration_seconds=metrics_data.get("total_duration_seconds", 0.0),
                    )

                    agent_metrics: dict[str, SkillMetrics] = {}
                    for aid, am_data in data.get("agent_metrics", {}).items():
                        agent_metrics[aid] = SkillMetrics(
                            total_executions=am_data.get("total_executions", 0),
                            successful_executions=am_data.get("successful_executions", 0),
                            failed_executions=am_data.get("failed_executions", 0),
                            total_confidence=am_data.get("total_confidence", 0.0),
                            total_duration_seconds=am_data.get("total_duration_seconds", 0.0),
                        )

                    self._skills[skill_id] = SkillRecord(
                        skill_id=skill_id,
                        name=data.get("name", skill_id),
                        description=data.get("description", ""),
                        tags=data.get("tags", []),
                        agent_ids=data.get("agent_ids", []),
                        phase_ids=data.get("phase_ids", []),
                        knowledge_sources=data.get("knowledge_sources", []),
                        metrics=metrics,
                        agent_metrics=agent_metrics,
                        created_at=data.get("created_at", ""),
                        updated_at=data.get("updated_at", ""),
                    )
            logger.info("Loaded %d skills from persistence", len(self._skills))
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning("Failed to load skill map state: %s", exc)

    def _persist(self) -> None:
        """Write all skills to persistence file."""
        if self._skills_dir is None:
            return
        skills_file = self._skills_dir / "skills.jsonl"
        try:
            with open(skills_file, "w", encoding="utf-8") as f:
                for skill in self._skills.values():
                    record_dict: dict[str, Any] = {
                        "skill_id": skill.skill_id,
                        "name": skill.name,
                        "description": skill.description,
                        "tags": skill.tags,
                        "agent_ids": skill.agent_ids,
                        "phase_ids": skill.phase_ids,
                        "knowledge_sources": skill.knowledge_sources,
                        "metrics": {
                            "total_executions": skill.metrics.total_executions,
                            "successful_executions": skill.metrics.successful_executions,
                            "failed_executions": skill.metrics.failed_executions,
                            "total_confidence": skill.metrics.total_confidence,
                            "total_duration_seconds": skill.metrics.total_duration_seconds,
                        },
                        "agent_metrics": {
                            aid: {
                                "total_executions": am.total_executions,
                                "successful_executions": am.successful_executions,
                                "failed_executions": am.failed_executions,
                                "total_confidence": am.total_confidence,
                                "total_duration_seconds": am.total_duration_seconds,
                            }
                            for aid, am in skill.agent_metrics.items()
                        },
                        "created_at": skill.created_at,
                        "updated_at": skill.updated_at,
                    }
                    f.write(json.dumps(record_dict) + "\n")
        except OSError as exc:
            logger.warning("Failed to persist skill map: %s", exc)

    def register_skill(self, skill: SkillRecord) -> None:
        """Register or update a skill record.

        Args:
            skill: The skill record to register.
        """
        with self._lock:
            existed = skill.skill_id in self._skills
            self._skills[skill.skill_id] = skill
            self._persist()
            verb = "Updated" if existed else "Registered"
            logger.info("%s skill: %s (%s)", verb, skill.skill_id, skill.name)

    def get_skill(self, skill_id: str) -> SkillRecord | None:
        """Get a skill record by ID.

        Args:
            skill_id: The skill identifier.

        Returns:
            The skill record, or None.
        """
        with self._lock:
            return self._skills.get(skill_id)

    def find_skills(
        self,
        *,
        tags: list[str] | None = None,
        agent_id: str | None = None,
        min_success_rate: float | None = None,
        maturity: SkillMaturity | None = None,
    ) -> list[SkillRecord]:
        """Find skills matching all provided filters.

        Args:
            tags: Required tags (all must match).
            agent_id: Skills this agent provides.
            min_success_rate: Minimum aggregate success rate.
            maturity: Required maturity level.

        Returns:
            List of matching skill records.
        """
        with self._lock:
            results: list[SkillRecord] = []
            for skill in self._skills.values():
                if tags and not all(t in skill.tags for t in tags):
                    continue
                if agent_id and agent_id not in skill.agent_ids:
                    continue
                if min_success_rate is not None and skill.metrics.success_rate < min_success_rate:
                    continue
                if maturity is not None and skill.metrics.maturity != maturity:
                    continue
                results.append(skill)
            return results

    def list_all(self) -> list[SkillRecord]:
        """Return all registered skills."""
        with self._lock:
            return list(self._skills.values())

    def unregister_skill(self, skill_id: str) -> bool:
        """Remove a skill by ID.

        Args:
            skill_id: The skill to remove.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if skill_id in self._skills:
                del self._skills[skill_id]
                self._persist()
                logger.info("Unregistered skill: %s", skill_id)
                return True
            return False

    def record_execution(
        self,
        skill_id: str,
        agent_id: str,
        *,
        success: bool,
        confidence: float,
        duration_seconds: float,
    ) -> bool:
        """Record an agent execution observation against a skill.

        Args:
            skill_id: The skill being exercised.
            agent_id: The agent that executed.
            success: Whether execution succeeded.
            confidence: Confidence score.
            duration_seconds: Execution duration.

        Returns:
            True if skill was found and updated, False otherwise.
        """
        with self._lock:
            skill = self._skills.get(skill_id)
            if skill is None:
                return False
            skill.record_agent_execution(
                agent_id,
                success=success,
                confidence=confidence,
                duration_seconds=duration_seconds,
            )
            self._persist()
            return True

    def auto_register_from_profile(
        self,
        agents: list[Any],
        phases: list[Any],
    ) -> int:
        """Auto-register skills from agent definitions and workflow phases.

        Creates one skill per unique agent skill tag, linking agents
        to skills based on their ``skills`` field.

        Args:
            agents: List of AgentDefinition objects.
            phases: List of WorkflowPhaseConfig objects.

        Returns:
            Number of skills registered.
        """
        with self._lock:
            count = 0
            # Build phase lookup for linking skills to phases
            agent_phases: dict[str, list[str]] = {}
            for phase in phases:
                phase_id = getattr(phase, "id", "")
                for agent_id in getattr(phase, "agents", []):
                    agent_phases.setdefault(agent_id, []).append(phase_id)

            # Collect skills from agent definitions
            skill_agents: dict[str, list[str]] = {}
            for agent in agents:
                agent_id = getattr(agent, "id", "")
                for skill_tag in getattr(agent, "skills", []):
                    skill_agents.setdefault(skill_tag, []).append(agent_id)

            for skill_tag, agent_ids in skill_agents.items():
                if skill_tag in self._skills:
                    # Update agent list if new agents discovered
                    existing = self._skills[skill_tag]
                    for aid in agent_ids:
                        if aid not in existing.agent_ids:
                            existing.agent_ids.append(aid)
                    continue

                # Collect phase IDs for this skill's agents
                phase_ids: list[str] = []
                for aid in agent_ids:
                    for pid in agent_phases.get(aid, []):
                        if pid not in phase_ids:
                            phase_ids.append(pid)

                self._skills[skill_tag] = SkillRecord(
                    skill_id=skill_tag,
                    name=skill_tag.replace("_", " ").title(),
                    agent_ids=list(agent_ids),
                    phase_ids=phase_ids,
                    tags=[skill_tag],
                )
                count += 1

            if count > 0:
                self._persist()
                logger.info("Auto-registered %d skills from profile", count)
            return count

    def get_coverage(self) -> SkillCoverage:
        """Analyze skill coverage across the organization.

        Returns:
            SkillCoverage summary with strong/weak/unassigned breakdowns.
        """
        with self._lock:
            coverage = SkillCoverage(total_skills=len(self._skills))
            for skill in self._skills.values():
                if not skill.agent_ids:
                    coverage.unassigned_skills.append(skill.skill_id)
                    continue

                coverage.covered_skills += 1
                mat = skill.metrics.maturity.value
                coverage.maturity_distribution[mat] = (
                    coverage.maturity_distribution.get(mat, 0) + 1
                )

                if skill.metrics.total_executions >= MIN_EXECUTIONS_FOR_ASSESSMENT:
                    if skill.metrics.success_rate < WEAK_SKILL_SUCCESS_RATE:
                        coverage.weak_skills.append(skill.skill_id)
                    elif skill.metrics.success_rate >= STRONG_SKILL_SUCCESS_RATE:
                        coverage.strong_skills.append(skill.skill_id)

            return coverage

    def get_agent_profile(self, agent_id: str) -> dict[str, Any]:
        """Get a performance profile for a specific agent across all skills.

        Args:
            agent_id: The agent to profile.

        Returns:
            Dict with skills, metrics, and overall performance.
        """
        with self._lock:
            skills: list[dict[str, Any]] = []
            total_metrics = SkillMetrics()
            for skill in self._skills.values():
                if agent_id not in skill.agent_ids:
                    continue
                agent_m = skill.agent_metrics.get(agent_id)
                skill_info: dict[str, Any] = {
                    "skill_id": skill.skill_id,
                    "name": skill.name,
                }
                if agent_m is not None:
                    skill_info.update({
                        "success_rate": agent_m.success_rate,
                        "average_confidence": agent_m.average_confidence,
                        "total_executions": agent_m.total_executions,
                        "maturity": agent_m.maturity.value,
                    })
                    total_metrics.total_executions += agent_m.total_executions
                    total_metrics.successful_executions += agent_m.successful_executions
                    total_metrics.failed_executions += agent_m.failed_executions
                    total_metrics.total_confidence += agent_m.total_confidence
                    total_metrics.total_duration_seconds += agent_m.total_duration_seconds
                else:
                    skill_info.update({
                        "success_rate": 0.0,
                        "average_confidence": 0.0,
                        "total_executions": 0,
                        "maturity": SkillMaturity.NASCENT.value,
                    })
                skills.append(skill_info)

            return {
                "agent_id": agent_id,
                "skills": skills,
                "overall_success_rate": total_metrics.success_rate,
                "overall_average_confidence": total_metrics.average_confidence,
                "total_executions": total_metrics.total_executions,
            }

    def summary(self) -> dict[str, Any]:
        """Return summary statistics for the skill map."""
        with self._lock:
            coverage = self.get_coverage()
            return {
                "total_skills": coverage.total_skills,
                "covered_skills": coverage.covered_skills,
                "coverage_ratio": coverage.coverage_ratio,
                "weak_skills": coverage.weak_skills,
                "strong_skills": coverage.strong_skills,
                "unassigned_skills": coverage.unassigned_skills,
                "maturity_distribution": coverage.maturity_distribution,
            }
