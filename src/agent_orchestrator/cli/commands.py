"""CLI commands for agent-orchestrator.

Entry point: python -m agent_orchestrator

Provides workspace management, profile switching, execution control,
and configuration import/export via Click commands.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
import yaml

from agent_orchestrator.configuration.agent_manager import AgentManager
from agent_orchestrator.configuration.loader import (
    ConfigurationManager,
    list_profiles,
    load_profile,
    save_settings,
)
from agent_orchestrator.configuration.models import SettingsConfig
from agent_orchestrator.configuration.validator import validate_profile
from agent_orchestrator.exceptions import AgentError, ConfigurationError, ProfileError

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE = Path(".")
BUILTIN_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "profiles"


def _setup_logging(level: str = "INFO") -> None:
    """Configure structured logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """agent-orchestrator — Generic agent orchestration & governance platform."""


@main.command()
@click.option(
    "--template", "-t",
    type=click.Choice(["content-moderation", "software-dev"]),
    default=None,
    help="Built-in profile template to initialize with.",
)
@click.argument("workspace", type=click.Path(), default=".")
def init(template: str | None, workspace: str) -> None:
    """Initialize a new workspace directory."""
    workspace_path = Path(workspace).resolve()
    _setup_logging()

    if (workspace_path / "settings.yaml").exists():
        click.echo(f"Workspace already initialized at {workspace_path}")
        sys.exit(1)

    # Create workspace structure
    workspace_path.mkdir(parents=True, exist_ok=True)
    (workspace_path / "profiles").mkdir(exist_ok=True)
    (workspace_path / ".state").mkdir(exist_ok=True)
    (workspace_path / ".history").mkdir(exist_ok=True)
    (workspace_path / ".audit").mkdir(exist_ok=True)

    # Copy template profile if specified
    profile_name = template or "default"
    if template and (BUILTIN_PROFILES_DIR / template).is_dir():
        import shutil
        target = workspace_path / "profiles" / template
        shutil.copytree(BUILTIN_PROFILES_DIR / template, target)
        click.echo(f"Copied '{template}' profile template.")
    else:
        # Create minimal default profile
        default_dir = workspace_path / "profiles" / "default"
        default_dir.mkdir(parents=True, exist_ok=True)
        _create_default_profile(default_dir)
        click.echo("Created default profile.")

    # Create settings
    settings = SettingsConfig(active_profile=profile_name)
    save_settings(workspace_path, settings)

    click.echo(f"Workspace initialized at {workspace_path}")
    click.echo(f"Active profile: {profile_name}")


def _create_default_profile(profile_dir: Path) -> None:
    """Create a minimal default profile."""
    agents = {
        "agents": [
            {
                "id": "default-agent",
                "name": "Default Agent",
                "system_prompt": "You are a helpful assistant.",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }
        ]
    }
    workflow = {
        "name": "default",
        "statuses": [
            {"id": "pending", "name": "Pending", "is_initial": True, "transitions_to": ["done"]},
            {"id": "done", "name": "Done", "is_terminal": True},
        ],
        "phases": [
            {"id": "process", "name": "Process", "order": 1, "agents": ["default-agent"], "on_success": "done"},
            {"id": "done", "name": "Done", "order": 2, "is_terminal": True},
        ],
    }
    governance = {
        "delegated_authority": {"auto_approve_threshold": 0.8, "review_threshold": 0.5, "abort_threshold": 0.2},
        "policies": [],
    }
    workitems = {"work_item_types": [{"id": "task", "name": "Task"}]}

    for filename, data in [
        ("agents.yaml", agents),
        ("workflow.yaml", workflow),
        ("governance.yaml", governance),
        ("workitems.yaml", workitems),
    ]:
        with open(profile_dir / filename, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)


