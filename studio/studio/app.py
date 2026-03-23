"""FastAPI application factory for Agent-Orchestrator Studio.

Creates a fully configured FastAPI app with all routes registered,
CORS configured for the React dev server, and shared state initialized.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from studio import __version__
from studio.config import StudioConfig, load_config

logger = logging.getLogger(__name__)


def create_app(config: StudioConfig | None = None) -> FastAPI:
    """Create and configure the Studio FastAPI application.

    Args:
        config: Studio configuration.  Loaded from environment if not provided.

    Returns:
        Fully configured FastAPI application with all routes registered.
    """
    if config is None:
        config = load_config()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    app = FastAPI(
        title="Agent-Orchestrator Studio",
        description=(
            "Visual design-time tool for creating and editing "
            "Agent-Orchestrator profiles."
        ),
        version=__version__,
    )

    # CORS — allow the React dev server and common local origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            config.frontend_origin,
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Shared state
    app.state.studio_config = config
    app.state.studio_state: dict[str, Any] = {
        "current_team": None,
    }

    # Register all route modules
    from studio.routes.schemas_routes import router as schemas_router
    from studio.routes.team_routes import router as team_router
    from studio.routes.generation_routes import router as generation_router
    from studio.routes.validation_routes import router as validation_router
    from studio.routes.graph_routes import router as graph_router
    from studio.routes.connector_routes import router as connector_router
    from studio.routes.template_routes import router as template_router
    from studio.routes.deploy_routes import router as deploy_router
    from studio.routes.condition_routes import router as condition_router
    from studio.routes.extension_routes import router as extension_router
    from studio.routes.prompt_routes import router as prompt_router
    from studio.routes.settings_routes import router as settings_router
    from studio.routes.recommend_routes import router as recommend_router

    app.include_router(schemas_router)
    app.include_router(team_router)
    app.include_router(generation_router)
    app.include_router(validation_router)
    app.include_router(graph_router)
    app.include_router(connector_router)
    app.include_router(template_router)
    app.include_router(deploy_router)
    app.include_router(condition_router)
    app.include_router(extension_router)
    app.include_router(prompt_router)
    app.include_router(settings_router)
    app.include_router(recommend_router)

    # Health check
    @app.get("/api/studio/health", tags=["health"])
    def health_check() -> dict[str, Any]:
        """Studio health check endpoint."""
        state = app.state.studio_state
        return {
            "status": "healthy",
            "version": __version__,
            "team_loaded": state.get("current_team") is not None,
            "team_name": (
                state["current_team"].name
                if state.get("current_team")
                else None
            ),
            "runtime_url": config.runtime_api_url,
            "workspace_dir": str(config.workspace_dir),
        }

    # Serve static frontend files if they exist
    static_dir = Path(__file__).parent.parent / "frontend" / "dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
        logger.info("Serving frontend from %s", static_dir)

    logger.info(
        "Studio app created (version %s, runtime=%s, workspace=%s)",
        __version__,
        config.runtime_api_url,
        config.workspace_dir,
    )
    return app
