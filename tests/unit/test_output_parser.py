"""Tests for agent_orchestrator.core.output_parser."""

from __future__ import annotations

import pytest

from agent_orchestrator.core.output_parser import (
    aggregate_confidence,
    extract_confidence,
    extract_structured_fields,
)


# ---- extract_confidence ----


class TestExtractConfidence:
    def test_confidence_key(self) -> None:
        assert extract_confidence({"confidence": 0.9}) == 0.9

    def test_score_key(self) -> None:
        assert extract_confidence({"score": 0.7}) == 0.7

    def test_quality_score_key(self) -> None:
        assert extract_confidence({"quality_score": 0.8}) == 0.8

    def test_priority_order(self) -> None:
        """confidence takes precedence over score and quality_score."""
        output = {"confidence": 0.1, "score": 0.9, "quality_score": 0.8}
        assert extract_confidence(output) == 0.1

    def test_score_before_quality_score(self) -> None:
        output = {"score": 0.3, "quality_score": 0.9}
        assert extract_confidence(output) == 0.3

    def test_no_key_returns_default(self) -> None:
        assert extract_confidence({"other": 42}) == 0.5

    def test_empty_dict_returns_default(self) -> None:
        assert extract_confidence({}) == 0.5

    def test_clamp_above_one(self) -> None:
        assert extract_confidence({"confidence": 1.5}) == 1.0

    def test_clamp_below_zero(self) -> None:
        assert extract_confidence({"confidence": -0.3}) == 0.0

    def test_exactly_zero(self) -> None:
        assert extract_confidence({"confidence": 0.0}) == 0.0

    def test_exactly_one(self) -> None:
        assert extract_confidence({"confidence": 1.0}) == 1.0

    def test_non_numeric_string(self) -> None:
        assert extract_confidence({"confidence": "high"}) == 0.5

    def test_non_numeric_none_value(self) -> None:
        """None as value (key present but value is None)."""
        assert extract_confidence({"confidence": None}) == 0.5

    def test_numeric_string_coerced(self) -> None:
        """A numeric string like '0.75' should be converted."""
        assert extract_confidence({"confidence": "0.75"}) == 0.75

    def test_integer_value(self) -> None:
        assert extract_confidence({"confidence": 1}) == 1.0


# ---- extract_structured_fields ----


class TestExtractStructuredFields:
    def test_all_fields_present(self) -> None:
        output = {"a": 1, "b": 2, "c": 3}
        extracted, missing = extract_structured_fields(output, ["a", "b", "c"])
        assert extracted == {"a": 1, "b": 2, "c": 3}
        assert missing == []

    def test_some_fields_missing(self) -> None:
        output = {"a": 1}
        extracted, missing = extract_structured_fields(output, ["a", "b"])
        assert extracted == {"a": 1}
        assert missing == ["b"]

    def test_all_fields_missing(self) -> None:
        output = {"x": 1}
        extracted, missing = extract_structured_fields(output, ["a", "b"])
        assert extracted == {}
        assert missing == ["a", "b"]

    def test_empty_required_fields(self) -> None:
        output = {"a": 1}
        extracted, missing = extract_structured_fields(output, [])
        assert extracted == {}
        assert missing == []

    def test_empty_output(self) -> None:
        extracted, missing = extract_structured_fields({}, ["a"])
        assert extracted == {}
        assert missing == ["a"]

    def test_extra_keys_ignored(self) -> None:
        output = {"a": 1, "b": 2, "extra": 99}
        extracted, missing = extract_structured_fields(output, ["a", "b"])
        assert extracted == {"a": 1, "b": 2}
        assert "extra" not in extracted

    def test_none_value_counted_as_present(self) -> None:
        output = {"a": None}
        extracted, missing = extract_structured_fields(output, ["a"])
        assert extracted == {"a": None}
        assert missing == []


# ---- aggregate_confidence ----


class TestAggregateConfidence:
    def test_mixed_scores(self) -> None:
        result = aggregate_confidence([0.8, 0.6, 0.9])
        assert result == pytest.approx((0.8 + 0.6 + 0.9) / 3)

    def test_all_defaults(self) -> None:
        assert aggregate_confidence([0.5, 0.5, 0.5]) == 0.5

    def test_empty_list(self) -> None:
        assert aggregate_confidence([]) == 0.5

    def test_single_value(self) -> None:
        assert aggregate_confidence([0.9]) == 0.9

    def test_single_default_value(self) -> None:
        assert aggregate_confidence([0.5]) == 0.5

    def test_filters_out_defaults(self) -> None:
        """0.5 values are filtered; mean is taken from non-0.5 only."""
        result = aggregate_confidence([0.5, 0.8, 0.5])
        assert result == pytest.approx(0.8)

    def test_mixed_with_some_defaults(self) -> None:
        result = aggregate_confidence([0.5, 0.8, 0.6, 0.5])
        assert result == pytest.approx((0.8 + 0.6) / 2)

    def test_zero_scores(self) -> None:
        """0.0 is not filtered (only exactly 0.5 is)."""
        result = aggregate_confidence([0.0, 1.0])
        assert result == pytest.approx(0.5)
