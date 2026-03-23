"""Studio configuration loaded from environment variables or defaults.

Provides a single StudioConfig Pydantic model that every module reads from.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_STUDIO_PORT = 8004
DEFAULT_RUNTIME_URL = "http://localhost:8000"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"


class StudioConfig(BaseModel, frozen=True):
    """Immutable configuration for the Studio backend.

    Attributes:
        runtime_api_url: Base URL of the running Agent-Orchestrator API.
        workspace_dir: Absolute path to the orchestrator workspace root.
        profiles_dir: Directory inside the workspace that holds profile dirs.
        studio_port: Port the Studio FastAPI server listens on.
        frontend_origin: Allowed CORS origin for the React dev server.
        log_level: Python log level name.
    """

    runtime_api_url: str = DEFAULT_RUNTIME_URL
    workspace_dir: Path = Field(default_factory=lambda: Path.cwd())
    profiles_dir: Path | None = None
    studio_port: int = DEFAULT_STUDIO_PORT
    frontend_origin: str = DEFAULT_FRONTEND_ORIGIN
    log_level: str = "INFO"

    @property
    def resolved_profiles_dir(self) -> Path:
        """Return profiles_dir, falling back to workspace_dir / 'profiles'."""
        if self.profiles_dir is not None:
            return self.profiles_dir
        return self.workspace_dir / "profiles"


def load_config() -> StudioConfig:
    """Build a StudioConfig from environment variables.

    Environment variables (all optional):
        STUDIO_RUNTIME_URL      — runtime API base URL
        STUDIO_WORKSPACE_DIR    — workspace root path
        STUDIO_PROFILES_DIR     — profiles directory override
        STUDIO_PORT             — Studio server port
        STUDIO_FRONTEND_ORIGIN  — CORS origin for React dev server
        STUDIO_LOG_LEVEL        — Python log level name
    """
    values: dict[str, object] = {}

    if url := os.environ.get("STUDIO_RUNTIME_URL"):
        values["runtime_api_url"] = url
    if ws := os.environ.get("STUDIO_WORKSPACE_DIR"):
        values["workspace_dir"] = Path(ws)
    if pd := os.environ.get("STUDIO_PROFILES_DIR"):
        values["profiles_dir"] = Path(pd)
    if port := os.environ.get("STUDIO_PORT"):
        values["studio_port"] = int(port)
    if origin := os.environ.get("STUDIO_FRONTEND_ORIGIN"):
        values["frontend_origin"] = origin
    if level := os.environ.get("STUDIO_LOG_LEVEL"):
        values["log_level"] = level

    cfg = StudioConfig(**values)  # type: ignore[arg-type]
    logger.info(
        "Studio config loaded",
        extra={
            "runtime_api_url": cfg.runtime_api_url,
            "workspace_dir": str(cfg.workspace_dir),
            "studio_port": cfg.studio_port,
        },
    )
    return cfg
