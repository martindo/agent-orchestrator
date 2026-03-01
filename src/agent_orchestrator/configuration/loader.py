"""Configuration loader — loads YAML files and parses into Pydantic models.

Responsibilities:
- Load YAML files from workspace/profile directories
- Parse into validated Pydantic models
- Support hot-reload via file watching
- Support import/export of config bundles

Thread-safe: All public methods are safe to call from multiple threads.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import json

import yaml
from pydantic import ValidationError as PydanticValidationError

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    GovernanceConfig,
    ProfileConfig,
    SettingsConfig,
    WorkflowConfig,
    WorkItemTypeConfig,
)
from agent_orchestrator.exceptions import ConfigurationError, ProfileError

logger = logging.getLogger(__name__)

# ---- Named Constants ----

SETTINGS_FILENAME = "settings.yaml"
AGENTS_FILENAME = "agents.yaml"
AGENTS_JSON_FILENAME = "agents.json"
WORKFLOW_FILENAME = "workflow.yaml"
GOVERNANCE_FILENAME = "governance.yaml"
WORKITEMS_FILENAME = "workitems.yaml"
PROFILES_DIR_NAME = "profiles"
SUPPORTED_YAML_EXTENSIONS = frozenset({".yaml", ".yml"})
SUPPORTED_JSON_EXTENSIONS = frozenset({".json"})
SUPPORTED_CONFIG_EXTENSIONS = SUPPORTED_YAML_EXTENSIONS | SUPPORTED_JSON_EXTENSIONS

_PROFILE_FILES = [AGENTS_FILENAME, WORKFLOW_FILENAME, GOVERNANCE_FILENAME, WORKITEMS_FILENAME]

# Components that can be exported individually
PROFILE_COMPONENTS = frozenset({"agents", "workflow", "governance", "workitems", "all"})

# Map component names to their default filenames
_COMPONENT_FILENAMES: dict[str, str] = {
    "agents": AGENTS_FILENAME,
    "workflow": WORKFLOW_FILENAME,
    "governance": GOVERNANCE_FILENAME,
    "workitems": WORKITEMS_FILENAME,
}


def _serialize_component(
    profile: ProfileConfig, component: str,
) -> dict[str, Any]:
    """Serialize a profile component to a dict for export.

    Args:
        profile: The loaded profile.
        component: One of 'agents', 'workflow', 'governance', 'workitems', 'all'.

    Returns:
        Serializable dict matching the on-disk file format.

    Raises:
        ConfigurationError: If component name is invalid.
    """
    if component not in PROFILE_COMPONENTS:
        msg = (
            f"Unknown component '{component}'. "
            f"Must be one of: {', '.join(sorted(PROFILE_COMPONENTS))}"
        )
        raise ConfigurationError(msg)

    if component == "agents":
        return {"agents": [a.model_dump() for a in profile.agents]}
    if component == "workflow":
        return profile.workflow.model_dump()
    if component == "governance":
        return profile.governance.model_dump()
    if component == "workitems":
        return {"work_item_types": [w.model_dump() for w in profile.work_item_types]}
    # component == "all"
    return {
        "agents": [a.model_dump() for a in profile.agents],
        "workflow": profile.workflow.model_dump(),
        "governance": profile.governance.model_dump(),
        "work_item_types": [w.model_dump() for w in profile.work_item_types],
    }


def _read_json(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file.

    Args:
        path: Path to JSON file.

    Returns:
        Parsed JSON content as dict.

    Raises:
        ConfigurationError: If file not found or invalid JSON.
    """
    if not path.exists():
        msg = f"Configuration file not found: {path}"
        raise ConfigurationError(msg)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON in {path}: {e}"
        raise ConfigurationError(msg) from e

    if not isinstance(data, dict):
        msg = f"Expected JSON object in {path}, got {type(data).__name__}"
        raise ConfigurationError(msg)
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write data to a JSON file with atomic write pattern.

    Args:
        path: Target file path.
        data: Data to serialize.

    Raises:
        ConfigurationError: If write fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        temp_path.replace(path)
    except OSError as e:
        msg = f"Failed to write config to {path}: {e}"
        raise ConfigurationError(msg) from e
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _read_config_file(path: Path) -> dict[str, Any]:
    """Read a configuration file, dispatching by extension.

    Supports .json, .yaml, and .yml extensions.

    Args:
        path: Path to configuration file.

    Returns:
        Parsed content as dict.

    Raises:
        ConfigurationError: If file not found, invalid, or unsupported extension.
    """
    ext = path.suffix.lower()
    if ext in SUPPORTED_JSON_EXTENSIONS:
        return _read_json(path)
    if ext in SUPPORTED_YAML_EXTENSIONS:
        return _read_yaml(path)
    msg = f"Unsupported config file extension '{ext}' for {path}"
    raise ConfigurationError(msg)


