"""Extract confidence scores and structured fields from agent LLM output dicts."""

from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONFIDENCE = 0.5
_CONFIDENCE_KEYS = ("confidence", "score", "quality_score")
_SCORE_KEYS = frozenset({
    "confidence", "accuracy", "completeness", "quality_score",
    "risk_score", "relevance", "coherence",
})
_SCORE_SUFFIX_PATTERN = re.compile(r"_score$|_confidence$")


def extract_confidence(output: dict[str, Any]) -> float:
    """Extract a confidence score from an agent output dict.

    Looks for keys in priority order: ``confidence``, ``score``,
    ``quality_score``.  Falls back to 0.5 when none are present.
    The result is clamped to [0.0, 1.0].

    Args:
        output: Raw agent output dictionary.

    Returns:
        Confidence value between 0.0 and 1.0.
    """
    raw: Any = None
    for key in _CONFIDENCE_KEYS:
        if key in output:
            raw = output[key]
            break

    if raw is None:
        logger.debug("No confidence key found in output; using default %s", _DEFAULT_CONFIDENCE)
        return _DEFAULT_CONFIDENCE

    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Non-numeric confidence value %r; using default %s", raw, _DEFAULT_CONFIDENCE)
        return _DEFAULT_CONFIDENCE

    clamped = max(0.0, min(1.0, value))
    if clamped != value:
        logger.debug("Clamped confidence %s -> %s", value, clamped)
    return clamped


def extract_structured_fields(
    output: dict[str, Any],
    required_fields: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Extract required fields from an agent output dict.

    Args:
        output: Raw agent output dictionary.
        required_fields: List of field names to extract.

    Returns:
        A tuple of (extracted_fields_dict, missing_field_names_list).
    """
    extracted: dict[str, Any] = {}
    missing: list[str] = []

    for field_name in required_fields:
        if field_name in output:
            extracted[field_name] = output[field_name]
        else:
            missing.append(field_name)

    if missing:
        logger.debug("Missing required fields: %s", missing)

    return extracted, missing


def aggregate_confidence(scores: list[float]) -> float:
    """Compute the mean confidence, filtering out default (0.5) values.

    If all values are exactly 0.5 or the list is empty, returns 0.5.

    Args:
        scores: List of confidence scores.

    Returns:
        Aggregated confidence value.
    """
    if not scores:
        return _DEFAULT_CONFIDENCE

    filtered = [s for s in scores if s != _DEFAULT_CONFIDENCE]
    if not filtered:
        return _DEFAULT_CONFIDENCE

    mean = sum(filtered) / len(filtered)
    logger.debug("Aggregated confidence from %d scores (of %d total): %s", len(filtered), len(scores), mean)
    return mean


def extract_scores(output: dict[str, Any]) -> dict[str, float]:
    """Extract all numeric score dimensions from an agent output dict.

    Looks for known score keys (confidence, accuracy, completeness, etc.)
    and any key ending in ``_score`` or ``_confidence``. Values are clamped
    to [0.0, 1.0].

    Args:
        output: Raw agent output dictionary.

    Returns:
        Dictionary of {dimension: clamped_value}.
    """
    scores: dict[str, float] = {}
    for key, value in output.items():
        if key in _SCORE_KEYS or _SCORE_SUFFIX_PATTERN.search(key):
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            scores[key] = max(0.0, min(1.0, numeric))
    return scores


def aggregate_scores(score_sets: list[dict[str, float]]) -> dict[str, float]:
    """Compute per-dimension mean scores across multiple agents.

    Args:
        score_sets: List of score dicts from ``extract_scores()``.

    Returns:
        Dictionary of {dimension: mean_value}.
    """
    if not score_sets:
        return {}

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for scores in score_sets:
        for dim, val in scores.items():
            totals[dim] = totals.get(dim, 0.0) + val
            counts[dim] = counts.get(dim, 0) + 1

    return {dim: totals[dim] / counts[dim] for dim in totals}
