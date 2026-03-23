"""CLI entry point for Agent-Orchestrator Studio.

Usage:
    studio serve [--port PORT] [--workspace DIR] [--runtime-url URL]
    studio import <template_path>
    studio export <output_dir>
    studio validate
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

logger = logging.getLogger(__name__)


@click.group()
@click.version_option(package_name="agent-orchestrator-studio")
def main() -> None:
    """Agent-Orchestrator Studio — visual profile builder."""


@main.command()
@click.option("--port", default=8001, help="Server port")
@click.option("--host", default="0.0.0.0", help="Server host")
@click.option("--workspace", type=click.Path(exists=True), default=".", help="Workspace directory")
@click.option("--runtime-url", default="http://localhost:8000", help="Runtime API URL")
@click.option("--log-level", default="INFO", help="Log level")
def serve(
    port: int,
    host: str,
    workspace: str,
    runtime_url: str,
    log_level: str,
) -> None:
    """Start the Studio server."""
    import uvicorn
    from studio.config import StudioConfig
    from studio.app import create_app

    config = StudioConfig(
        runtime_api_url=runtime_url,
        workspace_dir=Path(workspace).resolve(),
        studio_port=port,
        log_level=log_level,
    )

    app = create_app(config)
    logger.info("Starting Studio on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower())


@main.command("import")
@click.argument("template_path", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["json", "summary"]), default="summary")
def import_cmd(template_path: str, fmt: str) -> None:
    """Import a profile template and display it."""
    from studio.templates.manager import import_template

    team = import_template(Path(template_path))

    if fmt == "json":
        import json
        click.echo(json.dumps(team.model_dump(), indent=2))
    else:
        click.echo(f"Team: {team.name}")
        click.echo(f"Description: {team.description}")
        click.echo(f"Agents: {len(team.agents)}")
        for agent in team.agents:
            click.echo(f"  - {agent.id}: {agent.name} ({agent.llm.provider}/{agent.llm.model})")
        click.echo(f"Phases: {len(team.workflow.phases)}")
        for phase in team.workflow.phases:
            click.echo(f"  - {phase.id}: {phase.name} -> {phase.on_success}")
        click.echo(f"Policies: {len(team.governance.policies)}")
        click.echo(f"Work Item Types: {len(team.work_item_types)}")


@main.command("export")
@click.argument("output_dir", type=click.Path())
@click.option("--template", "template_path", type=click.Path(exists=True), required=True, help="Source template to export from")
def export_cmd(output_dir: str, template_path: str) -> None:
    """Export a profile template to YAML files."""
    from studio.templates.manager import import_template, export_template

    team = import_template(Path(template_path))
    files = export_template(team, Path(output_dir))
    click.echo(f"Exported {len(files)} files to {output_dir}:")
    for f in files:
        click.echo(f"  - {f.name}")


@main.command()
@click.argument("template_path", type=click.Path(exists=True))
def validate(template_path: str) -> None:
    """Validate a profile template."""
    from studio.templates.manager import import_template
    from studio.validation.validator import validate_team

    team = import_template(Path(template_path))
    result = validate_team(team)

    if result.is_valid:
        click.echo(click.style("VALID", fg="green", bold=True))
    else:
        click.echo(click.style("INVALID", fg="red", bold=True))

    if result.errors:
        click.echo(f"\nErrors ({len(result.errors)}):")
        for err in result.errors:
            click.echo(click.style(f"  ERROR: {err.message}", fg="red"))
            if err.path:
                click.echo(f"         at: {err.path}")

    if result.warnings:
        click.echo(f"\nWarnings ({len(result.warnings)}):")
        for warn in result.warnings:
            click.echo(click.style(f"  WARN: {warn.message}", fg="yellow"))
            if warn.path:
                click.echo(f"        at: {warn.path}")

    sys.exit(0 if result.is_valid else 1)


if __name__ == "__main__":
    main()