@main.command()
@click.argument("workspace", type=click.Path(exists=True), default=".")
def validate(workspace: str) -> None:
    """Validate workspace configuration."""
    workspace_path = Path(workspace).resolve()
    _setup_logging()

    try:
        mgr = ConfigurationManager(workspace_path)
        mgr.load()
        result = validate_profile(mgr.get_profile(), mgr.get_settings())
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    if result.is_valid:
        click.echo("Configuration is valid.")
    else:
        click.echo("Validation errors:")
        for error in result.errors:
            click.echo(f"  - {error}")
        sys.exit(1)

    if result.warnings:
        click.echo("Warnings:")
        for warning in result.warnings:
            click.echo(f"  - {warning}")


# ---- Profile Commands ----


@main.group()
def profile() -> None:
    """Manage profiles."""


@profile.command("list")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def profile_list(workspace: str) -> None:
    """List available profiles."""
    workspace_path = Path(workspace).resolve()
    _setup_logging()

    try:
        mgr = ConfigurationManager(workspace_path)
        mgr.load()
        settings = mgr.get_settings()
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    profiles = list_profiles(workspace_path)
    if not profiles:
        click.echo("No profiles found.")
        return

    for name in profiles:
        marker = " (active)" if name == settings.active_profile else ""
        click.echo(f"  {name}{marker}")


@profile.command("switch")
@click.argument("name")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def profile_switch(name: str, workspace: str) -> None:
    """Switch active profile."""
    workspace_path = Path(workspace).resolve()
    _setup_logging()

    try:
        mgr = ConfigurationManager(workspace_path)
        mgr.load()
        mgr.switch_profile(name)
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(f"Switched to profile '{name}'")


@profile.command("export")
@click.option(
    "--component", "-c",
    type=click.Choice(["agents", "workflow", "governance", "workitems", "all"]),
    default="all",
    help="Which component to export.",
)
@click.option(
    "--format", "fmt",
    type=click.Choice(["yaml", "json"]),
    default="yaml",
    help="Output format.",
)
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file or directory path.")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def profile_export(component: str, fmt: str, output: str | None, workspace: str) -> None:
    """Export profile components to files for reuse as templates.

    Export a single component or all components from the active profile.
    Use this to create a starting point for a new domain.

    Examples:
        profile export --component workflow --format json -o my-workflow.json
        profile export --component all -o ./new-domain/
        profile export  # exports all as YAML to ./profile-export/
    """
    workspace_path = Path(workspace).resolve()
    _setup_logging()

    try:
        mgr = ConfigurationManager(workspace_path)
        mgr.load()
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        if component == "all":
            out_dir = Path(output).resolve() if output else Path("profile-export").resolve()
            created = mgr.export_profile_to_directory(out_dir, fmt=fmt)
            click.echo(f"Exported {len(created)} component(s) to {out_dir}/")
            for p in created:
                click.echo(f"  {p.name}")
        else:
            ext = ".json" if fmt == "json" else ".yaml"
            default_name = f"{component}{ext}"
            out_path = Path(output).resolve() if output else Path(default_name).resolve()
            mgr.export_profile_component(component, out_path)
            click.echo(f"Exported {component} to {out_path}")
    except ConfigurationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@profile.command("create")
@click.argument("name")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def profile_create(name: str, workspace: str) -> None:
    """Create a new empty profile."""
    workspace_path = Path(workspace).resolve()
    _setup_logging()

    profile_dir = workspace_path / "profiles" / name
    if profile_dir.exists():
        click.echo(f"Profile '{name}' already exists.", err=True)
        sys.exit(1)

    profile_dir.mkdir(parents=True)
    _create_default_profile(profile_dir)
    click.echo(f"Created profile '{name}'")


# ---- Execution Commands ----


