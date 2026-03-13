"""Test helpers for apps built on agent-orchestrator.

Provides factory functions that create valid configuration objects
with sensible defaults, eliminating boilerplate in test suites.

Usage::

    from agent_orchestrator.testing import make_work_item, make_agent, make_profile

    def test_my_workflow():
        item = make_work_item(title="Review PR #42")
        agent = make_agent(phases=["review"])
        profile = make_profile(agents=[agent])
        ...
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import yaml

from agent_orchestrator.configuration.models import (
    AgentDefinition,
    DelegatedAuthorityConfig,
    GovernanceConfig,
    LLMConfig,
    PolicyConfig,
    ProfileConfig,
    RetryPolicy,
    SettingsConfig,
    StatusConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
    WorkItemTypeConfig,
)
from agent_orchestrator.core.work_queue import WorkItem, WorkItemStatus

logger = logging.getLogger(__name__)


def _uid(prefix: str = "") -> str:
    """Generate a short unique id."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def make_work_item(
    *,
    id: str | None = None,
    type_id: str = "task",
    title: str = "Test Work Item",
    data: dict[str, Any] | None = None,
    priority: int = 5,
    status: WorkItemStatus = WorkItemStatus.PENDING,
) -> WorkItem:
    """Create a WorkItem with sensible defaults.

    Args:
        id: Unique identifier. Auto-generated if omitted.
        type_id: Work item type id.
        title: Human-readable title.
        data: Arbitrary payload.
        priority: Queue priority (0=highest).
        status: Initial status.

    Returns:
        A WorkItem ready for submission.
    """
    return WorkItem(
        id=id or _uid("work-"),
        type_id=type_id,
        title=title,
        data=data or {},
        priority=priority,
        status=status,
    )


def make_agent(
    *,
    id: str | None = None,
    name: str = "Test Agent",
    provider: str = "openai",
    model: str = "gpt-4o",
    system_prompt: str = "You are a test agent.",
    phases: list[str] | None = None,
    skills: list[str] | None = None,
    concurrency: int = 1,
    temperature: float = 0.3,
    max_tokens: int = 4000,
    enabled: bool = True,
) -> AgentDefinition:
    """Create an AgentDefinition with sensible defaults.

    Args:
        id: Unique identifier. Auto-generated if omitted.
        name: Human-readable name.
        provider: LLM provider name.
        model: LLM model identifier.
        system_prompt: Agent instruction prompt.
        phases: Workflow phase IDs. Defaults to ``["phase-1"]``.
        skills: Capability tags.
        concurrency: Max concurrent executions.
        temperature: LLM temperature.
        max_tokens: LLM max tokens.
        enabled: Whether agent is enabled.

    Returns:
        A valid AgentDefinition.
    """
    return AgentDefinition(
        id=id or _uid("agent-"),
        name=name,
        system_prompt=system_prompt,
        phases=phases or ["phase-1"],
        skills=skills or [],
        llm=LLMConfig(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        concurrency=concurrency,
        enabled=enabled,
    )


def make_profile(
    *,
    name: str = "test-profile",
    description: str = "Test profile",
    agents: list[AgentDefinition] | None = None,
    workflow: WorkflowConfig | None = None,
    governance: GovernanceConfig | None = None,
    work_item_types: list[WorkItemTypeConfig] | None = None,
) -> ProfileConfig:
    """Create a complete ProfileConfig with sensible defaults.

    When ``agents`` and ``workflow`` are omitted, a consistent two-phase
    workflow with one agent is generated automatically.

    Args:
        name: Profile display name.
        description: Profile description.
        agents: Agent definitions. Defaults to one test agent.
        workflow: Workflow config. Defaults to a two-phase workflow.
        governance: Governance config. Defaults to standard thresholds.
        work_item_types: Work item type definitions. Defaults to one "task" type.

    Returns:
        A valid ProfileConfig.
    """
    default_agents = agents or [make_agent(id="test-agent", phases=["phase-1"])]

    default_workflow = workflow or WorkflowConfig(
        name="test-workflow",
        description="Default test workflow",
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

    default_governance = governance or GovernanceConfig(
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

    default_work_item_types = work_item_types or [
        WorkItemTypeConfig(id="task", name="Task"),
    ]

    return ProfileConfig(
        name=name,
        description=description,
        agents=default_agents,
        workflow=default_workflow,
        governance=default_governance,
        work_item_types=default_work_item_types,
    )


def make_workspace(
    tmp_path: Path,
    *,
    profile: ProfileConfig | None = None,
    settings: SettingsConfig | None = None,
) -> Path:
    """Create a temporary workspace directory on disk.

    Writes ``settings.yaml`` and a profile directory with all config files.
    Suitable for integration tests that exercise ``ConfigurationManager``.

    Args:
        tmp_path: Base temporary directory (e.g. from pytest's ``tmp_path``).
        profile: Profile to write. Defaults to :func:`make_profile` output.
        settings: Workspace settings. Defaults to matching the profile name.

    Returns:
        Path to the workspace root directory.
    """
    profile = profile or make_profile()
    settings = settings or SettingsConfig(
        active_profile=profile.name,
        api_keys={"openai": "sk-test-key"},
        log_level="DEBUG",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # Write settings
    with open(workspace / "settings.yaml", "w", encoding="utf-8") as f:
        yaml.dump(settings.model_dump(), f, default_flow_style=False, sort_keys=False)

    # Create profile directory
    profile_dir = workspace / "profiles" / profile.name
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Write agents
    agents_data = {"agents": [a.model_dump() for a in profile.agents]}
    with open(profile_dir / "agents.yaml", "w", encoding="utf-8") as f:
        yaml.dump(agents_data, f, default_flow_style=False, sort_keys=False)

    # Write workflow
    with open(profile_dir / "workflow.yaml", "w", encoding="utf-8") as f:
        yaml.dump(profile.workflow.model_dump(), f, default_flow_style=False, sort_keys=False)

    # Write governance
    with open(profile_dir / "governance.yaml", "w", encoding="utf-8") as f:
        yaml.dump(profile.governance.model_dump(), f, default_flow_style=False, sort_keys=False)

    # Write work item types
    workitems_data = {"work_item_types": [w.model_dump() for w in profile.work_item_types]}
    with open(profile_dir / "workitems.yaml", "w", encoding="utf-8") as f:
        yaml.dump(workitems_data, f, default_flow_style=False, sort_keys=False)

    return workspace


def mock_llm_fn(
    responses: list[str] | None = None,
) -> Callable[..., Coroutine[Any, Any, str]]:
    """Return a callable that yields canned LLM responses in order.

    When responses are exhausted, cycles back to the last response.

    Args:
        responses: List of response strings. Defaults to ``["OK"]``.

    Returns:
        An async callable matching the LLM call signature.
    """
    _responses = list(responses or ["OK"])
    _index = 0

    async def _mock_llm(*args: Any, **kwargs: Any) -> str:
        nonlocal _index
        result = _responses[min(_index, len(_responses) - 1)]
        _index += 1
        return result

    return _mock_llm
