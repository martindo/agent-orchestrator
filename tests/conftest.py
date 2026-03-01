"""Shared test fixtures for agent-orchestrator tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure src is on path
_src_dir = Path(__file__).resolve().parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    ConditionConfig,
    DelegatedAuthorityConfig,
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


@pytest.fixture
def sample_llm_config() -> LLMConfig:
    """Create a sample LLM configuration."""
    return LLMConfig(provider="openai", model="gpt-4o", temperature=0.3, max_tokens=4000)


@pytest.fixture
def sample_agent(sample_llm_config: LLMConfig) -> AgentDefinition:
    """Create a sample agent definition."""
    return AgentDefinition(
        id="test-agent",
        name="Test Agent",
        description="A test agent",
        system_prompt="You are a test agent.",
        skills=["testing"],
        phases=["phase-1"],
        llm=sample_llm_config,
    )


@pytest.fixture
def sample_workflow() -> WorkflowConfig:
    """Create a sample workflow with two phases."""
    return WorkflowConfig(
        name="test-workflow",
        description="A test workflow",
        statuses=[
            StatusConfig(id="pending", name="Pending", is_initial=True, transitions_to=["active"]),
            StatusConfig(id="active", name="Active", transitions_to=["done"]),
            StatusConfig(id="done", name="Done", is_terminal=True),
        ],
        phases=[
            WorkflowPhaseConfig(
                id="phase-1",
                name="Phase One",
                order=1,
                agents=["test-agent"],
                on_success="phase-2",
                on_failure="phase-2",
            ),
            WorkflowPhaseConfig(
                id="phase-2",
                name="Phase Two",
                order=2,
                agents=[],
                is_terminal=True,
            ),
        ],
    )


@pytest.fixture
def sample_governance() -> GovernanceConfig:
    """Create a sample governance configuration."""
    return GovernanceConfig(
        delegated_authority=DelegatedAuthorityConfig(
            auto_approve_threshold=0.8,
            review_threshold=0.5,
            abort_threshold=0.2,
        ),
        policies=[
            PolicyConfig(
                id="auto-approve",
                name="Auto Approve",
                action="allow",
                conditions=["confidence >= 0.8"],
                priority=100,
            ),
        ],
    )


@pytest.fixture
def sample_profile(
    sample_agent: AgentDefinition,
    sample_workflow: WorkflowConfig,
    sample_governance: GovernanceConfig,
) -> ProfileConfig:
    """Create a complete sample profile."""
    return ProfileConfig(
        name="test-profile",
        description="A test profile",
        agents=[sample_agent],
        workflow=sample_workflow,
        governance=sample_governance,
        work_item_types=[
            WorkItemTypeConfig(id="task", name="Task"),
        ],
    )


@pytest.fixture
def sample_settings() -> SettingsConfig:
    """Create sample workspace settings."""
    return SettingsConfig(
        active_profile="test-profile",
        api_keys={"openai": "sk-test-key"},
        log_level="DEBUG",
    )


@pytest.fixture
def workspace_dir(tmp_path: Path, sample_settings: SettingsConfig) -> Path:
    """Create a temporary workspace directory with settings and a profile."""
    import yaml

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Write settings
    settings_path = workspace / "settings.yaml"
    with open(settings_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_settings.model_dump(), f)

    # Create profile directory with minimal config
    profile_dir = workspace / "profiles" / "test-profile"
    profile_dir.mkdir(parents=True)

    agents_data = {
        "agents": [
            {
                "id": "test-agent",
                "name": "Test Agent",
                "system_prompt": "You are a test agent.",
                "phases": ["phase-1"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }
        ]
    }
    with open(profile_dir / "agents.yaml", "w", encoding="utf-8") as f:
        yaml.dump(agents_data, f)

    workflow_data = {
        "name": "test-workflow",
        "statuses": [
            {"id": "pending", "name": "Pending", "is_initial": True, "transitions_to": ["done"]},
            {"id": "done", "name": "Done", "is_terminal": True},
        ],
        "phases": [
            {
                "id": "phase-1",
                "name": "Phase One",
                "order": 1,
                "agents": ["test-agent"],
                "on_success": "done",
                "on_failure": "done",
            },
            {"id": "done", "name": "Done", "order": 2, "is_terminal": True},
        ],
    }
    with open(profile_dir / "workflow.yaml", "w", encoding="utf-8") as f:
        yaml.dump(workflow_data, f)

    governance_data = {
        "delegated_authority": {
            "auto_approve_threshold": 0.8,
            "review_threshold": 0.5,
            "abort_threshold": 0.2,
        },
        "policies": [
            {
                "id": "auto-approve",
                "name": "Auto Approve",
                "action": "allow",
                "conditions": ["confidence >= 0.8"],
                "priority": 100,
            }
        ],
    }
    with open(profile_dir / "governance.yaml", "w", encoding="utf-8") as f:
        yaml.dump(governance_data, f)

    workitems_data = {
        "work_item_types": [{"id": "task", "name": "Task"}]
    }
    with open(profile_dir / "workitems.yaml", "w", encoding="utf-8") as f:
        yaml.dump(workitems_data, f)

    return workspace
