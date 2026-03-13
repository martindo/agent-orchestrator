"""Context helpers — create and transform ExecutionContext instances.

Pure functions, no shared state.
"""

from __future__ import annotations

import uuid

from agent_orchestrator.configuration.models import (
    DeploymentMode,
    ExecutionContext,
    SettingsConfig,
)


def create_root_context(
    settings: SettingsConfig,
    profile_name: str = "",
) -> ExecutionContext:
    """Build initial context from SettingsConfig + active profile.

    Args:
        settings: Workspace-level settings.
        profile_name: Active profile name (falls back to settings.active_profile).

    Returns:
        Root ExecutionContext for the engine lifetime.
    """
    return ExecutionContext(
        app_id="default",
        run_id="",
        tenant_id="default",
        environment="development",
        deployment_mode=DeploymentMode(settings.deployment_mode),
        profile_name=profile_name or settings.active_profile,
    )


def create_run_context(
    parent: ExecutionContext,
    run_id: str | None = None,
) -> ExecutionContext:
    """Create run-scoped child context with UUID run_id.

    Args:
        parent: The root or parent context.
        run_id: Explicit run ID, or auto-generated UUID.

    Returns:
        New ExecutionContext with a unique run_id.
    """
    return ExecutionContext(
        app_id=parent.app_id,
        run_id=run_id or uuid.uuid4().hex,
        tenant_id=parent.tenant_id,
        environment=parent.environment,
        deployment_mode=parent.deployment_mode,
        profile_name=parent.profile_name,
        extra=parent.extra,
    )


def context_tags(ctx: ExecutionContext) -> dict[str, str]:
    """Flat dict of context fields for metric tags / log extras.

    Args:
        ctx: The execution context.

    Returns:
        Dictionary suitable for structured logging or metric tagging.
    """
    return {
        "app_id": ctx.app_id,
        "run_id": ctx.run_id,
        "tenant_id": ctx.tenant_id,
        "environment": ctx.environment,
        "deployment_mode": ctx.deployment_mode.value,
        "profile_name": ctx.profile_name,
    }
