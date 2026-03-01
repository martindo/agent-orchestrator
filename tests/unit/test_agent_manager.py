"""Unit tests for AgentManager CRUD operations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from agent_orchestrator.configuration.agent_manager import AgentManager
from agent_orchestrator.configuration.loader import ConfigurationManager
from agent_orchestrator.configuration.models import AgentDefinition
from agent_orchestrator.exceptions import AgentError, ConfigurationError


# ---- Fixtures ----


def _create_workspace(tmp_path: Path, agents: list[dict] | None = None) -> Path:
    """Create a minimal workspace with settings and profile.

    Args:
        tmp_path: Temporary directory for the workspace.
        agents: Optional list of agent dicts to include.

    Returns:
        Path to workspace directory.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    profile_dir = workspace / "profiles" / "default"
    profile_dir.mkdir(parents=True)
    (workspace / ".history").mkdir()
    (workspace / ".state").mkdir()

    # settings.yaml
    settings = {"active_profile": "default"}
    with open(workspace / "settings.yaml", "w", encoding="utf-8") as f:
        yaml.dump(settings, f)

    # agents.yaml
    default_agents = agents or [
        {
            "id": "agent-1",
            "name": "Agent One",
            "system_prompt": "You are agent one.",
            "phases": ["process"],
            "llm": {"provider": "openai", "model": "gpt-4o"},
        },
        {
            "id": "agent-2",
            "name": "Agent Two",
            "system_prompt": "You are agent two.",
            "phases": ["review"],
            "llm": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
            "concurrency": 3,
        },
    ]
    with open(profile_dir / "agents.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"agents": default_agents}, f)

    # workflow.yaml (minimal)
    workflow = {
        "name": "default",
        "phases": [
            {"id": "process", "name": "Process", "order": 1, "agents": ["agent-1"]},
            {"id": "review", "name": "Review", "order": 2, "agents": ["agent-2"]},
        ],
    }
    with open(profile_dir / "workflow.yaml", "w", encoding="utf-8") as f:
        yaml.dump(workflow, f)

    return workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a test workspace."""
    return _create_workspace(tmp_path)


@pytest.fixture
def agent_manager(workspace: Path) -> AgentManager:
    """Create an AgentManager with loaded configuration."""
    config = ConfigurationManager(workspace)
    config.load()
    return AgentManager(config)


# ---- List / Get Tests ----


class TestAgentManagerRead:
    """Tests for agent read operations."""

    def test_list_agents(self, agent_manager: AgentManager) -> None:
        agents = agent_manager.list_agents()
        assert len(agents) == 2
        ids = {a.id for a in agents}
        assert ids == {"agent-1", "agent-2"}

    def test_get_agent(self, agent_manager: AgentManager) -> None:
        agent = agent_manager.get_agent("agent-1")
        assert agent is not None
        assert agent.name == "Agent One"
        assert agent.llm.provider == "openai"

    def test_get_unknown_returns_none(self, agent_manager: AgentManager) -> None:
        assert agent_manager.get_agent("nonexistent") is None


# ---- Create Tests ----


class TestAgentManagerCreate:
    """Tests for agent creation."""

    def test_create_agent(self, agent_manager: AgentManager) -> None:
        agent = agent_manager.create_agent({
            "id": "new-agent",
            "name": "New Agent",
            "system_prompt": "You are new.",
            "phases": ["process"],
            "llm": {"provider": "openai", "model": "gpt-4o"},
        })
        assert agent.id == "new-agent"
        assert agent.name == "New Agent"

        # Verify it's retrievable
        assert agent_manager.get_agent("new-agent") is not None
        assert len(agent_manager.list_agents()) == 3

    def test_create_duplicate_raises(self, agent_manager: AgentManager) -> None:
        with pytest.raises(AgentError, match="already exists"):
            agent_manager.create_agent({
                "id": "agent-1",
                "name": "Duplicate",
                "system_prompt": "test",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            })

    def test_validation_error(self, agent_manager: AgentManager) -> None:
        with pytest.raises(ConfigurationError, match="Invalid agent"):
            agent_manager.create_agent({
                "id": "bad-agent",
                # Missing required fields: name, system_prompt, phases, llm
            })

    def test_create_persists_to_disk(
        self, workspace: Path, agent_manager: AgentManager,
    ) -> None:
        agent_manager.create_agent({
            "id": "persisted-agent",
            "name": "Persisted",
            "system_prompt": "test",
            "phases": ["process"],
            "llm": {"provider": "openai", "model": "gpt-4o"},
        })

        # Reload from disk and verify
        config2 = ConfigurationManager(workspace)
        config2.load()
        am2 = AgentManager(config2)
        assert am2.get_agent("persisted-agent") is not None


# ---- Update Tests ----


class TestAgentManagerUpdate:
    """Tests for agent updates."""

    def test_update_agent(self, agent_manager: AgentManager) -> None:
        updated = agent_manager.update_agent("agent-1", {"name": "Updated Name"})
        assert updated.name == "Updated Name"
        assert updated.id == "agent-1"

        # Verify the change persists in memory
        fetched = agent_manager.get_agent("agent-1")
        assert fetched is not None
        assert fetched.name == "Updated Name"

    def test_update_unknown_raises(self, agent_manager: AgentManager) -> None:
        with pytest.raises(AgentError, match="not found"):
            agent_manager.update_agent("nonexistent", {"name": "X"})

    def test_update_concurrency(self, agent_manager: AgentManager) -> None:
        updated = agent_manager.update_agent("agent-2", {"concurrency": 5})
        assert updated.concurrency == 5


# ---- Delete Tests ----


class TestAgentManagerDelete:
    """Tests for agent deletion."""

    def test_delete_agent(self, agent_manager: AgentManager) -> None:
        assert agent_manager.delete_agent("agent-1") is True
        assert agent_manager.get_agent("agent-1") is None
        assert len(agent_manager.list_agents()) == 1

    def test_delete_unknown_returns_false(self, agent_manager: AgentManager) -> None:
        assert agent_manager.delete_agent("nonexistent") is False

    def test_delete_persists_to_disk(
        self, workspace: Path, agent_manager: AgentManager,
    ) -> None:
        agent_manager.delete_agent("agent-1")

        # Reload from disk and verify
        config2 = ConfigurationManager(workspace)
        config2.load()
        am2 = AgentManager(config2)
        assert am2.get_agent("agent-1") is None
        assert len(am2.list_agents()) == 1


# ---- Import Tests ----


class TestAgentManagerImport:
    """Tests for agent import from files."""

    def test_import_yaml(
        self, tmp_path: Path, agent_manager: AgentManager,
    ) -> None:
        import_file = tmp_path / "import.yaml"
        data = {
            "agents": [{
                "id": "imported-yaml",
                "name": "YAML Import",
                "system_prompt": "test",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }],
        }
        with open(import_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        imported = agent_manager.import_agents(import_file)
        assert len(imported) == 1
        assert imported[0].id == "imported-yaml"
        assert agent_manager.get_agent("imported-yaml") is not None

    def test_import_json(
        self, tmp_path: Path, agent_manager: AgentManager,
    ) -> None:
        import_file = tmp_path / "import.json"
        data = {
            "agents": [{
                "id": "imported-json",
                "name": "JSON Import",
                "system_prompt": "test",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }],
        }
        with open(import_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        imported = agent_manager.import_agents(import_file)
        assert len(imported) == 1
        assert imported[0].id == "imported-json"

    def test_import_single_agent_file(
        self, tmp_path: Path, agent_manager: AgentManager,
    ) -> None:
        """Test importing a file with a single agent (no 'agents' wrapper)."""
        import_file = tmp_path / "single.json"
        data = {
            "id": "single-agent",
            "name": "Single",
            "system_prompt": "test",
            "phases": ["process"],
            "llm": {"provider": "openai", "model": "gpt-4o"},
        }
        with open(import_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        imported = agent_manager.import_agents(import_file)
        assert len(imported) == 1
        assert imported[0].id == "single-agent"

    def test_import_skips_duplicates(
        self, tmp_path: Path, agent_manager: AgentManager,
    ) -> None:
        import_file = tmp_path / "dup.yaml"
        data = {
            "agents": [{
                "id": "agent-1",  # Already exists
                "name": "Duplicate",
                "system_prompt": "test",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }],
        }
        with open(import_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        imported = agent_manager.import_agents(import_file)
        assert len(imported) == 0  # Skipped


# ---- Export Tests ----


class TestAgentManagerExport:
    """Tests for agent export to files."""

    def test_export_yaml(
        self, tmp_path: Path, agent_manager: AgentManager,
    ) -> None:
        export_file = tmp_path / "exported.yaml"
        agent_manager.export_agents(export_file, fmt="yaml")

        assert export_file.exists()
        with open(export_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert len(data["agents"]) == 2

    def test_export_json(
        self, tmp_path: Path, agent_manager: AgentManager,
    ) -> None:
        export_file = tmp_path / "exported.json"
        agent_manager.export_agents(export_file, fmt="json")

        assert export_file.exists()
        with open(export_file, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["agents"]) == 2

    def test_export_unsupported_format_raises(
        self, tmp_path: Path, agent_manager: AgentManager,
    ) -> None:
        with pytest.raises(ConfigurationError, match="Unsupported export format"):
            agent_manager.export_agents(tmp_path / "out.xml", fmt="xml")


# ---- History Tests ----


class TestAgentManagerHistory:
    """Tests for config history recording."""

    def test_create_records_history(
        self, workspace: Path, agent_manager: AgentManager,
    ) -> None:
        history_dir = workspace / ".history"

        # Count initial history entries
        initial_count = len(list(history_dir.iterdir()))

        agent_manager.create_agent({
            "id": "history-test",
            "name": "History Test",
            "system_prompt": "test",
            "phases": ["process"],
            "llm": {"provider": "openai", "model": "gpt-4o"},
        })

        # Should have recorded at least one history entry
        final_count = len(list(history_dir.iterdir()))
        assert final_count > initial_count


# ---- JSON Config Loading Tests ----


class TestJSONConfigLoading:
    """Tests for JSON configuration file support."""

    def test_load_agents_from_json(self, tmp_path: Path) -> None:
        """Test that agents can be loaded from agents.json."""
        workspace = tmp_path / "json_workspace"
        workspace.mkdir()
        profile_dir = workspace / "profiles" / "default"
        profile_dir.mkdir(parents=True)
        (workspace / ".history").mkdir()

        # settings.yaml
        with open(workspace / "settings.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"active_profile": "default"}, f)

        # agents.json (instead of agents.yaml)
        agents_data = {
            "agents": [{
                "id": "json-agent",
                "name": "JSON Agent",
                "system_prompt": "test",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }],
        }
        with open(profile_dir / "agents.json", "w", encoding="utf-8") as f:
            json.dump(agents_data, f)

        # workflow.yaml (minimal required)
        with open(profile_dir / "workflow.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"name": "default"}, f)

        config = ConfigurationManager(workspace)
        config.load()
        am = AgentManager(config)

        agents = am.list_agents()
        assert len(agents) == 1
        assert agents[0].id == "json-agent"

    def test_yaml_takes_precedence_over_json(self, tmp_path: Path) -> None:
        """Test that YAML file takes precedence when both exist."""
        workspace = tmp_path / "dual_workspace"
        workspace.mkdir()
        profile_dir = workspace / "profiles" / "default"
        profile_dir.mkdir(parents=True)
        (workspace / ".history").mkdir()

        with open(workspace / "settings.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"active_profile": "default"}, f)

        # agents.yaml (should take precedence)
        yaml_agents = {
            "agents": [{
                "id": "yaml-agent",
                "name": "YAML Agent",
                "system_prompt": "test",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }],
        }
        with open(profile_dir / "agents.yaml", "w", encoding="utf-8") as f:
            yaml.dump(yaml_agents, f)

        # agents.json (should be ignored)
        json_agents = {
            "agents": [{
                "id": "json-agent",
                "name": "JSON Agent",
                "system_prompt": "test",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }],
        }
        with open(profile_dir / "agents.json", "w", encoding="utf-8") as f:
            json.dump(json_agents, f)

        with open(profile_dir / "workflow.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"name": "default"}, f)

        config = ConfigurationManager(workspace)
        config.load()
        am = AgentManager(config)

        agents = am.list_agents()
        assert len(agents) == 1
        assert agents[0].id == "yaml-agent"  # YAML wins


# ---- Profile Component Export Tests ----


class TestProfileComponentExport:
    """Tests for exporting individual profile components."""

    @pytest.fixture
    def config_manager(self, workspace: Path) -> ConfigurationManager:
        """Create a ConfigurationManager with loaded configuration."""
        config = ConfigurationManager(workspace)
        config.load()
        return config

    def test_export_agents_component(
        self, config_manager: ConfigurationManager,
    ) -> None:
        data = config_manager.get_profile_component("agents")
        assert "agents" in data
        assert len(data["agents"]) == 2
        assert data["agents"][0]["id"] == "agent-1"

    def test_export_workflow_component(
        self, config_manager: ConfigurationManager,
    ) -> None:
        data = config_manager.get_profile_component("workflow")
        assert "name" in data
        assert "phases" in data
        assert len(data["phases"]) == 2

    def test_export_governance_component(
        self, config_manager: ConfigurationManager,
    ) -> None:
        data = config_manager.get_profile_component("governance")
        assert "delegated_authority" in data
        assert "policies" in data

    def test_export_workitems_component(
        self, config_manager: ConfigurationManager,
    ) -> None:
        data = config_manager.get_profile_component("workitems")
        assert "work_item_types" in data

    def test_export_all_component(
        self, config_manager: ConfigurationManager,
    ) -> None:
        data = config_manager.get_profile_component("all")
        assert "agents" in data
        assert "workflow" in data
        assert "governance" in data
        assert "work_item_types" in data

    def test_export_invalid_component_raises(
        self, config_manager: ConfigurationManager,
    ) -> None:
        with pytest.raises(ConfigurationError, match="Unknown component"):
            config_manager.get_profile_component("invalid")

    def test_export_component_to_yaml_file(
        self, tmp_path: Path, config_manager: ConfigurationManager,
    ) -> None:
        out = tmp_path / "workflow.yaml"
        config_manager.export_profile_component("workflow", out)

        assert out.exists()
        with open(out, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["name"] == "default"
        assert len(data["phases"]) == 2

    def test_export_component_to_json_file(
        self, tmp_path: Path, config_manager: ConfigurationManager,
    ) -> None:
        out = tmp_path / "agents.json"
        config_manager.export_profile_component("agents", out)

        assert out.exists()
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["agents"]) == 2

    def test_export_all_to_directory(
        self, tmp_path: Path, config_manager: ConfigurationManager,
    ) -> None:
        out_dir = tmp_path / "new-domain"
        created = config_manager.export_profile_to_directory(out_dir, fmt="yaml")

        assert out_dir.is_dir()
        assert len(created) == 4
        filenames = {p.name for p in created}
        assert filenames == {"agents.yaml", "workflow.yaml", "governance.yaml", "workitems.yaml"}

        # Verify each file is valid YAML with correct content
        with open(out_dir / "agents.yaml", encoding="utf-8") as f:
            assert "agents" in yaml.safe_load(f)
        with open(out_dir / "workflow.yaml", encoding="utf-8") as f:
            assert "name" in yaml.safe_load(f)

    def test_export_all_to_directory_json(
        self, tmp_path: Path, config_manager: ConfigurationManager,
    ) -> None:
        out_dir = tmp_path / "new-domain-json"
        created = config_manager.export_profile_to_directory(out_dir, fmt="json")

        assert len(created) == 4
        filenames = {p.name for p in created}
        assert filenames == {"agents.json", "workflow.json", "governance.json", "workitems.json"}

    def test_exported_agents_are_reimportable(
        self, tmp_path: Path, config_manager: ConfigurationManager,
    ) -> None:
        """Verify exported agents can be loaded back as a valid profile."""
        out_dir = tmp_path / "reimport-test"
        config_manager.export_profile_to_directory(out_dir, fmt="yaml")

        # Should be loadable as a profile
        from agent_orchestrator.configuration.loader import load_profile
        profile = load_profile(out_dir)
        assert len(profile.agents) == 2
        assert profile.workflow.name == "default"