def _write_config_file(path: Path, data: dict[str, Any]) -> None:
    """Write a configuration file, dispatching by extension.

    Supports .json, .yaml, and .yml extensions.

    Args:
        path: Target file path.
        data: Data to serialize.

    Raises:
        ConfigurationError: If unsupported extension or write fails.
    """
    ext = path.suffix.lower()
    if ext in SUPPORTED_JSON_EXTENSIONS:
        _write_json(path, data)
    elif ext in SUPPORTED_YAML_EXTENSIONS:
        _write_yaml(path, data)
    else:
        msg = f"Unsupported config file extension '{ext}' for {path}"
        raise ConfigurationError(msg)


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file.

    Args:
        path: Path to YAML file.

    Returns:
        Parsed YAML content as dict.

    Raises:
        ConfigurationError: If file not found or invalid YAML.
    """
    if not path.exists():
        msg = f"Configuration file not found: {path}"
        raise ConfigurationError(msg)
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        msg = f"Invalid YAML in {path}: {e}"
        raise ConfigurationError(msg) from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = f"Expected YAML mapping in {path}, got {type(data).__name__}"
        raise ConfigurationError(msg)
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write data to a YAML file with atomic write pattern.

    Args:
        path: Target file path.
        data: Data to serialize.

    Raises:
        ConfigurationError: If write fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        # Atomic replace (works on same filesystem)
        temp_path.replace(path)
    except OSError as e:
        msg = f"Failed to write config to {path}: {e}"
        raise ConfigurationError(msg) from e
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def load_settings(workspace_dir: Path) -> SettingsConfig:
    """Load workspace-level settings from settings.yaml.

    Args:
        workspace_dir: Root workspace directory.

    Returns:
        Validated SettingsConfig.

    Raises:
        ConfigurationError: If file missing or invalid.
    """
    settings_path = workspace_dir / SETTINGS_FILENAME
    data = _read_yaml(settings_path)
    try:
        return SettingsConfig(**data)
    except PydanticValidationError as e:
        msg = f"Invalid settings in {settings_path}: {e}"
        raise ConfigurationError(msg) from e


def save_settings(workspace_dir: Path, settings: SettingsConfig) -> None:
    """Save workspace settings to settings.yaml.

    Args:
        workspace_dir: Root workspace directory.
        settings: Settings to persist.
    """
    settings_path = workspace_dir / SETTINGS_FILENAME
    _write_yaml(settings_path, settings.model_dump())
    logger.info("Settings saved to %s", settings_path)


def _load_agents(profile_dir: Path) -> list[AgentDefinition]:
    """Load agent definitions from agents.yaml or agents.json.

    YAML takes precedence if both exist.
    """
    yaml_path = profile_dir / AGENTS_FILENAME
    json_path = profile_dir / AGENTS_JSON_FILENAME

    # YAML takes precedence
    if yaml_path.exists():
        agents_path = yaml_path
    elif json_path.exists():
        agents_path = json_path
    else:
        return []

    data = _read_config_file(agents_path)
    agents_data = data.get("agents", [])
    try:
        return [AgentDefinition(**a) for a in agents_data]
    except PydanticValidationError as e:
        msg = f"Invalid agent definition in {agents_path}: {e}"
        raise ConfigurationError(msg) from e


def _load_workflow(profile_dir: Path) -> WorkflowConfig:
    """Load workflow configuration from workflow.yaml."""
    workflow_path = profile_dir / WORKFLOW_FILENAME
    if not workflow_path.exists():
        return WorkflowConfig(name="default")
    data = _read_yaml(workflow_path)
    try:
        return WorkflowConfig(**data)
    except PydanticValidationError as e:
        msg = f"Invalid workflow in {workflow_path}: {e}"
        raise ConfigurationError(msg) from e


def _load_governance(profile_dir: Path) -> GovernanceConfig:
    """Load governance configuration from governance.yaml."""
    governance_path = profile_dir / GOVERNANCE_FILENAME
    if not governance_path.exists():
        return GovernanceConfig()
    data = _read_yaml(governance_path)
    try:
        return GovernanceConfig(**data)
    except PydanticValidationError as e:
        msg = f"Invalid governance config in {governance_path}: {e}"
        raise ConfigurationError(msg) from e


def _load_work_item_types(profile_dir: Path) -> list[WorkItemTypeConfig]:
    """Load work item type definitions from workitems.yaml."""
    workitems_path = profile_dir / WORKITEMS_FILENAME
    if not workitems_path.exists():
        return []
    data = _read_yaml(workitems_path)
    types_data = data.get("work_item_types", [])
    try:
        return [WorkItemTypeConfig(**t) for t in types_data]
    except PydanticValidationError as e:
        msg = f"Invalid work item types in {workitems_path}: {e}"
        raise ConfigurationError(msg) from e


def load_profile(profile_dir: Path) -> ProfileConfig:
    """Load a complete profile from a directory.

    Loads agents.yaml, workflow.yaml, governance.yaml, and workitems.yaml
    from the given profile directory and assembles them into a ProfileConfig.

    Args:
        profile_dir: Directory containing profile YAML files.

    Returns:
        Validated ProfileConfig.

    Raises:
        ProfileError: If profile directory doesn't exist.
        ConfigurationError: If any config file is invalid.
    """
    if not profile_dir.is_dir():
        msg = f"Profile directory not found: {profile_dir}"
        raise ProfileError(msg)

    profile_name = profile_dir.name
    logger.info("Loading profile '%s' from %s", profile_name, profile_dir)

    agents = _load_agents(profile_dir)
    workflow = _load_workflow(profile_dir)
    governance = _load_governance(profile_dir)
    work_item_types = _load_work_item_types(profile_dir)

    return ProfileConfig(
        name=profile_name,
        agents=agents,
        workflow=workflow,
        governance=governance,
        work_item_types=work_item_types,
    )


def list_profiles(workspace_dir: Path) -> list[str]:
    """List available profile names in a workspace.

    Args:
        workspace_dir: Root workspace directory.

    Returns:
        List of profile directory names.
    """
    profiles_dir = workspace_dir / PROFILES_DIR_NAME
    if not profiles_dir.is_dir():
        return []
    return sorted(
        d.name for d in profiles_dir.iterdir()
        if d.is_dir() and any((d / f).exists() for f in _PROFILE_FILES)
    )


def load_active_profile(workspace_dir: Path) -> ProfileConfig:
    """Load the currently active profile from workspace settings.

    Args:
        workspace_dir: Root workspace directory.

    Returns:
        Validated ProfileConfig for the active profile.

    Raises:
        ProfileError: If active profile not found.
        ConfigurationError: If settings or profile config invalid.
    """
    settings = load_settings(workspace_dir)
    profile_dir = workspace_dir / PROFILES_DIR_NAME / settings.active_profile
    if not profile_dir.is_dir():
        msg = f"Active profile '{settings.active_profile}' not found at {profile_dir}"
        raise ProfileError(msg)
    return load_profile(profile_dir)


class ConfigurationManager:
    """Manages configuration loading and hot-reload.

    Thread-safe: Uses internal lock to protect state.

    State Ownership:
    - ConfigurationManager owns settings, active profile, and profile cache.
    - External code should read via get_settings/get_profile methods.
    """

    def __init__(self, workspace_dir: Path) -> None:
        self._workspace_dir = workspace_dir
        self._settings: SettingsConfig | None = None
        self._profile: ProfileConfig | None = None
        self._lock = threading.Lock()

    @property
    def workspace_dir(self) -> Path:
        """Root workspace directory."""
        return self._workspace_dir

    def load(self) -> None:
        """Load settings and active profile.

        Raises:
            ConfigurationError: If configuration is invalid.
            ProfileError: If active profile not found.
        """
        with self._lock:
            self._settings = load_settings(self._workspace_dir)
            self._profile = load_active_profile(self._workspace_dir)
            logger.info(
                "Configuration loaded: profile='%s', agents=%d, phases=%d",
                self._profile.name,
                len(self._profile.agents),
                len(self._profile.workflow.phases),
            )

    def reload(self) -> None:
        """Reload all configuration from disk.

        Raises:
            ConfigurationError: If configuration is invalid.
        """
        logger.info("Reloading configuration from %s", self._workspace_dir)
        self.load()

    def get_settings(self) -> SettingsConfig:
        """Get current settings.

        Returns:
            Current SettingsConfig.

        Raises:
            ConfigurationError: If not loaded yet.
        """
        with self._lock:
            if self._settings is None:
                msg = "Configuration not loaded. Call load() first."
                raise ConfigurationError(msg)
            return self._settings

    def get_profile(self) -> ProfileConfig:
        """Get current active profile.

        Returns:
            Current ProfileConfig.

        Raises:
            ConfigurationError: If not loaded yet.
        """
        with self._lock:
            if self._profile is None:
                msg = "Configuration not loaded. Call load() first."
                raise ConfigurationError(msg)
            return self._profile

    def switch_profile(self, profile_name: str) -> ProfileConfig:
        """Switch to a different profile.

        Updates settings and reloads the profile configuration.

        Args:
            profile_name: Name of the profile to switch to.

        Returns:
            The newly loaded ProfileConfig.

        Raises:
            ProfileError: If profile not found.
        """
        with self._lock:
            profile_dir = self._workspace_dir / PROFILES_DIR_NAME / profile_name
            if not profile_dir.is_dir():
                msg = f"Profile '{profile_name}' not found at {profile_dir}"
                raise ProfileError(msg)

            self._profile = load_profile(profile_dir)

            # Update settings with new active profile
            if self._settings is not None:
                new_settings = self._settings.model_copy(
                    update={"active_profile": profile_name},
                )
                save_settings(self._workspace_dir, new_settings)
                self._settings = new_settings

            logger.info("Switched to profile '%s'", profile_name)
            return self._profile

    def list_profiles(self) -> list[str]:
        """List available profiles.

        Returns:
            List of profile names.
        """
        return list_profiles(self._workspace_dir)

    def get_profile_component(self, component: str) -> dict[str, Any]:
        """Get a single profile component as a serializable dict.

        Reads from the loaded in-memory profile, not from disk.

        Args:
            component: One of 'agents', 'workflow', 'governance', 'workitems', 'all'.

        Returns:
            Dictionary ready for JSON/YAML serialization.

        Raises:
            ConfigurationError: If profile not loaded or invalid component.
        """
        profile = self.get_profile()
        return _serialize_component(profile, component)

    def export_profile_component(
        self, component: str, output_path: Path,
    ) -> None:
        """Export a profile component to a file (JSON or YAML by extension).

        Reads from the loaded in-memory profile, not from disk.

        Args:
            component: One of 'agents', 'workflow', 'governance', 'workitems', 'all'.
            output_path: Target file path (.json, .yaml, or .yml).

        Raises:
            ConfigurationError: If profile not loaded, invalid component, or write fails.
        """
        data = self.get_profile_component(component)
        _write_config_file(output_path, data)
        logger.info("Exported '%s' to %s", component, output_path)

    def export_profile_to_directory(
        self, output_dir: Path, fmt: str = "yaml",
    ) -> list[Path]:
        """Export all profile components to separate files in a directory.

        Creates one file per component, ready to use as a new profile.

        Args:
            output_dir: Target directory (created if needed).
            fmt: Output format ('yaml' or 'json').

        Returns:
            List of created file paths.

        Raises:
            ConfigurationError: If profile not loaded or write fails.
        """
        profile = self.get_profile()
        output_dir.mkdir(parents=True, exist_ok=True)

        ext = ".json" if fmt == "json" else ".yaml"
        created: list[Path] = []

        for component, filename in _COMPONENT_FILENAMES.items():
            data = _serialize_component(profile, component)
            stem = Path(filename).stem
            out_path = output_dir / f"{stem}{ext}"
            _write_config_file(out_path, data)
            created.append(out_path)

        logger.info(
            "Exported %d component(s) to %s", len(created), output_dir,
        )
        return created
