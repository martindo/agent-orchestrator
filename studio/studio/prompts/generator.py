"""Generate coding-assistant prompt packs for extending agent profiles.

Produces task-scoped prompt files that can be used with Claude Code,
Cursor, or other AI coding assistants.  Each prompt pack gives the
assistant context about the profile structure and asks it to
implement a specific extension task.

Prompt types:
1. **Connector implementation** — fill in the stub for a connector provider.
2. **Event handler implementation** — implement event handling logic.
3. **Hook implementation** — implement phase context injection.
4. **Agent tuning** — improve system prompts and parameters.
5. **Quality gate tuning** — refine conditions and thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from studio.ir.models import TeamSpec

logger = logging.getLogger(__name__)


@dataclass
class PromptPack:
    """A collection of prompt files for coding assistants.

    Attributes:
        prompts: Mapping of filename → prompt content.
        written: Absolute paths of files written to disk.
    """

    prompts: dict[str, str] = field(default_factory=dict)
    written: list[Path] = field(default_factory=list)


def _profile_context(team: TeamSpec) -> str:
    """Build a context block describing the profile for prompts."""
    agents_list = "\n".join(
        f"  - {a.id}: {a.name} ({a.llm.provider}/{a.llm.model}) — {a.description}"
        for a in team.agents
    )
    phases_list = "\n".join(
        f"  - {p.id}: {p.name} (agents: {', '.join(p.agents)}) → on_success: {p.on_success}"
        for p in team.workflow.phases
    )
    policies_list = "\n".join(
        f"  - {p.id}: {p.name} (action: {p.action}, priority: {p.priority})"
        for p in team.governance.policies
    )

    return f"""## Profile: {team.name}

{team.description}

### Agents
{agents_list}

### Workflow Phases
{phases_list}

### Governance Policies
{policies_list}

### Work Item Types
{chr(10).join(f'  - {w.id}: {w.name}' for w in team.work_item_types)}
"""


def _connector_prompt(team: TeamSpec, provider_id: str, stub_path: str) -> str:
    """Generate a prompt for implementing a connector provider."""
    context = _profile_context(team)
    return f"""# Task: Implement Connector Provider '{provider_id}'

{context}

## Instructions

You are implementing a connector provider for the Agent-Orchestrator platform.
The stub file is at: `{stub_path}`

The connector must implement the `ConnectorProviderProtocol`:
- `get_descriptor()` → returns provider metadata (operations, capabilities)
- `execute(operation, parameters, context)` → executes an operation and returns results

### Requirements
1. Read the stub file and understand the TODO sections
2. Implement the `execute()` method with real API calls
3. Add proper error handling with specific exceptions
4. Use `logging.getLogger(__name__)` for all logging (never print)
5. Add type hints to all functions
6. Keep functions under 50 lines
7. Add authentication support if the external service requires it
8. Return structured results matching the expected format

### Testing
After implementing, create a test file that:
- Tests each operation with mocked HTTP responses
- Tests error handling for API failures
- Tests authentication flow
"""


def _event_handler_prompt(team: TeamSpec, handler_path: str) -> str:
    """Generate a prompt for implementing an event handler."""
    context = _profile_context(team)
    return f"""# Task: Implement Event Handler

{context}

## Instructions

You are implementing an event handler for the Agent-Orchestrator platform.
The stub file is at: `{handler_path}`

The handler subscribes to EventBus events and performs side-effects:
- `work_item.submitted` — triggered when new work enters the system
- `phase.completed` — triggered when a workflow phase finishes
- `workflow.completed` — triggered when the entire workflow is done

### Requirements
1. Read the stub file and understand the TODO sections
2. Implement the `handle()` method with your logic
3. Examples of what to implement:
   - Send Slack/email notifications on phase completion
   - Update external dashboards or metrics
   - Trigger downstream workflows
   - Log audit events to external systems
4. Use `logging.getLogger(__name__)` for all logging
5. Handle errors gracefully — event handlers should not crash the pipeline
6. Add type hints to all functions
"""


def _hook_prompt(team: TeamSpec, phase_id: str, hook_path: str) -> str:
    """Generate a prompt for implementing a phase context hook."""
    phase = next((p for p in team.workflow.phases if p.id == phase_id), None)
    phase_desc = f"'{phase.name}' ({phase.description})" if phase else f"'{phase_id}'"
    context = _profile_context(team)
    return f"""# Task: Implement Phase Context Hook for {phase_desc}

{context}

## Instructions

You are implementing a phase context hook for the Agent-Orchestrator platform.
The stub file is at: `{hook_path}`

This hook runs **before** agents execute in phase {phase_desc}.
It receives the execution context dict and can inject additional data.

