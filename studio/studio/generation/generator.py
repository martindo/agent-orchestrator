"""Generate YAML files from Studio IR models.

The generator converts a TeamSpec into the exact file structure expected
by the runtime's ConfigurationManager loader:

    agents.yaml     — top-level key ``agents:``
    workflow.yaml   — top-level keys ``name:``, ``description:``, ``statuses:``, ``phases:``
    governance.yaml — top-level keys ``delegated_authority:``, ``policies:``
    workitems.yaml  — top-level key ``work_item_types:``
    app.yaml        — flat manifest fields (optional)

The generated YAML is always valid for the runtime — we convert IR → dict
using the same field names the loader expects, then dump with PyYAML.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from studio.conversion.converter import ir_to_profile_dict
from studio.exceptions import GenerationError
from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)

# Custom YAML representer for multiline strings
def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    """Use literal block style for multiline strings."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _get_dumper() -> type[yaml.Dumper]:
    """Return a YAML Dumper that handles multiline strings nicely."""
    dumper = yaml.Dumper
    dumper.add_representer(str, _str_representer)
    return dumper


def _dump_yaml(data: Any) -> str:
    """Dump a Python object to a YAML string with nice formatting."""
    return yaml.dump(
        data,
        Dumper=_get_dumper(),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )


def _build_agents_yaml(profile_dict: dict[str, Any]) -> str:
    """Build agents.yaml content from profile dict."""
    agents_data = {"agents": profile_dict.get("agents", [])}
    return _dump_yaml(agents_data)


def _build_workflow_yaml(profile_dict: dict[str, Any]) -> str:
    """Build workflow.yaml content from profile dict."""
    wf = profile_dict.get("workflow", {})
    workflow_data: dict[str, Any] = {
        "name": wf.get("name", "default"),
    }
    if wf.get("description"):
        workflow_data["description"] = wf["description"]
    if wf.get("statuses"):
        workflow_data["statuses"] = wf["statuses"]
    if wf.get("phases"):
        workflow_data["phases"] = wf["phases"]
    return _dump_yaml(workflow_data)


def _build_governance_yaml(profile_dict: dict[str, Any]) -> str:
    """Build governance.yaml content from profile dict."""
    gov = profile_dict.get("governance", {})
    return _dump_yaml(gov)


def _build_workitems_yaml(profile_dict: dict[str, Any]) -> str:
    """Build workitems.yaml content from profile dict."""
    items = profile_dict.get("work_item_types", [])
    return _dump_yaml({"work_item_types": items})


def _build_app_yaml(profile_dict: dict[str, Any]) -> str:
    """Build app.yaml content from profile dict (optional)."""
    manifest = profile_dict.get("manifest")
    if manifest is None:
        return ""
    return _dump_yaml(manifest)


def generate_component_yaml(team: TeamSpec, component: str) -> str:
    """Generate YAML for a single component.

    Args:
        team: The complete team specification.
        component: One of 'agents', 'workflow', 'governance', 'workitems', 'app'.

    Returns:
        YAML string content for the specified component.

    Raises:
        GenerationError: If the component is unknown or generation fails.
    """
    builders: dict[str, Any] = {
        "agents": _build_agents_yaml,
        "workflow": _build_workflow_yaml,
        "governance": _build_governance_yaml,
        "workitems": _build_workitems_yaml,
        "app": _build_app_yaml,
    }

    if component not in builders:
        valid = ", ".join(sorted(builders.keys()))
        raise GenerationError(f"Unknown component '{component}'. Valid: {valid}")

    try:
        profile_dict = ir_to_profile_dict(team)
        return builders[component](profile_dict)
    except Exception as exc:
        raise GenerationError(
            f"Failed to generate {component}.yaml: {exc}"
        ) from exc


def generate_profile_yaml(team: TeamSpec) -> dict[str, str]:
    """Generate all YAML files for a complete profile.

    Args:
        team: The complete team specification.

    Returns:
        Dict mapping filename to YAML content string.
        Keys: 'agents.yaml', 'workflow.yaml', 'governance.yaml',
              'workitems.yaml', and optionally 'app.yaml'.

    Raises:
        GenerationError: If generation fails.
    """
    try:
        profile_dict = ir_to_profile_dict(team)
    except Exception as exc:
        raise GenerationError(f"IR conversion failed: {exc}") from exc

    files: dict[str, str] = {
        "agents.yaml": _build_agents_yaml(profile_dict),
        "workflow.yaml": _build_workflow_yaml(profile_dict),
        "governance.yaml": _build_governance_yaml(profile_dict),
        "workitems.yaml": _build_workitems_yaml(profile_dict),
    }

    app_content = _build_app_yaml(profile_dict)
    if app_content:
        files["app.yaml"] = app_content

    logger.info("Generated %d YAML files for team '%s'", len(files), team.name)
    return files


def write_profile_to_directory(team: TeamSpec, output_dir: Path) -> list[Path]:
    """Generate and write all YAML files to a directory.

    Creates the directory if it doesn't exist.

    Args:
        team: The complete team specification.
        output_dir: Directory to write files into.

    Returns:
        List of paths to written files.

    Raises:
        GenerationError: If generation or writing fails.
    """
    files = generate_profile_yaml(team)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for filename, content in files.items():
        filepath = output_dir / filename
        try:
            filepath.write_text(content, encoding="utf-8")
            written.append(filepath)
            logger.debug("Wrote %s (%d bytes)", filepath, len(content))
        except OSError as exc:
            raise GenerationError(f"Failed to write {filepath}: {exc}") from exc

    logger.info("Wrote %d files to %s", len(written), output_dir)
    return written
