"""Unit tests for configuration models, loader, and validator."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Ensure src is on path
_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    ConditionConfig,
    DelegatedAuthorityConfig,
    FieldDefinition,
    FieldType,
    GovernanceConfig,
    LLMConfig,
    PolicyConfig,
    ProfileConfig,
    QualityGateConfig,
    RetryPolicy,
    SettingsConfig,
    StatusConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
    WorkItemTypeConfig,
)
from agent_orchestrator.configuration.loader import (
    ConfigurationManager,
    load_active_profile,
    load_profile,
    load_settings,
    list_profiles,
    save_settings,
)
from agent_orchestrator.configuration.validator import (
    ValidationResult,
    validate_agent_phase_references,
    validate_governance,
    validate_llm_providers,
    validate_phase_graph,
    validate_profile,
    validate_status_transitions,
)
from agent_orchestrator.exceptions import ConfigurationError, ProfileError


# ---- Model Tests ----


class TestLLMConfig:
    """Tests for LLMConfig model."""

    def test_valid_config(self) -> None:
        config = LLMConfig(provider="openai", model="gpt-4o")
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.temperature == 0.3
        assert config.max_tokens == 4000

    def test_custom_endpoint(self) -> None:
        config = LLMConfig(
            provider="ollama",
            model="llama3",
            endpoint="http://localhost:11434",
        )
        assert config.endpoint == "http://localhost:11434"

    def test_invalid_temperature(self) -> None:
        with pytest.raises(ValueError, match="Temperature"):
            LLMConfig(provider="openai", model="gpt-4o", temperature=3.0)

    def test_invalid_max_tokens(self) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            LLMConfig(provider="openai", model="gpt-4o", max_tokens=0)

    def test_frozen(self) -> None:
        config = LLMConfig(provider="openai", model="gpt-4o")
        with pytest.raises(Exception):
            config.provider = "anthropic"  # type: ignore[misc]


class TestSettingsConfig:
    """Tests for SettingsConfig model."""

    def test_valid_settings(self) -> None:
        settings = SettingsConfig(
            active_profile="my-profile",
            api_keys={"openai": "sk-key"},
        )
        assert settings.active_profile == "my-profile"
        assert settings.log_level == "INFO"

    def test_invalid_log_level(self) -> None:
        with pytest.raises(ValueError, match="Invalid log level"):
            SettingsConfig(active_profile="test", log_level="VERBOSE")

    def test_invalid_backend(self) -> None:
        with pytest.raises(ValueError, match="Invalid persistence backend"):
            SettingsConfig(active_profile="test", persistence_backend="redis")

    def test_log_level_case_insensitive(self) -> None:
        settings = SettingsConfig(active_profile="test", log_level="debug")
        assert settings.log_level == "DEBUG"


class TestAgentDefinition:
    """Tests for AgentDefinition model."""

    def test_valid_agent(self, sample_llm_config: LLMConfig) -> None:
        agent = AgentDefinition(
            id="agent-1",
            name="Agent One",
            system_prompt="You are agent one.",
            phases=["phase-1"],
            llm=sample_llm_config,
        )
        assert agent.id == "agent-1"
        assert agent.enabled is True
        assert agent.concurrency == 1

    def test_invalid_concurrency(self, sample_llm_config: LLMConfig) -> None:
        with pytest.raises(ValueError, match="Concurrency"):
            AgentDefinition(
                id="agent-1",
                name="Agent One",
                system_prompt="test",
                phases=["p1"],
                llm=sample_llm_config,
                concurrency=0,
            )

    def test_default_retry_policy(self, sample_llm_config: LLMConfig) -> None:
        agent = AgentDefinition(
            id="a1", name="A1", system_prompt="test", phases=["p1"], llm=sample_llm_config,
        )
        assert agent.retry_policy.max_retries == 3


class TestFieldDefinition:
    """Tests for FieldDefinition model."""

    def test_enum_requires_values(self) -> None:
        with pytest.raises(ValueError, match="Enum fields must specify"):
            FieldDefinition(name="status", type=FieldType.ENUM)

    def test_enum_with_values(self) -> None:
        field = FieldDefinition(
            name="status", type=FieldType.ENUM, values=["open", "closed"],
        )
        assert field.values == ["open", "closed"]

    def test_string_no_values_needed(self) -> None:
        field = FieldDefinition(name="title", type=FieldType.STRING)
        assert field.values is None


class TestWorkflowConfig:
    """Tests for WorkflowConfig model."""

    def test_valid_workflow(self, sample_workflow: WorkflowConfig) -> None:
        assert sample_workflow.name == "test-workflow"
        assert len(sample_workflow.phases) == 2
        assert len(sample_workflow.statuses) == 3


class TestProfileConfig:
    """Tests for ProfileConfig model."""

    def test_valid_profile(self, sample_profile: ProfileConfig) -> None:
        assert sample_profile.name == "test-profile"
        assert len(sample_profile.agents) == 1
        assert len(sample_profile.work_item_types) == 1


# ---- Loader Tests ----


class TestLoadSettings:
    """Tests for settings loading."""

    def test_load_valid_settings(self, workspace_dir: Path) -> None:
        settings = load_settings(workspace_dir)
        assert settings.active_profile == "test-profile"
        assert "openai" in settings.api_keys

    def test_load_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="not found"):
            load_settings(tmp_path)

    def test_save_and_reload(self, workspace_dir: Path) -> None:
        original = load_settings(workspace_dir)
        new_settings = original.model_copy(update={"log_level": "DEBUG"})
        save_settings(workspace_dir, new_settings)
        reloaded = load_settings(workspace_dir)
        assert reloaded.log_level == "DEBUG"


class TestLoadProfile:
    """Tests for profile loading."""

    def test_load_valid_profile(self, workspace_dir: Path) -> None:
        profile_dir = workspace_dir / "profiles" / "test-profile"
        profile = load_profile(profile_dir)
        assert profile.name == "test-profile"
        assert len(profile.agents) == 1

    def test_load_missing_profile(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileError, match="not found"):
            load_profile(tmp_path / "nonexistent")

    def test_load_active_profile(self, workspace_dir: Path) -> None:
        profile = load_active_profile(workspace_dir)
        assert profile.name == "test-profile"


class TestListProfiles:
    """Tests for profile listing."""

    def test_list_profiles(self, workspace_dir: Path) -> None:
        profiles = list_profiles(workspace_dir)
        assert "test-profile" in profiles

    def test_list_empty(self, tmp_path: Path) -> None:
        profiles = list_profiles(tmp_path)
        assert profiles == []


class TestConfigurationManager:
    """Tests for ConfigurationManager."""

    def test_load_and_get(self, workspace_dir: Path) -> None:
        mgr = ConfigurationManager(workspace_dir)
        mgr.load()
        assert mgr.get_settings().active_profile == "test-profile"
        assert mgr.get_profile().name == "test-profile"

    def test_get_before_load_raises(self, workspace_dir: Path) -> None:
        mgr = ConfigurationManager(workspace_dir)
        with pytest.raises(ConfigurationError, match="not loaded"):
            mgr.get_settings()
        with pytest.raises(ConfigurationError, match="not loaded"):
            mgr.get_profile()

    def test_switch_profile(self, workspace_dir: Path) -> None:
        # Create a second profile
        profile2_dir = workspace_dir / "profiles" / "profile-2"
        profile2_dir.mkdir(parents=True)
        agents_data = {
            "agents": [
                {
                    "id": "agent-2",
                    "name": "Agent 2",
                    "system_prompt": "test",
                    "phases": ["p1"],
                    "llm": {"provider": "openai", "model": "gpt-4o"},
                }
            ]
        }
        with open(profile2_dir / "agents.yaml", "w") as f:
            yaml.dump(agents_data, f)
        workflow_data = {
            "name": "workflow-2",
            "phases": [{"id": "p1", "name": "P1", "order": 1, "is_terminal": True}],
        }
        with open(profile2_dir / "workflow.yaml", "w") as f:
            yaml.dump(workflow_data, f)

        mgr = ConfigurationManager(workspace_dir)
        mgr.load()
        assert mgr.get_profile().name == "test-profile"

        new_profile = mgr.switch_profile("profile-2")
        assert new_profile.name == "profile-2"
        assert mgr.get_settings().active_profile == "profile-2"

    def test_switch_nonexistent_profile(self, workspace_dir: Path) -> None:
        mgr = ConfigurationManager(workspace_dir)
        mgr.load()
        with pytest.raises(ProfileError, match="not found"):
            mgr.switch_profile("nonexistent")

    def test_list_profiles(self, workspace_dir: Path) -> None:
        mgr = ConfigurationManager(workspace_dir)
        profiles = mgr.list_profiles()
        assert "test-profile" in profiles

    def test_reload(self, workspace_dir: Path) -> None:
        mgr = ConfigurationManager(workspace_dir)
        mgr.load()
        mgr.reload()
        assert mgr.get_settings() is not None


# ---- Validator Tests ----


class TestValidateAgentPhaseReferences:
    """Tests for agent-phase cross-reference validation."""

    def test_valid_references(self, sample_profile: ProfileConfig) -> None:
        result = validate_agent_phase_references(sample_profile)
        assert result.is_valid

    def test_agent_references_unknown_phase(self, sample_llm_config: LLMConfig) -> None:
        profile = ProfileConfig(
            name="test",
            agents=[
                AgentDefinition(
                    id="a1", name="A1", system_prompt="test",
                    phases=["nonexistent-phase"],
                    llm=sample_llm_config,
                ),
            ],
            workflow=WorkflowConfig(name="w"),
        )
        result = validate_agent_phase_references(profile)
        assert not result.is_valid
        assert "nonexistent-phase" in result.errors[0]

    def test_phase_references_unknown_agent(self) -> None:
        profile = ProfileConfig(
            name="test",
            workflow=WorkflowConfig(
                name="w",
                phases=[
                    WorkflowPhaseConfig(
                        id="p1", name="P1", order=1,
                        agents=["ghost-agent"], is_terminal=True,
                    ),
                ],
            ),
        )
        result = validate_agent_phase_references(profile)
        assert not result.is_valid
        assert "ghost-agent" in result.errors[0]


class TestValidatePhaseGraph:
    """Tests for phase graph validation."""

    def test_valid_graph(self, sample_workflow: WorkflowConfig) -> None:
        result = validate_phase_graph(sample_workflow)
        assert result.is_valid

    def test_no_terminal_phase(self) -> None:
        workflow = WorkflowConfig(
            name="w",
            phases=[
                WorkflowPhaseConfig(id="p1", name="P1", order=1, on_success="p2"),
                WorkflowPhaseConfig(id="p2", name="P2", order=2, on_success="p1"),
            ],
        )
        result = validate_phase_graph(workflow)
        assert not result.is_valid
        assert any("terminal" in e.lower() for e in result.errors)

    def test_broken_on_success_ref(self) -> None:
        workflow = WorkflowConfig(
            name="w",
            phases=[
                WorkflowPhaseConfig(
                    id="p1", name="P1", order=1, on_success="nonexistent",
                ),
                WorkflowPhaseConfig(id="p2", name="P2", order=2, is_terminal=True),
            ],
        )
        result = validate_phase_graph(workflow)
        assert not result.is_valid
        assert any("nonexistent" in e for e in result.errors)

    def test_empty_workflow(self) -> None:
        workflow = WorkflowConfig(name="empty")
        result = validate_phase_graph(workflow)
        assert result.is_valid  # No errors, just warnings
        assert len(result.warnings) > 0


class TestValidateLLMProviders:
    """Tests for LLM provider validation."""

    def test_valid_providers(
        self, sample_profile: ProfileConfig, sample_settings: SettingsConfig,
    ) -> None:
        result = validate_llm_providers(sample_profile, sample_settings)
        assert result.is_valid

    def test_missing_api_key(self, sample_profile: ProfileConfig) -> None:
        settings = SettingsConfig(active_profile="test")
        result = validate_llm_providers(sample_profile, settings)
        assert not result.is_valid
        assert any("API key" in e for e in result.errors)

    def test_ollama_no_key_needed(self) -> None:
        profile = ProfileConfig(
            name="test",
            agents=[
                AgentDefinition(
                    id="a1", name="A1", system_prompt="test", phases=["p1"],
                    llm=LLMConfig(provider="ollama", model="llama3"),
                ),
            ],
            workflow=WorkflowConfig(name="w"),
        )
        settings = SettingsConfig(active_profile="test")
        result = validate_llm_providers(profile, settings)
        assert result.is_valid

    def test_disabled_agent_skipped(self) -> None:
        profile = ProfileConfig(
            name="test",
            agents=[
                AgentDefinition(
                    id="a1", name="A1", system_prompt="test", phases=["p1"],
                    llm=LLMConfig(provider="openai", model="gpt-4o"),
                    enabled=False,
                ),
            ],
            workflow=WorkflowConfig(name="w"),
        )
        settings = SettingsConfig(active_profile="test")
        result = validate_llm_providers(profile, settings)
        assert result.is_valid


class TestValidateStatusTransitions:
    """Tests for status transition validation."""

    def test_valid_transitions(self, sample_workflow: WorkflowConfig) -> None:
        result = validate_status_transitions(sample_workflow)
        assert result.is_valid

    def test_invalid_transition_target(self) -> None:
        workflow = WorkflowConfig(
            name="w",
            statuses=[
                StatusConfig(
                    id="s1", name="S1", is_initial=True, transitions_to=["nonexistent"],
                ),
            ],
        )
        result = validate_status_transitions(workflow)
        assert not result.is_valid

    def test_no_initial_status(self) -> None:
        workflow = WorkflowConfig(
            name="w",
            statuses=[StatusConfig(id="s1", name="S1", is_terminal=True)],
        )
        result = validate_status_transitions(workflow)
        assert not result.is_valid


class TestValidateGovernance:
    """Tests for governance validation."""

    def test_valid_governance(self, sample_governance: GovernanceConfig) -> None:
        result = validate_governance(sample_governance)
        assert result.is_valid

    def test_invalid_policy_action(self) -> None:
        governance = GovernanceConfig(
            policies=[
                PolicyConfig(id="p1", name="P1", action="invalid_action"),
            ],
        )
        result = validate_governance(governance)
        assert not result.is_valid
        assert any("invalid_action" in e for e in result.errors)

    def test_threshold_ordering_warning(self) -> None:
        governance = GovernanceConfig(
            delegated_authority=DelegatedAuthorityConfig(
                auto_approve_threshold=0.3,
                review_threshold=0.5,
            ),
        )
        result = validate_governance(governance)
        assert len(result.warnings) > 0


class TestValidateProfile:
    """Tests for full profile validation."""

    def test_valid_profile(
        self, sample_profile: ProfileConfig, sample_settings: SettingsConfig,
    ) -> None:
        result = validate_profile(sample_profile, sample_settings)
        assert result.is_valid

    def test_without_settings(self, sample_profile: ProfileConfig) -> None:
        result = validate_profile(sample_profile)
        assert result.is_valid


# ---- Profile Template Tests ----


class TestBuiltInProfiles:
    """Test that built-in profile templates load and validate correctly."""

    @pytest.fixture
    def profiles_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent / "profiles"

    def test_content_moderation_loads(self, profiles_dir: Path) -> None:
        profile = load_profile(profiles_dir / "content-moderation")
        assert profile.name == "content-moderation"
        assert len(profile.agents) == 3
        assert len(profile.workflow.phases) == 4

    def test_content_moderation_validates(self, profiles_dir: Path) -> None:
        profile = load_profile(profiles_dir / "content-moderation")
        result = validate_profile(profile)
        assert result.is_valid, f"Validation errors: {result.errors}"

    def test_software_dev_loads(self, profiles_dir: Path) -> None:
        profile = load_profile(profiles_dir / "software-dev")
        assert profile.name == "software-dev"
        assert len(profile.agents) == 8
        assert len(profile.workflow.phases) == 9

    def test_software_dev_validates(self, profiles_dir: Path) -> None:
        profile = load_profile(profiles_dir / "software-dev")
        result = validate_profile(profile)
        assert result.is_valid, f"Validation errors: {result.errors}"