### Requirements
1. Read the stub file and understand the TODO section
2. Implement the hook function to:
   - Load any external data the phase agents need
   - Inject results from previous phases
   - Add reference data or lookup tables
   - Set phase-specific configuration
3. Return the modified context dict
4. The function must be synchronous (not async)
5. Use `logging.getLogger(__name__)` for all logging
6. Handle errors — if data loading fails, log a warning and return
   context unmodified rather than crashing
"""


def _agent_tuning_prompt(team: TeamSpec) -> str:
    """Generate a prompt for tuning agent configurations."""
    context = _profile_context(team)
    return f"""# Task: Tune Agent Configurations

{context}

## Instructions

Review and improve the agent configurations in this profile.
The agent definitions are in `agents.yaml`.

### Areas to Evaluate
1. **System prompts** — Are they clear, specific, and well-structured?
   - Do they specify output format?
   - Do they include relevant context?
   - Are they appropriately detailed for the task?
2. **Model selection** — Is each agent using the right LLM?
   - High-precision tasks → higher-capability models (GPT-4o, Claude)
   - High-volume tasks → faster/cheaper models
3. **Temperature** — Is it appropriate?
   - Classification/analysis → low (0.1-0.3)
   - Creative/drafting → higher (0.5-0.8)
4. **Concurrency** — Is it set correctly?
   - Independent tasks → higher concurrency
   - Sequential/dependent → concurrency 1
5. **Skills** — Are the skill tags accurate and useful?

### Output
Provide specific changes to `agents.yaml` with explanations for each change.
"""


def _quality_gate_prompt(team: TeamSpec) -> str:
    """Generate a prompt for tuning quality gates."""
    context = _profile_context(team)
    gates_detail = ""
    for phase in team.workflow.phases:
        for gate in phase.quality_gates:
            conditions = ", ".join(c.expression for c in gate.conditions)
            gates_detail += (
                f"  - Phase '{phase.id}', Gate '{gate.name}': "
                f"conditions=[{conditions}], on_failure={gate.on_failure.value}\n"
            )

    return f"""# Task: Tune Quality Gates

{context}

## Current Quality Gates
{gates_detail or "  (none defined)"}

## Instructions

Review and improve the quality gate configurations.
Quality gates are in `workflow.yaml` under each phase's `quality_gates` section.

### Areas to Evaluate
1. **Condition thresholds** — Are they too strict or too lenient?
   - Too strict → legitimate work gets blocked
   - Too lenient → quality issues pass through
2. **Failure actions** — Is the right action configured?
   - `block` — stops the pipeline (use for critical checks)
   - `warn` — logs warning but continues (use for advisory checks)
   - `skip` — bypasses the gate entirely (use for optional checks)
3. **Missing gates** — Are there phases that should have quality gates?
4. **Condition expressions** — Are they testing the right variables?

### Output
Provide specific changes to `workflow.yaml` with explanations.
"""


def generate_prompt_pack(
    team: TeamSpec,
    output_dir: Path,
    *,
    include_connector: str | None = None,
) -> PromptPack:
    """Generate a complete prompt pack for a team profile.

    Args:
        team: Team specification.
        output_dir: Directory to write prompt files into.
        include_connector: Optional specific connector provider ID to include.

    Returns:
        PromptPack with all generated prompts.
    """
    pack = PromptPack()
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # Agent tuning prompt
    pack.prompts["tune-agents.md"] = _agent_tuning_prompt(team)

    # Quality gate tuning prompt
    pack.prompts["tune-quality-gates.md"] = _quality_gate_prompt(team)

    # Event handler prompt
    handler_path = "extensions/handlers/workflow_events.py"
    pack.prompts["implement-event-handler.md"] = _event_handler_prompt(team, handler_path)

    # Phase hook prompts
    for phase in team.workflow.phases:
        if phase.is_terminal or not phase.agents:
            continue
        hook_path = f"extensions/hooks/hook_{phase.id}.py"
        filename = f"implement-hook-{phase.id}.md"
        pack.prompts[filename] = _hook_prompt(team, phase.id, hook_path)

    # Connector prompt if requested
    if include_connector:
        stub_path = f"extensions/connectors/{include_connector}.py"
        pack.prompts[f"implement-connector-{include_connector}.md"] = (
            _connector_prompt(team, include_connector, stub_path)
        )

    # Write all prompts to disk
    for filename, content in pack.prompts.items():
        filepath = prompts_dir / filename
        try:
            filepath.write_text(content, encoding="utf-8")
            pack.written.append(filepath)
        except OSError as exc:
            logger.warning("Failed to write prompt %s: %s", filepath, exc, exc_info=True)

    logger.info("Generated %d prompt files in %s", len(pack.written), prompts_dir)
    return pack
