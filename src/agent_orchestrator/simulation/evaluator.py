"""LLM-as-Judge Evaluator — score agent outputs using an LLM judge.

Provides configurable rubric-based evaluation of agent outputs.
The LLM acts as an expert judge, scoring each dimension from 0.0 to 1.0
with reasoning.

Thread-safe: Stateless evaluation functions.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "You are an expert evaluator. Score the following agent output on each "
    "dimension from 0.0 to 1.0. Return a JSON object where each key is the "
    "dimension name and the value is an object with 'score' (float) and "
    "'reasoning' (string). Return ONLY valid JSON, no markdown fences."
)

_FALLBACK_SCORE = 0.5


@dataclass(frozen=True)
class EvalDimension:
    """A single evaluation dimension with a weight."""

    name: str
    description: str
    weight: float = 1.0


@dataclass(frozen=True)
class EvalRubric:
    """A rubric defining how to evaluate agent output."""

    rubric_id: str
    name: str
    description: str = ""
    dimensions: tuple[EvalDimension, ...] = ()
    system_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "rubric_id": self.rubric_id,
            "name": self.name,
            "description": self.description,
            "dimensions": [
                {"name": d.name, "description": d.description, "weight": d.weight}
                for d in self.dimensions
            ],
            "system_prompt": self.system_prompt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalRubric:
        """Deserialize from a dict."""
        dims = tuple(
            EvalDimension(
                name=d["name"],
                description=d.get("description", ""),
                weight=d.get("weight", 1.0),
            )
            for d in data.get("dimensions", [])
        )
        return cls(
            rubric_id=data["rubric_id"],
            name=data["name"],
            description=data.get("description", ""),
            dimensions=dims,
            system_prompt=data.get("system_prompt", ""),
        )


@dataclass
class EvalScore:
    """Score for a single evaluation dimension."""

    dimension: str
    score: float
    reasoning: str = ""


@dataclass
class EvalResult:
    """Complete evaluation result for an agent output."""

    rubric_id: str
    work_id: str
    agent_id: str
    phase_id: str
    scores: list[EvalScore] = field(default_factory=list)
    aggregate_score: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "rubric_id": self.rubric_id,
            "work_id": self.work_id,
            "agent_id": self.agent_id,
            "phase_id": self.phase_id,
            "scores": [
                {"dimension": s.dimension, "score": s.score, "reasoning": s.reasoning}
                for s in self.scores
            ],
            "aggregate_score": self.aggregate_score,
            "timestamp": self.timestamp,
            "raw_response": self.raw_response,
        }


class LLMJudgeEvaluator:
    """Evaluate agent outputs using an LLM as a judge.

    The evaluator sends the agent output and rubric dimensions to an LLM,
    then parses the response to extract per-dimension scores. Falls back
    gracefully if the LLM output is not parseable.

    Usage:
        evaluator = LLMJudgeEvaluator(llm_call_fn=my_llm_fn)
        result = await evaluator.evaluate(rubric, agent_output, context)
    """

    def __init__(self, llm_call_fn: Callable[..., Any]) -> None:
        self._llm_call_fn = llm_call_fn

    async def evaluate(
        self,
        rubric: EvalRubric,
        agent_output: dict[str, Any],
        work_item_context: dict[str, Any],
        agent_id: str = "",
        phase_id: str = "",
        work_id: str = "",
    ) -> EvalResult:
        """Evaluate an agent output against a rubric.

        Args:
            rubric: The evaluation rubric with dimensions.
            agent_output: The agent's output to evaluate.
            work_item_context: Context about the work item.
            agent_id: Identifier of the agent that produced the output.
            phase_id: Identifier of the workflow phase.
            work_id: Identifier of the work item.

        Returns:
            EvalResult with per-dimension scores and aggregate.
        """
        system_prompt = rubric.system_prompt or _DEFAULT_SYSTEM_PROMPT

        dimensions_desc = "\n".join(
            f"- {d.name}: {d.description} (weight: {d.weight})"
            for d in rubric.dimensions
        )

        user_prompt = (
            f"## Evaluation Rubric: {rubric.name}\n\n"
            f"Dimensions to evaluate:\n{dimensions_desc}\n\n"
            f"## Agent Output:\n{json.dumps(agent_output, indent=2, default=str)}\n\n"
            f"## Work Item Context:\n{json.dumps(work_item_context, indent=2, default=str)}\n\n"
            f"Score each dimension from 0.0 to 1.0 with reasoning."
        )

        raw_response = ""
        try:
            llm_result = await self._llm_call_fn(
                system_prompt, user_prompt,
            )

            if isinstance(llm_result, dict):
                raw_response = llm_result.get("response", json.dumps(llm_result, default=str))
            else:
                raw_response = str(llm_result)

            scores = self._parse_scores(raw_response, rubric.dimensions)
        except Exception as exc:
            logger.warning(
                "LLM judge evaluation failed: %s", exc, exc_info=True,
            )
            scores = self._fallback_scores(rubric.dimensions)

        aggregate = self._compute_aggregate(scores, rubric.dimensions)

        return EvalResult(
            rubric_id=rubric.rubric_id,
            work_id=work_id,
            agent_id=agent_id,
            phase_id=phase_id,
            scores=scores,
            aggregate_score=aggregate,
            raw_response=raw_response,
        )

    async def evaluate_batch(
        self,
        rubric: EvalRubric,
        results: list[tuple[dict[str, Any], dict[str, Any]]],
        agent_id: str = "",
        phase_id: str = "",
        work_id_prefix: str = "",
    ) -> list[EvalResult]:
        """Evaluate multiple agent outputs against the same rubric.

        Args:
            rubric: The evaluation rubric.
            results: List of (agent_output, work_item_context) tuples.
            agent_id: Agent identifier.
            phase_id: Phase identifier.
            work_id_prefix: Prefix for auto-generated work IDs.

        Returns:
            List of EvalResult, one per input.
        """
        eval_results: list[EvalResult] = []
        for idx, (agent_output, context) in enumerate(results):
            w_id = f"{work_id_prefix}{idx}" if work_id_prefix else str(idx)
            result = await self.evaluate(
                rubric=rubric,
                agent_output=agent_output,
                work_item_context=context,
                agent_id=agent_id,
                phase_id=phase_id,
                work_id=w_id,
            )
            eval_results.append(result)
        return eval_results

    def _parse_scores(
        self,
        raw_response: str,
        dimensions: tuple[EvalDimension, ...],
    ) -> list[EvalScore]:
        """Parse LLM response into per-dimension scores.

        Expects JSON where keys are dimension names, values are objects
        with 'score' and 'reasoning'. Falls back to default scores on
        parse failure.

        Args:
            raw_response: Raw LLM response text.
            dimensions: Expected dimensions.

        Returns:
            List of EvalScore.
        """
        try:
            # Try to extract JSON from response (handle markdown fences)
            text = raw_response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                # Remove first and last fence lines
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)

            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                logger.warning("LLM judge returned non-dict JSON; using fallback scores")
                return self._fallback_scores(dimensions)

            scores: list[EvalScore] = []
            for dim in dimensions:
                dim_data = parsed.get(dim.name, {})
                if isinstance(dim_data, dict):
                    score_val = float(dim_data.get("score", _FALLBACK_SCORE))
                    score_val = max(0.0, min(1.0, score_val))
                    reasoning = str(dim_data.get("reasoning", ""))
                elif isinstance(dim_data, (int, float)):
                    score_val = max(0.0, min(1.0, float(dim_data)))
                    reasoning = ""
                else:
                    score_val = _FALLBACK_SCORE
                    reasoning = "Could not parse dimension score"

                scores.append(EvalScore(
                    dimension=dim.name,
                    score=score_val,
                    reasoning=reasoning,
                ))
            return scores

        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning(
                "Failed to parse LLM judge response: %s", exc,
            )
            return self._fallback_scores(dimensions)

    @staticmethod
    def _fallback_scores(
        dimensions: tuple[EvalDimension, ...],
    ) -> list[EvalScore]:
        """Generate fallback scores when LLM output is unparseable.

        Args:
            dimensions: The rubric dimensions.

        Returns:
            List of EvalScore with default 0.5 scores.
        """
        return [
            EvalScore(
                dimension=d.name,
                score=_FALLBACK_SCORE,
                reasoning="Fallback score — LLM response could not be parsed",
            )
            for d in dimensions
        ]

    @staticmethod
    def _compute_aggregate(
        scores: list[EvalScore],
        dimensions: tuple[EvalDimension, ...],
    ) -> float:
        """Compute weighted aggregate score.

        Args:
            scores: Per-dimension scores.
            dimensions: Dimension definitions with weights.

        Returns:
            Weighted average score.
        """
        if not scores:
            return 0.0

        weight_map = {d.name: d.weight for d in dimensions}
        total_weight = 0.0
        weighted_sum = 0.0

        for s in scores:
            w = weight_map.get(s.dimension, 1.0)
            weighted_sum += s.score * w
            total_weight += w

        if total_weight == 0.0:
            return 0.0
        return round(weighted_sum / total_weight, 4)
