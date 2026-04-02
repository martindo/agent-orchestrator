"""Plugin management routes for the Plugin SDK."""

from __future__ import annotations

from fastapi import APIRouter

from ..plugins.sdk import PluginMetadata, plugin_registry

router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.get("/")
async def list_plugins(plugin_type: str = "") -> dict:
    """List all plugins, optionally filtered by type."""
    if plugin_type:
        plugins = plugin_registry.get_by_type(plugin_type)
    else:
        plugins = plugin_registry.list_all()
    return {"data": [p.__dict__ for p in plugins], "total": len(plugins)}


@router.post("/register")
async def register_plugin(body: dict) -> dict:
    """Register a new plugin."""
    metadata = PluginMetadata(
        id=body.get("id", ""),
        name=body.get("name", ""),
        version=body.get("version", "1.0.0"),
        author=body.get("author", ""),
        description=body.get("description", ""),
        plugin_type=body.get("plugin_type", "connector"),
        entry_point=body.get("entry_point", ""),
    )
    success = plugin_registry.register(metadata)
    return {"success": success, "data": metadata.__dict__}


@router.post("/{plugin_id}/load")
async def load_plugin(plugin_id: str) -> dict:
    """Dynamically load a registered plugin."""
    instance = plugin_registry.load(plugin_id)
    return {"success": instance is not None, "loaded": plugin_id}


@router.delete("/{plugin_id}")
async def unregister_plugin(plugin_id: str) -> dict:
    """Remove a plugin from the registry."""
    success = plugin_registry.unregister(plugin_id)
    return {"success": success}
