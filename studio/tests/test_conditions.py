"""Tests for condition expression builder and parser."""

import pytest

from studio.conditions.builder import (
    build_condition,
    parse_condition,
    validate_condition,
    ConditionParts,
    SUPPORTED_OPERATORS,
)
from studio.exceptions import ConditionParseError


class TestBuildCondition:
    def test_basic(self) -> None:
        expr = build_condition("confidence", ">=", "0.8")
        assert expr == "confidence >= 0.8"

    def test_string_value(self) -> None:
        expr = build_condition("category", "==", "'hate_speech'")
        assert expr == "category == 'hate_speech'"

    def test_in_operator(self) -> None:
        expr = build_condition("status", "in", "['open', 'pending']")
        assert expr == "status in ['open', 'pending']"

    def test_empty_field_raises(self) -> None:
        with pytest.raises(ConditionParseError):
            build_condition("", ">=", "0.5")

    def test_invalid_operator_raises(self) -> None:
        with pytest.raises(ConditionParseError):
            build_condition("field", "~=", "0.5")

    def test_empty_value_raises(self) -> None:
        with pytest.raises(ConditionParseError):
            build_condition("field", ">=", "")

    def test_invalid_field_name(self) -> None:
        with pytest.raises(ConditionParseError):
            build_condition("123bad", ">=", "0.5")


class TestParseCondition:
    def test_numeric(self) -> None:
        parts = parse_condition("confidence >= 0.8")
        assert parts == ConditionParts(field="confidence", operator=">=", value="0.8")

    def test_string_value(self) -> None:
        parts = parse_condition("category == 'hate_speech'")
        assert parts.field == "category"
        assert parts.operator == "=="
        assert parts.value == "'hate_speech'"

    def test_in_operator(self) -> None:
        parts = parse_condition("status in ['open', 'closed']")
        assert parts.operator == "in"

    def test_all_operators(self) -> None:
        for op in SUPPORTED_OPERATORS:
            if op == "in":
                expr = f"field {op} ['a']"
            else:
                expr = f"field {op} 0.5"
            parts = parse_condition(expr)
            assert parts.operator == op

    def test_invalid_expression(self) -> None:
        with pytest.raises(ConditionParseError):
            parse_condition("not a valid expression!!")


class TestValidateCondition:
    def test_valid_numeric(self) -> None:
        errors = validate_condition("confidence >= 0.8")
        assert len(errors) == 0

    def test_valid_string(self) -> None:
        errors = validate_condition("category == 'safe'")
        assert len(errors) == 0

    def test_empty_expression(self) -> None:
        errors = validate_condition("")
        assert len(errors) > 0

    def test_invalid_value(self) -> None:
        errors = validate_condition("field >= not valid value")
        assert len(errors) > 0

    def test_in_without_list(self) -> None:
        errors = validate_condition("field in not_a_list")
        assert len(errors) > 0

    def test_in_with_list(self) -> None:
        errors = validate_condition("field in ['a', 'b']")
        assert len(errors) == 0