@main.command()
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def start(workspace: str) -> None:
    """Start the orchestration engine (headless processing)."""
    import asyncio

    workspace_path = Path(workspace).resolve()
    _setup_logging()

    try:
        mgr = ConfigurationManager(workspace_path)
        mgr.load()
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    click.echo(f"Starting engine with profile '{mgr.get_profile().name}'...")

    from agent_orchestrator.core.engine import OrchestrationEngine
    from agent_orchestrator.core.event_bus import EventBus

    async def _run() -> None:
        event_bus = EventBus()
        engine = OrchestrationEngine(mgr, event_bus)
        try:
            await engine.start()
            click.echo("Engine running. Press Ctrl+C to stop.")
            while engine.state.value == "running":
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            click.echo("\nStopping engine...")
        finally:
            await engine.stop()
            click.echo("Engine stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


@main.command()
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
@click.option("--file", "-f", type=click.Path(exists=True), help="Work item YAML file")
@click.option("--title", "-t", type=str, help="Work item title (inline submission)")
@click.option("--type-id", type=str, default="task", help="Work item type ID")
@click.option("--priority", "-p", type=int, default=5, help="Priority (0=highest)")
def submit(workspace: str, file: str | None, title: str | None, type_id: str, priority: int) -> None:
    """Submit a work item for processing."""
    import uuid

    workspace_path = Path(workspace).resolve()
    _setup_logging()

    if file:
        with open(file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        work_title = data.get("title", Path(file).stem)
        work_data = data
    elif title:
        work_title = title
        work_data = {"title": title}
    else:
        click.echo("Provide --file or --title", err=True)
        sys.exit(1)

    work_id = f"work-{uuid.uuid4().hex[:8]}"

    try:
        mgr = ConfigurationManager(workspace_path)
        mgr.load()
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Configuration error: {e}", err=True)
        sys.exit(1)

    import asyncio

    from agent_orchestrator.core.engine import OrchestrationEngine
    from agent_orchestrator.core.event_bus import EventBus
    from agent_orchestrator.core.work_queue import WorkItem

    async def _submit() -> None:
        event_bus = EventBus()
        engine = OrchestrationEngine(mgr, event_bus)
        try:
            await engine.start()
            work_item = WorkItem(
                id=work_id,
                type_id=type_id,
                title=work_title,
                data=work_data,
                priority=priority,
            )
            await engine.submit_work(work_item)
            click.echo(f"Submitted work item: {work_id}")
            click.echo(f"  Title: {work_title}")
            click.echo(f"  Type: {type_id}")
            click.echo(f"  Priority: {priority}")
        finally:
            await engine.stop()

    try:
        asyncio.run(_submit())
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=8000, help="Bind port")
def serve(workspace: str, host: str, port: int) -> None:
    """Start the REST API server."""
    workspace_path = Path(workspace).resolve()
    _setup_logging()

    from agent_orchestrator.api.app import create_app
    from agent_orchestrator.core.engine import OrchestrationEngine

    try:
        mgr_serve = ConfigurationManager(workspace_path)
        mgr_serve.load()
        engine = OrchestrationEngine(mgr_serve)
    except Exception:
        engine = None

    app = create_app(workspace_path, engine=engine)
    click.echo(f"Starting API server on {host}:{port}")

    import uvicorn
    uvicorn.run(app, host=host, port=port)


@main.command("export")
@click.argument("workspace", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="workspace-export.zip")
def export_config(workspace: str, output: str) -> None:
    """Export workspace configuration as a zip bundle."""
    import zipfile

    workspace_path = Path(workspace).resolve()
    output_path = Path(output).resolve()
    _setup_logging()

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        settings_file = workspace_path / "settings.yaml"
        if settings_file.exists():
            zf.write(settings_file, "settings.yaml")

        profiles_dir = workspace_path / "profiles"
        if profiles_dir.is_dir():
            for file_path in profiles_dir.rglob("*.yaml"):
                arcname = file_path.relative_to(workspace_path)
                zf.write(file_path, str(arcname))

    click.echo(f"Exported workspace to {output_path}")


@main.command("import")
@click.argument("bundle", type=click.Path(exists=True))
@click.option("--workspace", "-w", type=click.Path(), default=".")
def import_config(bundle: str, workspace: str) -> None:
    """Import workspace configuration from a zip bundle."""
    import zipfile

    bundle_path = Path(bundle).resolve()
    workspace_path = Path(workspace).resolve()
    _setup_logging()

    workspace_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(bundle_path, "r") as zf:
        zf.extractall(workspace_path)

    click.echo(f"Imported configuration to {workspace_path}")


def _get_agent_manager(workspace: str) -> AgentManager:
    """Initialize ConfigurationManager and AgentManager for CLI commands.

    Args:
        workspace: Workspace directory path.

    Returns:
        Initialized AgentManager.
    """
    workspace_path = Path(workspace).resolve()
    _setup_logging()
    mgr = ConfigurationManager(workspace_path)
    mgr.load()
    return AgentManager(mgr)


# ---- Agent Commands ----


@main.group()
def agent() -> None:
    """Manage agent definitions."""


@agent.command("list")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def agent_list(workspace: str) -> None:
    """List all agents in the active profile."""
    try:
        am = _get_agent_manager(workspace)
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    agents = am.list_agents()
    if not agents:
        click.echo("No agents configured.")
        return

    for a in agents:
        status = "enabled" if a.enabled else "disabled"
        click.echo(
            f"  {a.id}: {a.name} [{a.llm.provider}/{a.llm.model}] "
            f"phases={','.join(a.phases)} ({status})"
        )


@agent.command("get")
@click.argument("agent_id")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def agent_get(agent_id: str, workspace: str) -> None:
    """Get details for a specific agent."""
    try:
        am = _get_agent_manager(workspace)
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    a = am.get_agent(agent_id)
    if a is None:
        click.echo(f"Agent '{agent_id}' not found.", err=True)
        sys.exit(1)

    click.echo(f"ID:            {a.id}")
    click.echo(f"Name:          {a.name}")
    click.echo(f"Description:   {a.description}")
    click.echo(f"Provider:      {a.llm.provider}")
    click.echo(f"Model:         {a.llm.model}")
    click.echo(f"Phases:        {', '.join(a.phases)}")
    click.echo(f"Concurrency:   {a.concurrency}")
    click.echo(f"Enabled:       {a.enabled}")
    click.echo(f"System Prompt: {a.system_prompt[:80]}...")


@agent.command("create")
@click.option("--id", "agent_id", required=True, help="Unique agent ID")
@click.option("--name", required=True, help="Display name")
@click.option("--system-prompt", required=True, help="Agent system prompt")
@click.option("--phases", required=True, help="Comma-separated phase IDs")
@click.option("--provider", default="openai", help="LLM provider")
@click.option("--model", "llm_model", default="gpt-4o", help="LLM model")
@click.option("--concurrency", default=1, type=int, help="Max concurrency")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def agent_create(
    agent_id: str,
    name: str,
    system_prompt: str,
    phases: str,
    provider: str,
    llm_model: str,
    concurrency: int,
    workspace: str,
) -> None:
    """Create a new agent definition."""
    try:
        am = _get_agent_manager(workspace)
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    agent_data = {
        "id": agent_id,
        "name": name,
        "system_prompt": system_prompt,
        "phases": [p.strip() for p in phases.split(",")],
        "llm": {"provider": provider, "model": llm_model},
        "concurrency": concurrency,
    }

    try:
        created = am.create_agent(agent_data)
        click.echo(f"Created agent '{created.id}'")
    except (AgentError, ConfigurationError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@agent.command("update")
@click.argument("agent_id")
@click.option("--name", default=None, help="New display name")
@click.option("--system-prompt", default=None, help="New system prompt")
@click.option("--phases", default=None, help="New comma-separated phase IDs")
@click.option("--concurrency", default=None, type=int, help="New concurrency")
@click.option("--enabled/--disabled", default=None, help="Enable/disable agent")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def agent_update(
    agent_id: str,
    name: str | None,
    system_prompt: str | None,
    phases: str | None,
    concurrency: int | None,
    enabled: bool | None,
    workspace: str,
) -> None:
    """Update an existing agent definition."""
    try:
        am = _get_agent_manager(workspace)
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    updates: dict[str, object] = {}
    if name is not None:
        updates["name"] = name
    if system_prompt is not None:
        updates["system_prompt"] = system_prompt
    if phases is not None:
        updates["phases"] = [p.strip() for p in phases.split(",")]
    if concurrency is not None:
        updates["concurrency"] = concurrency
    if enabled is not None:
        updates["enabled"] = enabled

    if not updates:
        click.echo("No update fields provided.", err=True)
        sys.exit(1)

    try:
        updated = am.update_agent(agent_id, updates)
        click.echo(f"Updated agent '{updated.id}'")
    except (AgentError, ConfigurationError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@agent.command("delete")
@click.argument("agent_id")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def agent_delete(agent_id: str, workspace: str) -> None:
    """Delete an agent definition."""
    try:
        am = _get_agent_manager(workspace)
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    deleted = am.delete_agent(agent_id)
    if deleted:
        click.echo(f"Deleted agent '{agent_id}'")
    else:
        click.echo(f"Agent '{agent_id}' not found.", err=True)
        sys.exit(1)


@agent.command("import")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def agent_import(file_path: str, workspace: str) -> None:
    """Import agent definitions from a JSON or YAML file."""
    try:
        am = _get_agent_manager(workspace)
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        imported = am.import_agents(Path(file_path).resolve())
        click.echo(f"Imported {len(imported)} agent(s)")
        for a in imported:
            click.echo(f"  {a.id}: {a.name}")
    except ConfigurationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@agent.command("export")
@click.option("--format", "fmt", type=click.Choice(["yaml", "json"]), default="yaml")
@click.option("--output", "-o", type=click.Path(), default="agents-export.yaml")
@click.option("--workspace", "-w", type=click.Path(exists=True), default=".")
def agent_export(fmt: str, output: str, workspace: str) -> None:
    """Export agent definitions to a file."""
    try:
        am = _get_agent_manager(workspace)
    except (ConfigurationError, ProfileError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Adjust extension to match format
    output_path = Path(output).resolve()
    if fmt == "json" and output_path.suffix != ".json":
        output_path = output_path.with_suffix(".json")
    elif fmt == "yaml" and output_path.suffix not in {".yaml", ".yml"}:
        output_path = output_path.with_suffix(".yaml")

    try:
        am.export_agents(output_path, fmt=fmt)
        click.echo(f"Exported agents to {output_path}")
    except ConfigurationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command("new-app")
@click.argument("name")
@click.option("--workspace", "-w", type=click.Path(), default=".")
@click.option("--with-hooks", is_flag=True, default=False, help="Generate a hooks skeleton")
def new_app(name: str, workspace: str, with_hooks: bool) -> None:
    """Scaffold a new app profile with starter configuration.

    Creates a complete profile directory with agents, workflow,
    governance, work items, app manifest, and test scaffolding.

    Example:
        agent-orchestrator new-app my-app --workspace workspace
    """
    workspace_path = Path(workspace).resolve()
    profile_dir = workspace_path / "profiles" / name
    _setup_logging()

    if profile_dir.exists():
        click.echo(f"Profile '{name}' already exists at {profile_dir}", err=True)
        sys.exit(1)

    profile_dir.mkdir(parents=True)

    # app.yaml
    app_manifest = {
        "name": name,
        "version": "0.1.0",
        "description": f"{name} app built on agent-orchestrator",
        "platform_version": "0.1.0",
        "requires": {"providers": ["openai"]},
        "produces": {"work_item_types": ["task"]},
        "hooks": {},
        "author": "",
    }

    # agents.yaml
    agents_data = {
        "agents": [
            {
                "id": f"{name}-agent",
                "name": f"{name.replace('-', ' ').title()} Agent",
                "system_prompt": "You are a helpful assistant.",
                "phases": ["process"],
                "llm": {"provider": "openai", "model": "gpt-4o"},
            }
        ]
    }

    # workflow.yaml
    workflow_data = {
        "name": name,
        "statuses": [
            {"id": "pending", "name": "Pending", "is_initial": True, "transitions_to": ["active"]},
            {"id": "active", "name": "Active", "transitions_to": ["done"]},
            {"id": "done", "name": "Done", "is_terminal": True},
        ],
        "phases": [
            {
                "id": "process",
                "name": "Process",
                "order": 1,
                "agents": [f"{name}-agent"],
                "on_success": "complete",
            },
            {"id": "complete", "name": "Complete", "order": 2, "is_terminal": True},
        ],
    }

    # governance.yaml
    governance_data = {
        "delegated_authority": {
            "auto_approve_threshold": 0.8,
            "review_threshold": 0.5,
            "abort_threshold": 0.2,
        },
        "policies": [],
    }

    # workitems.yaml
    workitems_data = {"work_item_types": [{"id": "task", "name": "Task"}]}

    # Write config files
    for filename, data in [
        ("app.yaml", app_manifest),
        ("agents.yaml", agents_data),
        ("workflow.yaml", workflow_data),
        ("governance.yaml", governance_data),
        ("workitems.yaml", workitems_data),
    ]:
        with open(profile_dir / filename, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # helpers/ directory
    helpers_dir = profile_dir / "helpers"
    helpers_dir.mkdir()
    (helpers_dir / "__init__.py").write_text(
        f'"""Domain helpers for {name}."""\n',
        encoding="utf-8",
    )

    if with_hooks:
        hooks_content = f'''"""Phase context hooks for {name}.

Register in app.yaml under hooks:
    process: "{name}.helpers.hooks:process_hook"
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def process_hook(work_item: Any, phase: Any) -> dict[str, Any]:
    """Inject custom context into the 'process' phase.

    Args:
        work_item: The current WorkItem being processed.
        phase: The WorkflowPhaseConfig for the current phase.

    Returns:
        Dict of extra context passed to the phase executor.
    """
    logger.info("process_hook called for work item %s", work_item.id)
    return {{}}\n'''
        (helpers_dir / "hooks.py").write_text(hooks_content, encoding="utf-8")
        # Update manifest to reference the hook
        app_manifest["hooks"] = {"process": f"{name}.helpers.hooks:process_hook"}
        with open(profile_dir / "app.yaml", "w", encoding="utf-8") as f:
            yaml.dump(app_manifest, f, default_flow_style=False, sort_keys=False)

    # tests/ directory
    tests_dir = profile_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")

    conftest_content = '''"""Test fixtures for app tests."""

from __future__ import annotations

from agent_orchestrator.testing import make_agent, make_profile, make_work_item
'''
    (tests_dir / "conftest.py").write_text(conftest_content, encoding="utf-8")

    test_example_content = f'''"""Example tests for {name}."""

from __future__ import annotations

from agent_orchestrator.testing import make_agent, make_profile, make_work_item


def test_create_work_item() -> None:
    """Verify work items can be created with defaults."""
    item = make_work_item(title="Sample task for {name}")
    assert item.title == "Sample task for {name}"
    assert item.status.value == "pending"


def test_create_profile() -> None:
    """Verify a profile can be built from test helpers."""
    agent = make_agent(id="{name}-agent", phases=["process"])
    profile = make_profile(name="{name}", agents=[agent])
    assert profile.name == "{name}"
    assert len(profile.agents) == 1
'''
    (tests_dir / "test_example.py").write_text(test_example_content, encoding="utf-8")

    click.echo(f"Created app '{name}' at {profile_dir}")
    click.echo("  Files:")
    for path in sorted(profile_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(profile_dir)
            click.echo(f"    {rel}")


if __name__ == "__main__":
    main()
