"""Extract JSON Schemas from runtime Pydantic models via model_json_schema().

The extracted schemas serve two purposes:
1. Frontend form generation — drive dynamic forms from JSON Schema.
2. IR alignment checking — verify Studio IR covers all runtime fields.

Schemas are grouped by the file/component they belong to, matching the
runtime loader's file-per-concern structure (agents.yaml, workflow.yaml, etc.).
"""

from __future__ import annotations

import logging
from typing import Any

from studio.exceptions import SchemaExtractionError

logger = logging.getLogger(__name__)

# Component → (model class path, top-level YAML key)
_COMPONENT_MAP: dict[str, list[tuple[str, str]]] = {
    "agents": [
        ("agent_orchestrator.configuration.models.AgentDefinition", "agents"),
        ("agent_orchestrator.configuration.models.LLMConfig", "llm"),
        ("agent_orchestrator.configuration.models.RetryPolicy", "retry_policy"),
    ],
    "workflow": [
        ("agent_orchestrator.configuration.models.WorkflowConfig", "workflow"),
        ("agent_orchestrator.configuration.models.WorkflowPhaseConfig", "phase"),
        ("agent_orchestrator.configuration.models.StatusConfig", "status"),
        ("agent_orchestrator.configuration.models.QualityGateConfig", "quality_gate"),
        ("agent_orchestrator.configuration.models.ConditionConfig", "condition"),
    ],
    "governance": [
        ("agent_orchestrator.configuration.models.GovernanceConfig", "governance"),
        ("agent_orchestrator.configuration.models.DelegatedAuthorityConfig", "delegated_authority"),
        ("agent_orchestrator.configuration.models.PolicyConfig", "policy"),
    ],
    "workitems": [
        ("agent_orchestrator.configuration.models.WorkItemTypeConfig", "work_item_type"),
        ("agent_orchestrator.configuration.models.FieldDefinition", "field_definition"),
        ("agent_orchestrator.configuration.models.ArtifactTypeConfig", "artifact_type"),
    ],
    "app": [
        ("agent_orchestrator.configuration.models.AppManifest", "manifest"),
    ],
    "profile": [
        ("agent_orchestrator.configuration.models.ProfileConfig", "profile"),
    ],
}


def _import_model(dotted_path: str) -> type:
    """Dynamically import a Pydantic model class by dotted path.

    Raises:
        SchemaExtractionError: If the module or class cannot be imported.
    """
    module_path, _, class_name = dotted_path.rpartition(".")
    try:
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise SchemaExtractionError(
            f"Cannot import model '{dotted_path}': {exc}"
        ) from exc


def _extract_schema(model_cls: type) -> dict[str, Any]:
    """Call model_json_schema() on a Pydantic model class.

    Raises:
        SchemaExtractionError: If schema extraction fails.
    """
    try:
        return model_cls.model_json_schema()  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise SchemaExtractionError(
            f"{model_cls.__name__} does not support model_json_schema()"
        ) from exc


def extract_component_schema(component: str) -> dict[str, Any]:
    """Extract JSON schemas for all models in a component group.

    Args:
        component: One of 'agents', 'workflow', 'governance', 'workitems',
                   'app', or 'profile'.

    Returns:
        Dict keyed by short model name, each value is a JSON Schema dict.

    Raises:
        SchemaExtractionError: If the component is unknown or extraction fails.
    """
    if component not in _COMPONENT_MAP:
        valid = ", ".join(sorted(_COMPONENT_MAP.keys()))
        raise SchemaExtractionError(
            f"Unknown component '{component}'. Valid: {valid}"
        )

    schemas: dict[str, Any] = {}
    for dotted_path, short_name in _COMPONENT_MAP[component]:
        model_cls = _import_model(dotted_path)
        schemas[short_name] = _extract_schema(model_cls)
        logger.debug("Extracted schema for %s (%s)", short_name, dotted_path)

    return schemas


def extract_all_schemas() -> dict[str, dict[str, Any]]:
    """Extract JSON schemas for every component group.

    Returns:
        Nested dict: ``{component_name: {model_short_name: json_schema}}``.

    Raises:
        SchemaExtractionError: If any extraction fails.
    """
    result: dict[str, dict[str, Any]] = {}
    for component in _COMPONENT_MAP:
        result[component] = extract_component_schema(component)
        logger.info("Extracted %d schemas for component '%s'", len(result[component]), component)
    return result
