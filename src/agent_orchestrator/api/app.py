"""FastAPI application factory for agent-orchestrator REST API.

Creates and configures the FastAPI application with all route groups.
Optionally wires AgentManager into app state for agent CRUD endpoints.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from agent_orchestrator.api.routes import (
    agents_router,
    audit_router,
    config_router,
    execution_router,
    governance_router,
    health_router,
    metrics_router,
    workflow_router,
    workitems_router,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def create_app(
    workspace_dir: Path | None = None,
    agent_manager: object | None = None,
    engine: object | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        workspace_dir: Path to workspace directory.
        agent_manager: Optional AgentManager instance for agent CRUD.
            If not provided and workspace_dir is set, one will be created.
        engine: Optional OrchestrationEngine instance. If provided,
            the engine's agent_manager takes precedence.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="Agent Orchestrator",
        description="Generic agent orchestration & governance platform",
        version="0.1.0",
    )

    # Store workspace dir in app state for routes to access
    app.state.workspace_dir = workspace_dir

    # Wire engine into app state
    app.state.engine = engine

    # Wire up AgentManager and ConfigurationManager
    if agent_manager is not None:
        app.state.agent_manager = agent_manager
        app.state.config_manager = None
    elif workspace_dir is not None:
        _try_init_managers(app, workspace_dir)
    else:
        app.state.agent_manager = None
        app.state.config_manager = None

    # Register route groups
    app.include_router(health_router, prefix=API_PREFIX, tags=["health"])
    app.include_router(agents_router, prefix=API_PREFIX, tags=["agents"])
    app.include_router(workflow_router, prefix=API_PREFIX, tags=["workflow"])
    app.include_router(workitems_router, prefix=API_PREFIX, tags=["workitems"])
    app.include_router(governance_router, prefix=API_PREFIX, tags=["governance"])
    app.include_router(execution_router, prefix=API_PREFIX, tags=["execution"])
    app.include_router(metrics_router, prefix=API_PREFIX, tags=["metrics"])
    app.include_router(audit_router, prefix=API_PREFIX, tags=["audit"])
    app.include_router(config_router, prefix=API_PREFIX, tags=["config"])

    logger.info("API application created")
    return app


def _try_init_managers(app: FastAPI, workspace_dir: Path) -> None:
    """Try to initialize ConfigurationManager and AgentManager from workspace.

    Silently sets to None if workspace is not initialized.

    Args:
        app: FastAPI application.
        workspace_dir: Path to workspace directory.
    """
    settings_file = workspace_dir / "settings.yaml"
    if not settings_file.exists():
        app.state.agent_manager = None
        app.state.config_manager = None
        return

    try:
        from agent_orchestrator.configuration.agent_manager import AgentManager
        from agent_orchestrator.configuration.loader import ConfigurationManager
        from agent_orchestrator.core.engine import OrchestrationEngine

        config_mgr = ConfigurationManager(workspace_dir)
        config_mgr.load()
        app.state.config_manager = config_mgr

        # Create engine if not already provided
        if getattr(app.state, "engine", None) is None:
            engine = OrchestrationEngine(config_mgr)
            app.state.engine = engine

        # Use engine's agent_manager if available, else create standalone
        if app.state.engine is not None and app.state.engine.agent_manager is not None:
            app.state.agent_manager = app.state.engine.agent_manager
        else:
            app.state.agent_manager = AgentManager(config_mgr)

        logger.info("Managers initialized for workspace %s", workspace_dir)
    except Exception as e:
        logger.warning(
            "Could not initialize managers: %s", e, exc_info=True,
        )
        app.state.agent_manager = None
        app.state.config_manager = None
