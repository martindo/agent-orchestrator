"""Structured condition expression builder and parser.

The runtime stores conditions as free-text strings like ``confidence >= 0.8``
or ``category == 'hate_speech'``.  Studio provides a structured builder UI
that composes these strings safely, plus a parser that decomposes existing
expressions back into structured parts for editing.

Supported operators (matching runtime's _evaluate_condition):
    >=, <=, !=, ==, >, <, in
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from studio.exceptions import ConditionParseError

logger = logging.getLogger(__name__)

SUPPORTED_OPERATORS = (">=", "<=", "!=", "==", ">", "<", "in")

# Regex to parse expressions like:
#   confidence >= 0.8
#   category == 'hate_speech'
#   severity != "critical"
#   risk_level in ['high', 'critical']
_EXPRESSION_PATTERN = re.compile(
    r"^\s*"
    r"(?P<field>[a-zA-Z_][a-zA-Z0-9_]*)"  # field name
    r"\s+"
    r"(?P<operator>>=|<=|!=|==|>|<|in)"    # operator
    r"\s+"
    r"(?P<value>.+?)"                       # value (rest of line)
    r"\s*$"
)


@dataclass(frozen=True)
class ConditionParts:
    """Decomposed condition expression.

    Attributes:
        field: Variable name (left operand).
        operator: Comparison operator.
        value: Right operand as a string (may include quotes).
    """

    field: str
    operator: str
    value: str


def build_condition(field: str, operator: str, value: str) -> str:
    """Build a condition expression string from structured parts.

    Args:
        field: Variable name (e.g. ``confidence``, ``category``).
        operator: One of the supported operators.
        value: Right-hand operand (e.g. ``0.8``, ``'hate_speech'``).

    Returns:
        A formatted expression string like ``confidence >= 0.8``.

    Raises:
        ConditionParseError: If the field or operator is invalid.
    """
    field = field.strip()
    operator = operator.strip()
    value = value.strip()

    if not field:
        raise ConditionParseError("Condition field name is required")

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", field):
        raise ConditionParseError(
            f"Invalid field name '{field}': must be a valid identifier"
        )

    if operator not in SUPPORTED_OPERATORS:
        raise ConditionParseError(
            f"Unsupported operator '{operator}'. Must be one of: {', '.join(SUPPORTED_OPERATORS)}"
        )

    if not value:
        raise ConditionParseError("Condition value is required")

    expression = f"{field} {operator} {value}"
    logger.debug("Built condition: %s", expression)
    return expression


def parse_condition(expression: str) -> ConditionParts:
    """Parse a condition expression string into structured parts.

    Args:
        expression: Expression like ``confidence >= 0.8`` or
                    ``category == 'hate_speech'``.

    Returns:
        ConditionParts with field, operator, and value extracted.

    Raises:
        ConditionParseError: If the expression doesn't match the expected format.
    """
    match = _EXPRESSION_PATTERN.match(expression)
    if not match:
        raise ConditionParseError(
            f"Cannot parse condition expression: '{expression}'. "
            f"Expected format: <field> <operator> <value>"
        )

    parts = ConditionParts(
        field=match.group("field"),
        operator=match.group("operator"),
        value=match.group("value").strip(),
    )
    logger.debug("Parsed condition: %s → %s", expression, parts)
    return parts


def validate_condition(expression: str) -> list[str]:
    """Validate a condition expression and return any errors.

    Args:
        expression: The condition expression to validate.

    Returns:
        List of error messages. Empty list means the expression is valid.
    """
    errors: list[str] = []

    if not expression or not expression.strip():
        errors.append("Expression is empty")
        return errors

    try:
        parts = parse_condition(expression)
    except ConditionParseError as exc:
        errors.append(str(exc))
        return errors

    if parts.operator not in SUPPORTED_OPERATORS:
        errors.append(f"Unsupported operator: {parts.operator}")

    # Check value looks reasonable
    value = parts.value
    if parts.operator == "in":
        # Value should look like a list: ['a', 'b'] or [1, 2]
        if not (value.startswith("[") and value.endswith("]")):
            errors.append(
                f"'in' operator expects a list value like ['a', 'b'], got: {value}"
            )
    else:
        # Value should be a number, quoted string, or identifier
        is_number = _is_numeric(value)
        is_quoted = (
            (value.startswith("'") and value.endswith("'"))
            or (value.startswith('"') and value.endswith('"'))
        )
        is_identifier = bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", value))
        if not (is_number or is_quoted or is_identifier):
            errors.append(
                f"Value '{value}' is not a valid number, quoted string, or identifier"
            )

    return errors


def _is_numeric(value: str) -> bool:
    """Check if a string represents a number (int or float)."""
    try:
        float(value)
        return True
    except ValueError:
        return False
