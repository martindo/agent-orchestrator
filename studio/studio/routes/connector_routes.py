"""Routes for connector discovery.

GET  /api/studio/connectors              — discover all connector providers
GET  /api/studio/connectors/capabilities — discover capability types
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from studio.connectors.discovery import (
    ConnectorInfo,
    discover_capabilities,
    discover_connectors,
)
from studio.config import StudioConfig
from studio.exceptions import ConnectorDiscoveryError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/connectors", tags=["connectors"])


def _get_config(request: Request) -> StudioConfig:
    """Get the Studio config from app state."""
    return request.app.state.studio_config  # type: ignore[attr-defined]


def _connector_to_dict(info: ConnectorInfo) -> dict[str, Any]:
    """Serialize a ConnectorInfo to a JSON-compatible dict."""
    return {
        "provider_id": info.provider_id,
        "display_name": info.display_name,
        "capability_types": info.capability_types,
        "operations": [
            {
                "operation": op.operation,
                "description": op.description,
                "capability_type": op.capability_type,
                "read_only": op.read_only,
                "required_parameters": op.required_parameters,
                "optional_parameters": op.optional_parameters,
            }
            for op in info.operations
        ],
        "enabled": info.enabled,
        "auth_required": info.auth_required,
        "auth_type": info.auth_type,
        "parameter_schemas": info.parameter_schemas,
    }


@router.get("", response_model=None)
def get_connectors(request: Request) -> dict[str, Any]:
    """Discover available connector providers from the runtime.

    Queries the running Agent-Orchestrator instance.
    Returns an error if the runtime is not reachable.
    """
    config = _get_config(request)
    try:
        connectors = discover_connectors(config)
        return {
            "providers": [_connector_to_dict(c) for c in connectors],
            "count": len(connectors),
            "runtime_url": config.runtime_api_url,
        }
    except ConnectorDiscoveryError as exc:
        logger.warning("Connector discovery failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/capabilities", response_model=None)
def get_capabilities(request: Request) -> dict[str, Any]:
    """Discover available capability types from the runtime."""
    config = _get_config(request)
    try:
        capabilities = discover_capabilities(config)
        return {
            "capabilities": capabilities,
            "count": len(capabilities),
        }
    except ConnectorDiscoveryError as exc:
        logger.warning("Capability discovery failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
