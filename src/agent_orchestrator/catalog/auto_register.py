"""Auto-registration — derive CapabilityRegistration from a profile config.

Pure function that maps ProfileConfig + SettingsConfig fields to a
CapabilityRegistration, enabling profiles to be automatically registered
as discoverable capabilities on engine startup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agent_orchestrator.catalog.models import (
    CapabilityRegistration,
    InvocationMode,
    MemoryUsagePolicy,
    SecurityClassification,
)
from agent_orchestrator.configuration.models import (
    FieldType,
    ProfileConfig,
    SettingsConfig,
)
from agent_orchestrator.contracts.models import LifecycleState

logger = logging.getLogger(__name__)

# Map FieldType enum values to JSON Schema type strings
_FIELD_TYPE_TO_JSON_SCHEMA: dict[FieldType, str] = {
    FieldType.TEXT: "string",
    FieldType.STRING: "string",
    FieldType.INTEGER: "integer",
    FieldType.FLOAT: "number",
    FieldType.BOOLEAN: "boolean",
    FieldType.ENUM: "string",
}


def _build_input_schema(profile: ProfileConfig) -> dict:
    """Build JSON Schema from work_item_types custom_fields.

    Args:
        profile: The profile configuration.

    Returns:
        A JSON Schema dict describing accepted input properties.
    """
    properties: dict = {}
    required: list[str] = []

    for wit in profile.work_item_types:
        for field_def in wit.custom_fields:
            prop: dict = {
                "type": _FIELD_TYPE_TO_JSON_SCHEMA.get(field_def.type, "string"),
            }
            if field_def.type == FieldType.ENUM and field_def.values:
                prop["enum"] = field_def.values
            if field_def.default is not None:
                prop["default"] = field_def.default
            properties[field_def.name] = prop
            if field_def.required:
                required.append(field_def.name)

    if not properties:
        return {}

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _build_output_schema(profile: ProfileConfig) -> dict:
    """Build JSON Schema from workflow phases' expected_output_fields.

    Args:
        profile: The profile configuration.

    Returns:
        A JSON Schema dict describing expected output properties.
    """
    properties: dict = {}
    for phase in profile.workflow.phases:
        for field_name in phase.expected_output_fields:
            if field_name not in properties:
                properties[field_name] = {"type": "string"}

    if not properties:
        return {}

    return {"type": "object", "properties": properties}


def _determine_invocation_modes(profile: ProfileConfig) -> list[InvocationMode]:
    """Determine supported invocation modes from the workflow structure.

    ASYNC and EVENT_DRIVEN are always supported. SYNC is added when there
    is exactly one non-terminal phase (meaning the workflow can complete
    in a single pass).

    Args:
        profile: The profile configuration.

    Returns:
        List of supported invocation modes.
    """
    modes = [InvocationMode.ASYNC, InvocationMode.EVENT_DRIVEN]
    non_terminal = [p for p in profile.workflow.phases if not p.is_terminal]
    if len(non_terminal) <= 1:
        modes.insert(0, InvocationMode.SYNC)
    return modes


def build_registration_from_profile(
    profile: ProfileConfig,
    settings: SettingsConfig,
) -> CapabilityRegistration:
    """Build a CapabilityRegistration from a loaded profile and settings.

    Args:
        profile: The profile configuration to register.
        settings: The workspace settings (for deployment_mode).

    Returns:
        A fully populated CapabilityRegistration.
    """
    manifest = profile.manifest
    now = datetime.now(timezone.utc)

    # Identity fields — prefer manifest when available
    if manifest and manifest.name:
        capability_id = f"{manifest.name}.v{manifest.version}"
        display_name = manifest.name
        description = manifest.description or profile.description
        owner = manifest.author
        version = manifest.version
        tags = list(manifest.produces.keys()) if manifest.produces else []
    else:
        capability_id = f"{profile.name}.v1"
        display_name = profile.name
        description = profile.description
        owner = ""
        version = "1.0.0"
        tags = []

    # Required connectors from manifest
    required_connectors: list[str] = []
    if manifest and manifest.requires:
        required_connectors = manifest.requires.get("connectors", [])

    # Review threshold from governance config
    review_threshold = profile.governance.delegated_authority.review_threshold

    return CapabilityRegistration(
        capability_id=capability_id,
        display_name=display_name,
        description=description,
        owner=owner,
        version=version,
        tags=tags,
        input_schema=_build_input_schema(profile),
        output_schema=_build_output_schema(profile),
        profile_name=profile.name,
        deployment_mode=settings.deployment_mode,
        required_connectors=required_connectors,
        security_classification=SecurityClassification.INTERNAL,
        review_required_below=review_threshold,
        memory_usage_policy=MemoryUsagePolicy.NONE,
        invocation_modes=_determine_invocation_modes(profile),
        status=LifecycleState.ACTIVE,
        registered_at=now,
        updated_at=now,
    )
