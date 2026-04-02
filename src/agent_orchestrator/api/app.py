"""FastAPI application factory for agent-orchestrator REST API.

Creates and configures the FastAPI application with all route groups.
Optionally wires AgentManager into app state for agent CRUD endpoints.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from agent_orchestrator.api.benchmark_routes import benchmark_router
from agent_orchestrator.api.bulk_import_routes import bulk_router
from agent_orchestrator.api.cost_routes import router as cost_router
from agent_orchestrator.api.dashboard_routes import dashboard_router
from agent_orchestrator.api.websocket_events import ws_manager
from agent_orchestrator.api.catalog_routes import catalog_router
from agent_orchestrator.api.eval_routes import eval_router
from agent_orchestrator.api.knowledge_routes import knowledge_router
from agent_orchestrator.api.ledger_routes import ledger_router
from agent_orchestrator.api.lineage_routes import lineage_router
from agent_orchestrator.api.simulation_routes import simulation_router
from agent_orchestrator.api.skillmap_routes import skillmap_router
from agent_orchestrator.api.routes import (
    agents_router,
    artifacts_router,
    audit_router,
    config_router,
    connectors_router,
    contracts_router,
    execution_router,
    gaps_router,
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

    # Store execution context if engine has one
    app.state.execution_context = getattr(engine, "context", None) if engine else None

    # Initialize contract registry (always available; domain modules register at startup)
    from agent_orchestrator.contracts import ContractRegistry
    app.state.contract_registry = ContractRegistry()

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
    app.include_router(connectors_router, prefix=API_PREFIX, tags=["connectors"])
    app.include_router(contracts_router, prefix=API_PREFIX, tags=["contracts"])
    app.include_router(artifacts_router, prefix=API_PREFIX, tags=["artifacts"])
    app.include_router(gaps_router, prefix=API_PREFIX, tags=["gaps"])
    app.include_router(knowledge_router, prefix=API_PREFIX, tags=["knowledge"])
    app.include_router(catalog_router, prefix=API_PREFIX, tags=["catalog"])
    app.include_router(ledger_router, prefix=API_PREFIX, tags=["ledger"])
    app.include_router(skillmap_router, prefix=API_PREFIX, tags=["skills"])
    app.include_router(simulation_router, prefix=API_PREFIX, tags=["simulation"])
    app.include_router(lineage_router, prefix=API_PREFIX, tags=["lineage"])
    app.include_router(benchmark_router, prefix=API_PREFIX, tags=["benchmarks"])
    app.include_router(eval_router, prefix=API_PREFIX, tags=["evals"])
    app.include_router(cost_router, prefix=API_PREFIX, tags=["cost"])
    app.include_router(dashboard_router, prefix=API_PREFIX, tags=["dashboard"])
    app.include_router(bulk_router, prefix=API_PREFIX, tags=["bulk"])

    # WebSocket endpoint for real-time event streaming
    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        await ws_manager.connect(websocket)
        try:
            while True:
                # Keep connection alive; receive optional client messages (ping/subscribe)
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    # Mount MCP server if engine has MCP config enabled
    _try_mount_mcp(app, engine)

    logger.info("API application created")
    return app


def _try_mount_mcp(app: FastAPI, engine: object | None) -> None:
    """Mount MCP ASGI app if MCP server is enabled in config.

    Args:
        app: FastAPI application to mount on.
        engine: Optional OrchestrationEngine instance.
    """
    if engine is None:
        return

    try:
        config_manager = getattr(engine, "_config", None)
        if config_manager is None:
            return

        profile = config_manager.get_profile()
        mcp_config = getattr(profile, "mcp", None)
        if mcp_config is None:
            return

        from agent_orchestrator.mcp.models import MCPProfileConfig
        if not isinstance(mcp_config, MCPProfileConfig):
            return

        server_config = mcp_config.server
        if not server_config.enabled:
            return

        from agent_orchestrator.mcp.server import create_mcp_asgi_app
        mcp_app = create_mcp_asgi_app(engine, server_config)
        app.mount(server_config.mount_path, mcp_app)
        logger.info("MCP server mounted at %s", server_config.mount_path)
    except ImportError:
        logger.debug("MCP package not installed — MCP server not mounted")
    except Exception:
        logger.warning("Failed to mount MCP server", exc_info=True)


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
