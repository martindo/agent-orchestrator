"""Template import/export manager.

Handles reading shipped profile templates from disk into Studio IR
and writing IR back to profile directories.  This is the round-trip
test that validates the entire IR ↔ YAML pipeline.

Import path:  profile directory → YAML → dicts → runtime ProfileConfig → TeamSpec
Export path:  TeamSpec → dicts → YAML files → profile directory
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from studio.conversion.converter import profile_to_ir
from studio.exceptions import TemplateExportError, TemplateImportError
from studio.generation.generator import write_profile_to_directory
from studio.ir.models import (
    AgentSpec,
    ArtifactTypeSpec,
    AppManifestSpec,
    ConditionSpec,
    DelegatedAuthoritySpec,
    FieldType,
    GovernanceSpec,
    LLMSpec,
    OnFailureAction,
    PhaseSpec,
    PolicySpec,
    QualityGateSpec,
    RetryPolicySpec,
    StatusSpec,
    TeamSpec,
    WorkflowSpec,
    WorkItemFieldSpec,
    WorkItemTypeSpec,
)

logger = logging.getLogger(__name__)

# Expected YAML filenames — matches runtime loader constants
_AGENTS_FILE = "agents.yaml"
_WORKFLOW_FILE = "workflow.yaml"
_GOVERNANCE_FILE = "governance.yaml"
_WORKITEMS_FILE = "workitems.yaml"
_APP_FILE = "app.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file.

    Raises:
        TemplateImportError: If the file cannot be read or parsed.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        result = yaml.safe_load(text)
        return result if isinstance(result, dict) else {}
    except (yaml.YAMLError, OSError) as exc:
        raise TemplateImportError(f"Failed to read {path}: {exc}") from exc


def _parse_llm(data: dict[str, Any]) -> LLMSpec:
    """Parse an LLM config dict into LLMSpec."""
    return LLMSpec(
        provider=data.get("provider", "openai"),
        model=data.get("model", "gpt-4o"),
        temperature=float(data.get("temperature", 0.3)),
        max_tokens=int(data.get("max_tokens", 4000)),
        endpoint=data.get("endpoint"),
    )


def _parse_retry(data: dict[str, Any] | None) -> RetryPolicySpec:
    """Parse a retry policy dict into RetryPolicySpec."""
    if data is None:
        return RetryPolicySpec()
    return RetryPolicySpec(
        max_retries=int(data.get("max_retries", 3)),
        delay_seconds=float(data.get("delay_seconds", 1.0)),
        backoff_multiplier=float(data.get("backoff_multiplier", 2.0)),
    )


def _parse_condition(data: dict[str, Any] | str) -> ConditionSpec:
    """Parse a condition — can be a dict or a bare expression string."""
    if isinstance(data, str):
        return ConditionSpec(expression=data)
    return ConditionSpec(
        expression=data.get("expression", ""),
        description=data.get("description", ""),
    )


def _parse_quality_gate(data: dict[str, Any]) -> QualityGateSpec:
    """Parse a quality gate dict."""
    raw_action = data.get("on_failure", "block")
    try:
        action = OnFailureAction(raw_action)
    except ValueError:
        action = OnFailureAction.BLOCK
    return QualityGateSpec(
        name=data.get("name", ""),
        description=data.get("description", ""),
        conditions=[_parse_condition(c) for c in data.get("conditions", [])],
        on_failure=action,
    )


def _parse_agent(data: dict[str, Any]) -> AgentSpec:
    """Parse an agent definition dict."""
    return AgentSpec(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description", ""),
        system_prompt=data.get("system_prompt", ""),
        skills=data.get("skills", []),
        phases=data.get("phases", []),
        llm=_parse_llm(data.get("llm", {})),
        concurrency=int(data.get("concurrency", 1)),
        retry_policy=_parse_retry(data.get("retry_policy")),
        enabled=data.get("enabled", True),
    )


def _parse_status(data: dict[str, Any]) -> StatusSpec:
    """Parse a status config dict."""
    return StatusSpec(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description", ""),
        is_initial=data.get("is_initial", False),
        is_terminal=data.get("is_terminal", False),
        transitions_to=data.get("transitions_to", []),
    )


def _parse_phase(data: dict[str, Any]) -> PhaseSpec:
    """Parse a workflow phase dict."""
    return PhaseSpec(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description", ""),
        order=int(data.get("order", 0)),
        agents=data.get("agents", []),
        parallel=data.get("parallel", False),
        entry_conditions=[
            _parse_condition(c) for c in data.get("entry_conditions", [])
        ],
        exit_conditions=[
            _parse_condition(c) for c in data.get("exit_conditions", [])
        ],
        quality_gates=[
            _parse_quality_gate(g) for g in data.get("quality_gates", [])
        ],
        critic_agent=data.get("critic_agent"),
        critic_rubric=data.get("critic_rubric", ""),
        max_phase_retries=int(data.get("max_phase_retries", 1)),
        retry_backoff_seconds=float(data.get("retry_backoff_seconds", 1.0)),
        on_success=data.get("on_success", ""),
        on_failure=data.get("on_failure", ""),
        skippable=data.get("skippable", False),
        skip=data.get("skip", False),
        is_terminal=data.get("is_terminal", False),
        requires_human=data.get("requires_human", False),
    )


def _parse_field(data: dict[str, Any]) -> WorkItemFieldSpec:
    """Parse a work-item field definition dict.

    Handles legacy ``options`` → ``values`` rename for enum fields.
    """
    raw_type = data.get("type", "string")
    try:
        field_type = FieldType(raw_type)
    except ValueError:
        field_type = FieldType.STRING
    # Legacy: options → values
    values = data.get("values") or data.get("options")
    return WorkItemFieldSpec(
        name=data["name"],
        type=field_type,
        required=data.get("required", False),
        default=data.get("default"),
        values=values,
    )


def _parse_artifact_type(data: dict[str, Any]) -> ArtifactTypeSpec:
    """Parse an artifact type dict.

    Handles legacy ``formats`` → ``file_extensions`` rename.
    """
    return ArtifactTypeSpec(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description", ""),
        file_extensions=data.get("file_extensions") or data.get("formats", []),
    )


def _parse_work_item_type(data: dict[str, Any]) -> WorkItemTypeSpec:
    """Parse a work-item type dict.

    Handles legacy ``fields`` → ``custom_fields`` rename.
    """
    return WorkItemTypeSpec(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description", ""),
        custom_fields=[
            _parse_field(f)
            for f in data.get("custom_fields") or data.get("fields", [])
        ],
        artifact_types=[_parse_artifact_type(a) for a in data.get("artifact_types", [])],
    )


def _parse_policy(data: dict[str, Any]) -> PolicySpec:
    """Parse a governance policy dict.

    Handles the legacy format where policies used ``rule.expression``
    instead of ``conditions``.
    """
    # Legacy: rule.expression → conditions list
    conditions = data.get("conditions", [])
    if not conditions and "rule" in data:
        rule = data["rule"]
        if isinstance(rule, dict) and "expression" in rule:
            conditions = [rule["expression"]]

    return PolicySpec(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description", ""),
        scope=data.get("scope", "global"),
        action=data.get("action", "allow"),
        conditions=conditions,
        priority=int(data.get("priority", 0)),
        enabled=data.get("enabled", True),
        tags=data.get("tags", []),
    )


def _parse_work_item_types(data: dict[str, Any]) -> list[WorkItemTypeSpec]:
    """Parse work item types from YAML data.

    Supports two formats:
    1. Current: ``work_item_types: [{id: ..., custom_fields: [...]}]``
    2. Legacy flat: ``work_item_type: <id>`` + ``fields: [...]``
    """
    # Current format
    if "work_item_types" in data:
        return [_parse_work_item_type(w) for w in data["work_item_types"]]

    # Legacy flat format — single type
    if "work_item_type" in data:
        type_id = data["work_item_type"]
        return [_parse_work_item_type({
            "id": type_id,
            "name": type_id.replace("-", " ").title(),
            "fields": data.get("fields", []),
            "artifact_types": data.get("artifact_types", []),
        })]

    return []


def _parse_manifest(data: dict[str, Any]) -> AppManifestSpec:
    """Parse an app manifest dict."""
    return AppManifestSpec(
        name=data.get("name", ""),
        version=data.get("version", "0.0.0"),
        description=data.get("description", ""),
        platform_version=data.get("platform_version", ""),
        requires=data.get("requires", {}),
        produces=data.get("produces", {}),
        hooks=data.get("hooks", {}),
        author=data.get("author", ""),
    )


def import_template(profile_dir: Path) -> TeamSpec:
    """Import a profile template from a directory into a TeamSpec.

    Reads each YAML file and parses it directly into IR models.
    This is the pure-YAML import path that doesn't require the
    runtime to be installed.

    Args:
        profile_dir: Path to the profile directory containing YAML files.

    Returns:
        A fully populated TeamSpec.

    Raises:
        TemplateImportError: If the directory or required files are missing.
    """
    if not profile_dir.is_dir():
        raise TemplateImportError(f"Profile directory not found: {profile_dir}")

    # Agents
    agents_data = _read_yaml(profile_dir / _AGENTS_FILE)
    agents = [_parse_agent(a) for a in agents_data.get("agents", [])]

    # Workflow
    wf_data = _read_yaml(profile_dir / _WORKFLOW_FILE)
    statuses = [_parse_status(s) for s in wf_data.get("statuses", [])]
    phases = [_parse_phase(p) for p in wf_data.get("phases", [])]
    workflow = WorkflowSpec(
        name=wf_data.get("name", profile_dir.name),
        description=wf_data.get("description", ""),
        statuses=statuses,
        phases=phases,
    )

    # Governance
    gov_data = _read_yaml(profile_dir / _GOVERNANCE_FILE)
    da_data = gov_data.get("delegated_authority", {})
    delegated_authority = DelegatedAuthoritySpec(
        auto_approve_threshold=float(da_data.get("auto_approve_threshold", 0.8)),
        review_threshold=float(da_data.get("review_threshold", 0.5)),
        abort_threshold=float(da_data.get("abort_threshold", 0.2)),
        work_type_overrides=da_data.get("work_type_overrides", {}),
    )
    policies = [
        _parse_policy(p)
        for p in gov_data.get("policies", [])
    ]
    governance = GovernanceSpec(
        delegated_authority=delegated_authority,
        policies=policies,
    )

    # Work items (supports both list and legacy flat format)
    wi_data = _read_yaml(profile_dir / _WORKITEMS_FILE)
    work_item_types = _parse_work_item_types(wi_data)

    # App manifest (optional)
    app_data = _read_yaml(profile_dir / _APP_FILE)
    manifest = _parse_manifest(app_data) if app_data else None

    team_name = wf_data.get("name", profile_dir.name)
    team = TeamSpec(
        name=team_name,
        description=wf_data.get("description", ""),
        agents=agents,
        workflow=workflow,
        governance=governance,
        work_item_types=work_item_types,
        manifest=manifest,
    )

    logger.info(
        "Imported template '%s': %d agents, %d phases, %d policies, %d work item types",
        team.name,
        len(agents),
        len(phases),
        len(policies),
        len(work_item_types),
    )
    return team


def import_template_via_runtime(profile_dir: Path) -> TeamSpec:
    """Import using the runtime's loader → ProfileConfig → IR conversion.

    This path goes through the runtime's validation and normalization,
    ensuring maximum fidelity.  Falls back to direct YAML import if
    the runtime is not installed.

    Args:
        profile_dir: Path to the profile directory.

    Returns:
        A TeamSpec converted from a runtime ProfileConfig.

    Raises:
        TemplateImportError: If import fails.
    """
    try:
        from agent_orchestrator.configuration.loader import load_profile
        profile = load_profile(profile_dir)
        return profile_to_ir(profile)
    except ImportError:
        logger.warning(
            "Runtime not available, falling back to direct YAML import"
        )
        return import_template(profile_dir)
    except Exception as exc:
        raise TemplateImportError(
            f"Runtime import failed for {profile_dir}: {exc}"
        ) from exc


def export_template(team: TeamSpec, output_dir: Path) -> list[Path]:
    """Export a TeamSpec to a profile directory.

    Args:
        team: The team specification to export.
        output_dir: Target directory to write YAML files into.

    Returns:
        List of paths to written files.

    Raises:
        TemplateExportError: If export fails.
    """
    try:
        return write_profile_to_directory(team, output_dir)
    except Exception as exc:
        raise TemplateExportError(
            f"Failed to export template to {output_dir}: {exc}"
        ) from exc


def list_templates(profiles_dir: Path) -> list[dict[str, str]]:
    """List available profile templates in a directory.

    Args:
        profiles_dir: Directory containing profile subdirectories.

    Returns:
        List of dicts with 'name' and 'path' for each discovered template.
    """
    if not profiles_dir.is_dir():
        logger.warning("Profiles directory not found: %s", profiles_dir)
        return []

    templates: list[dict[str, str]] = []
    for child in sorted(profiles_dir.iterdir()):
        if child.is_dir() and (child / _AGENTS_FILE).exists():
            templates.append({
                "name": child.name,
                "path": str(child),
            })
            logger.debug("Found template: %s", child.name)

    logger.info("Found %d templates in %s", len(templates), profiles_dir)
    return templates
