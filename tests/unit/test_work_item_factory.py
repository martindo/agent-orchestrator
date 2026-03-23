"""Tests for work item type validation and factory creation."""

from __future__ import annotations

import pytest

from agent_orchestrator.configuration.models import (
    FieldDefinition,
    FieldType,
    WorkItemTypeConfig,
)
from agent_orchestrator.core.work_item_factory import (
    create_work_item,
    validate_work_item_data,
)
from agent_orchestrator.exceptions import WorkItemValidationError


def _make_type_config(
    custom_fields: list[FieldDefinition] | None = None,
) -> WorkItemTypeConfig:
    return WorkItemTypeConfig(
        id="test_type",
        name="Test Type",
        custom_fields=custom_fields or [],
    )


# ---- validate_work_item_data ----


def test_validate_empty_fields_no_errors() -> None:
    config = _make_type_config()
    errors = validate_work_item_data({"anything": "goes"}, config)
    assert errors == []


def test_validate_string_field_valid() -> None:
    config = _make_type_config([
        FieldDefinition(name="title", type=FieldType.STRING, required=True),
    ])
    errors = validate_work_item_data({"title": "hello"}, config)
    assert errors == []


def test_validate_string_field_wrong_type() -> None:
    config = _make_type_config([
        FieldDefinition(name="title", type=FieldType.STRING, required=True),
    ])
    errors = validate_work_item_data({"title": 123}, config)
    assert len(errors) == 1
    assert "title" in errors[0]
    assert "string" in errors[0].lower()


def test_validate_text_field() -> None:
    config = _make_type_config([
        FieldDefinition(name="body", type=FieldType.TEXT),
    ])
    assert validate_work_item_data({"body": "long text"}, config) == []
    errors = validate_work_item_data({"body": 42}, config)
    assert len(errors) == 1


def test_validate_integer_field() -> None:
    config = _make_type_config([
        FieldDefinition(name="count", type=FieldType.INTEGER, required=True),
    ])
    assert validate_work_item_data({"count": 5}, config) == []
    errors = validate_work_item_data({"count": 5.5}, config)
    assert len(errors) == 1


def test_validate_integer_rejects_bool() -> None:
    config = _make_type_config([
        FieldDefinition(name="count", type=FieldType.INTEGER),
    ])
    errors = validate_work_item_data({"count": True}, config)
    assert len(errors) == 1
    assert "bool" in errors[0]


def test_validate_float_field() -> None:
    config = _make_type_config([
        FieldDefinition(name="score", type=FieldType.FLOAT, required=True),
    ])
    # Both int and float are valid for FLOAT type
    assert validate_work_item_data({"score": 3.14}, config) == []
    assert validate_work_item_data({"score": 3}, config) == []
    errors = validate_work_item_data({"score": "high"}, config)
    assert len(errors) == 1


def test_validate_float_rejects_bool() -> None:
    config = _make_type_config([
        FieldDefinition(name="score", type=FieldType.FLOAT),
    ])
    errors = validate_work_item_data({"score": False}, config)
    assert len(errors) == 1


def test_validate_boolean_field() -> None:
    config = _make_type_config([
        FieldDefinition(name="active", type=FieldType.BOOLEAN),
    ])
    assert validate_work_item_data({"active": True}, config) == []
    assert validate_work_item_data({"active": False}, config) == []
    errors = validate_work_item_data({"active": 1}, config)
    assert len(errors) == 1


def test_validate_enum_field_valid() -> None:
    config = _make_type_config([
        FieldDefinition(
            name="severity",
            type=FieldType.ENUM,
            values=["low", "medium", "high"],
        ),
    ])
    assert validate_work_item_data({"severity": "high"}, config) == []


def test_validate_enum_field_invalid_value() -> None:
    config = _make_type_config([
        FieldDefinition(
            name="severity",
            type=FieldType.ENUM,
            values=["low", "medium", "high"],
        ),
    ])
    errors = validate_work_item_data({"severity": "critical"}, config)
    assert len(errors) == 1
    assert "critical" in errors[0]
    assert "allowed values" in errors[0].lower()


def test_validate_enum_field_wrong_type() -> None:
    config = _make_type_config([
        FieldDefinition(
            name="severity",
            type=FieldType.ENUM,
            values=["low", "medium", "high"],
        ),
    ])
    errors = validate_work_item_data({"severity": 42}, config)
    assert len(errors) == 1


def test_validate_required_field_missing() -> None:
    config = _make_type_config([
        FieldDefinition(name="title", type=FieldType.STRING, required=True),
    ])
    errors = validate_work_item_data({}, config)
    assert len(errors) == 1
    assert "required" in errors[0].lower()


def test_validate_required_field_with_default_not_missing() -> None:
    config = _make_type_config([
        FieldDefinition(name="priority", type=FieldType.INTEGER, required=True, default=5),
    ])
    # Has default, so not flagged as missing even though required
    errors = validate_work_item_data({}, config)
    assert errors == []


def test_validate_extra_fields_allowed() -> None:
    config = _make_type_config([
        FieldDefinition(name="title", type=FieldType.STRING),
    ])
    errors = validate_work_item_data({"title": "ok", "extra": "value"}, config)
    assert errors == []


def test_validate_multiple_errors() -> None:
    config = _make_type_config([
        FieldDefinition(name="title", type=FieldType.STRING, required=True),
        FieldDefinition(name="count", type=FieldType.INTEGER, required=True),
    ])
    errors = validate_work_item_data({"title": 123, "count": "abc"}, config)
    assert len(errors) == 2


# ---- create_work_item ----


def test_create_work_item_valid() -> None:
    config = _make_type_config([
        FieldDefinition(name="title", type=FieldType.STRING, required=True),
    ])
    item = create_work_item(
        id="w1", type_config=config, title="Test", data={"title": "hello"},
    )
    assert item.id == "w1"
    assert item.type_id == "test_type"
    assert item.data["title"] == "hello"


def test_create_work_item_applies_defaults() -> None:
    config = _make_type_config([
        FieldDefinition(name="priority", type=FieldType.INTEGER, default=5),
    ])
    item = create_work_item(
        id="w1", type_config=config, title="Test", data={},
    )
    assert item.data["priority"] == 5


def test_create_work_item_strict_raises() -> None:
    config = _make_type_config([
        FieldDefinition(name="count", type=FieldType.INTEGER, required=True),
    ])
    with pytest.raises(WorkItemValidationError) as exc_info:
        create_work_item(
            id="w1", type_config=config, title="Test", data={}, strict=True,
        )
    assert "count" in str(exc_info.value)


def test_create_work_item_lenient_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    config = _make_type_config([
        FieldDefinition(name="count", type=FieldType.INTEGER, required=True),
    ])
    import logging
    with caplog.at_level(logging.WARNING):
        item = create_work_item(
            id="w1", type_config=config, title="Test", data={}, strict=False,
        )
    assert item is not None
    assert any("validation warning" in r.message.lower() for r in caplog.records)
