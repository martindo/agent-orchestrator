"""WorkItemFactory — Type-validated WorkItem creation.

Validates work item data against WorkItemTypeConfig custom_fields,
ensuring field types, required fields, and enum constraints are satisfied.

Thread-safe: Stateless functions, no shared mutable state.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_orchestrator.configuration.models import (
    FieldDefinition,
    FieldType,
    WorkItemTypeConfig,
)
from agent_orchestrator.core.work_queue import DEFAULT_PRIORITY, WorkItem
from agent_orchestrator.exceptions import WorkItemValidationError

logger = logging.getLogger(__name__)

# Mapping from FieldType to acceptable Python types
_FIELD_TYPE_MAP: dict[FieldType, tuple[type, ...]] = {
    FieldType.TEXT: (str,),
    FieldType.STRING: (str,),
    FieldType.INTEGER: (int,),
    FieldType.FLOAT: (int, float),
    FieldType.BOOLEAN: (bool,),
    FieldType.ENUM: (str,),
}


def _validate_field(
    field_def: FieldDefinition,
    value: Any,
) -> str | None:
    """Validate a single field value against its definition.

    Returns an error string if invalid, None if valid.
    """
    expected_types = _FIELD_TYPE_MAP.get(field_def.type)
    if expected_types is None:
        return f"Unknown field type '{field_def.type.value}' for field '{field_def.name}'"

    # bool is a subclass of int in Python — reject bools for integer/float fields
    if field_def.type in (FieldType.INTEGER, FieldType.FLOAT) and isinstance(value, bool):
        return (
            f"Field '{field_def.name}' expected type '{field_def.type.value}', "
            f"got bool"
        )

    if not isinstance(value, expected_types):
        return (
            f"Field '{field_def.name}' expected type '{field_def.type.value}', "
            f"got {type(value).__name__}"
        )

    if field_def.type == FieldType.ENUM and field_def.values:
        if value not in field_def.values:
            return (
                f"Field '{field_def.name}' value '{value}' not in allowed values: "
                f"{field_def.values}"
            )

    return None


def validate_work_item_data(
    data: dict[str, Any],
    type_config: WorkItemTypeConfig,
) -> list[str]:
    """Validate work item data against its type config's custom_fields.

    Returns a list of validation error strings (empty means valid).
    """
    errors: list[str] = []
    field_map = {f.name: f for f in type_config.custom_fields}

    # Check required fields are present
    for field_def in type_config.custom_fields:
        if field_def.required and field_def.name not in data:
            if field_def.default is None:
                errors.append(f"Required field '{field_def.name}' is missing")

    # Validate each provided field that has a definition
    for key, value in data.items():
        field_def = field_map.get(key)
        if field_def is None:
            continue  # Extra fields are allowed (pass-through)
        error = _validate_field(field_def, value)
        if error is not None:
            errors.append(error)

    return errors


def create_work_item(
    id: str,
    type_config: WorkItemTypeConfig,
    title: str,
    data: dict[str, Any],
    *,
    priority: int = DEFAULT_PRIORITY,
    app_id: str = "default",
    strict: bool = False,
) -> WorkItem:
    """Create a WorkItem validated against its type config.

    Args:
        id: Unique work item identifier.
        type_config: The WorkItemTypeConfig defining expected fields.
        title: Human-readable title.
        data: Work item payload to validate.
        priority: Queue priority (lower = higher priority).
        app_id: Application identifier.
        strict: If True, raises WorkItemValidationError on invalid data.
            If False (default), logs warnings and proceeds.

    Returns:
        A new WorkItem instance.

    Raises:
        WorkItemValidationError: If strict=True and validation fails.
    """
    errors = validate_work_item_data(data, type_config)

    if errors:
        if strict:
            msg = f"Work item validation failed for type '{type_config.id}': {'; '.join(errors)}"
            raise WorkItemValidationError(msg)
        for error in errors:
            logger.warning("Work item '%s' validation warning: %s", id, error)

    # Apply defaults for missing optional fields
    enriched_data = dict(data)
    for field_def in type_config.custom_fields:
        if field_def.name not in enriched_data and field_def.default is not None:
            enriched_data[field_def.name] = field_def.default

    return WorkItem(
        id=id,
        type_id=type_config.id,
        title=title,
        data=enriched_data,
        priority=priority,
        app_id=app_id,
    )
