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
    GovernanceConfig,
    LLMConfig,
    ProfileConfig,
    SettingsConfig,
    WorkflowConfig,
)
from agent_orchestrator.testing import (
    make_agent,
    make_profile,
    make_work_item,
    make_workspace,
)


@pytest.fixture
def sample_llm_config() -> LLMConfig:
    """Create a sample LLM configuration."""
    return LLMConfig(provider="openai", model="gpt-4o", temperature=0.3, max_tokens=4000)


@pytest.fixture
def sample_agent() -> AgentDefinition:
    """Create a sample agent definition."""
    return make_agent(
        id="test-agent",
        name="Test Agent",
        system_prompt="You are a test agent.",
        skills=["testing"],
        phases=["phase-1"],
    )


@pytest.fixture
def sample_workflow() -> WorkflowConfig:
    """Create a sample workflow with two phases."""
    profile = make_profile()
    return profile.workflow


@pytest.fixture
def sample_governance() -> GovernanceConfig:
    """Create a sample governance configuration."""
    profile = make_profile()
    return profile.governance


@pytest.fixture
def sample_profile(
    sample_agent: AgentDefinition,
    sample_workflow: WorkflowConfig,
    sample_governance: GovernanceConfig,
) -> ProfileConfig:
    """Create a complete sample profile."""
    return make_profile(
        agents=[sample_agent],
        workflow=sample_workflow,
        governance=sample_governance,
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
def workspace_dir(tmp_path: Path) -> Path:
    """Create a temporary workspace directory with settings and a profile."""
    return make_workspace(tmp_path)
