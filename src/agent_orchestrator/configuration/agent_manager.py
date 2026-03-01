"""AgentManager — Central CRUD logic for agent definitions.

Provides create, read, update, delete operations for agent definitions
within the active profile. Used by API, CLI, and file-based interfaces.

Thread-safe: All public methods use internal lock.

State Ownership:
- AgentManager owns agent definition CRUD and persistence.
- ConfigurationManager owns profile loading and settings.
- AgentPool owns runtime agent instances (separate concern).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from agent_orchestrator.configuration.loader import (
    AGENTS_FILENAME,
    AGENTS_JSON_FILENAME,
    PROFILES_DIR_NAME,
    SUPPORTED_JSON_EXTENSIONS,
    ConfigurationManager,
    _read_config_file,
    _write_config_file,
    _write_yaml,
)
from agent_orchestrator.configuration.models import AgentDefinition
from agent_orchestrator.exceptions import AgentError, ConfigurationError
from agent_orchestrator.persistence.config_history import ConfigHistory

logger = logging.getLogger(__name__)

# ---- Named Constants ----

DEFAULT_EXPORT_FORMAT = "yaml"
SUPPORTED_EXPORT_FORMATS = frozenset({"yaml", "json"})


class AgentManager:
    """Central CRUD manager for agent definitions.

    Thread-safe: All public methods use internal lock.

    State Ownership:
    - Owns the in-memory agent definitions list for the active profile.
    - Persists changes to agents.yaml (or .json) in the active profile.
    - Records config history for undo capability.

    Usage:
        manager = AgentManager(config_manager)
        agent = manager.create_agent({"id": "my-agent", ...})
        agents = manager.list_agents()
        manager.delete_agent("my-agent")
    """

    def __init__(self, config_manager: ConfigurationManager) -> None:
        self._config = config_manager
        self._agents: dict[str, AgentDefinition] = {}
        self._lock = threading.Lock()
        self._history: ConfigHistory | None = None
        self._initialize()

    def _initialize(self) -> None:
        """Load agents from current profile into memory."""
        try:
            profile = self._config.get_profile()
            with self._lock:
                self._agents = {a.id: a for a in profile.agents}

            # Set up config history if workspace has .history dir
            history_dir = self._config.workspace_dir / ".history"
            if history_dir.is_dir():
                self._history = ConfigHistory(history_dir)

            logger.info(
                "AgentManager initialized with %d agents", len(self._agents),
            )
        except ConfigurationError:
            logger.warning(
                "Configuration not loaded; AgentManager starting empty",
            )

    def list_agents(self) -> list[AgentDefinition]:
        """List all agent definitions in the active profile.

        Returns:
            List of AgentDefinition objects.
        """
        with self._lock:
            return list(self._agents.values())

    def get_agent(self, agent_id: str) -> AgentDefinition | None:
        """Get a single agent definition by ID.

        Args:
            agent_id: Unique agent identifier.

        Returns:
            AgentDefinition if found, None otherwise.
        """
        with self._lock:
            return self._agents.get(agent_id)

    def create_agent(self, agent_data: dict[str, Any]) -> AgentDefinition:
        """Create a new agent definition.

        Validates via Pydantic, checks for duplicate IDs, persists to disk.

        Args:
            agent_data: Dictionary of agent fields matching AgentDefinition.

        Returns:
            The created AgentDefinition.

        Raises:
            AgentError: If agent ID already exists.
            ConfigurationError: If validation or persistence fails.
        """
        agent = self._validate_agent_data(agent_data)

        with self._lock:
            if agent.id in self._agents:
                msg = f"Agent '{agent.id}' already exists"
                raise AgentError(msg)
            self._agents[agent.id] = agent

        self._persist_agents()
        logger.info("Created agent '%s'", agent.id)
        return agent

    def update_agent(
        self, agent_id: str, updates: dict[str, Any],
    ) -> AgentDefinition:
        """Update an existing agent definition.

        Uses model_copy(update=...) since models are frozen.

        Args:
            agent_id: ID of the agent to update.
            updates: Dictionary of fields to update.

        Returns:
            The updated AgentDefinition.

        Raises:
            AgentError: If agent not found.
            ConfigurationError: If validation or persistence fails.
        """
        with self._lock:
            existing = self._agents.get(agent_id)
            if existing is None:
                msg = f"Agent '{agent_id}' not found"
                raise AgentError(msg)

            try:
                updated = existing.model_copy(update=updates)
            except (PydanticValidationError, ValueError) as e:
                msg = f"Invalid update for agent '{agent_id}': {e}"
                raise ConfigurationError(msg) from e

            self._agents[agent_id] = updated

        self._persist_agents()
        logger.info("Updated agent '%s'", agent_id)
        return updated

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent definition.

        Args:
            agent_id: ID of the agent to delete.

        Returns:
            True if agent was found and deleted, False if not found.
        """
        with self._lock:
            if agent_id not in self._agents:
                logger.warning("Cannot delete unknown agent '%s'", agent_id)
                return False
            del self._agents[agent_id]

        self._persist_agents()
        logger.info("Deleted agent '%s'", agent_id)
        return True

    def import_agents(self, file_path: Path) -> list[AgentDefinition]:
        """Import agent definitions from a JSON or YAML file.

        Agents are added to the active profile. Duplicates are skipped
        with a warning.

        Args:
            file_path: Path to the agent definition file.

        Returns:
            List of successfully imported AgentDefinitions.

        Raises:
            ConfigurationError: If file is invalid or unreadable.
        """
        data = _read_config_file(file_path)
        agents_data = data.get("agents", [])

        # Support single-agent files (no "agents" wrapper)
        if not agents_data and "id" in data:
            agents_data = [data]

        imported: list[AgentDefinition] = []
        for agent_data in agents_data:
            agent = self._validate_agent_data(agent_data)
            with self._lock:
                if agent.id in self._agents:
                    logger.warning(
                        "Skipping duplicate agent '%s' during import", agent.id,
                    )
                    continue
                self._agents[agent.id] = agent
            imported.append(agent)

        if imported:
            self._persist_agents()
            logger.info(
                "Imported %d agent(s) from %s", len(imported), file_path,
            )
        return imported

    def export_agents(
        self, file_path: Path, fmt: str = DEFAULT_EXPORT_FORMAT,
    ) -> None:
        """Export all agent definitions to a file.

        Args:
            file_path: Target file path.
            fmt: Export format ('yaml' or 'json').

        Raises:
            ConfigurationError: If format unsupported or write fails.
        """
        if fmt not in SUPPORTED_EXPORT_FORMATS:
            msg = f"Unsupported export format '{fmt}', must be one of {SUPPORTED_EXPORT_FORMATS}"
            raise ConfigurationError(msg)

        with self._lock:
            agents_data = [a.model_dump() for a in self._agents.values()]

        data = {"agents": agents_data}
        _write_config_file(file_path, data)
        logger.info("Exported %d agent(s) to %s", len(agents_data), file_path)

    def _validate_agent_data(
        self, agent_data: dict[str, Any],
    ) -> AgentDefinition:
        """Validate agent data and return an AgentDefinition.

        Args:
            agent_data: Raw agent data dictionary.

        Returns:
            Validated AgentDefinition.

        Raises:
            ConfigurationError: If validation fails.
        """
        try:
            return AgentDefinition(**agent_data)
        except (PydanticValidationError, ValueError, TypeError) as e:
            msg = f"Invalid agent definition: {e}"
            raise ConfigurationError(msg) from e

    def _persist_agents(self) -> None:
        """Write current agents to the active profile's agents file.

        Determines output file based on what exists in the profile dir.
        Defaults to agents.yaml if neither exists.

        Raises:
            ConfigurationError: If persistence fails.
        """
        profile_dir = self._get_profile_dir()
        agents_path = self._resolve_agents_path(profile_dir)

        with self._lock:
            agents_data = [a.model_dump() for a in self._agents.values()]

        data = {"agents": agents_data}

        # Record history before overwriting
        if self._history is not None and agents_path.exists():
            try:
                self._history.record(agents_path, label="agent_crud")
            except Exception as e:
                logger.warning(
                    "Failed to record config history: %s", e, exc_info=True,
                )

        _write_config_file(agents_path, data)
        logger.debug("Persisted %d agents to %s", len(agents_data), agents_path)

    def _get_profile_dir(self) -> Path:
        """Get the active profile directory path.

        Returns:
            Path to the active profile directory.

        Raises:
            ConfigurationError: If settings not loaded.
        """
        settings = self._config.get_settings()
        return (
            self._config.workspace_dir / PROFILES_DIR_NAME / settings.active_profile
        )

    def _resolve_agents_path(self, profile_dir: Path) -> Path:
        """Determine the agents file path in a profile directory.

        Uses existing file if found (JSON or YAML). Defaults to YAML.

        Args:
            profile_dir: Profile directory path.

        Returns:
            Path to the agents file.
        """
        json_path = profile_dir / AGENTS_JSON_FILENAME
        yaml_path = profile_dir / AGENTS_FILENAME

        # Prefer existing file format
        if yaml_path.exists():
            return yaml_path
        if json_path.exists():
            return json_path
        # Default to YAML for new files
        return yaml_path
