"""Plugin SDK for custom connectors, quality gates, and phase handlers."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class PluginMetadata:
    """Describes a registered plugin."""

    id: str
    name: str
    version: str
    author: str
    description: str
    plugin_type: str  # connector, quality_gate, phase_handler, hook
    entry_point: str  # module.path:ClassName


@dataclass
class PluginRegistry:
    """Central registry for discovering and loading plugins."""

    plugins: dict[str, PluginMetadata] = field(default_factory=dict)
    instances: dict[str, Any] = field(default_factory=dict)

    def register(self, metadata: PluginMetadata) -> bool:
        """Register a plugin. Returns False if already registered."""
        if metadata.id in self.plugins:
            logger.warning("Plugin %s already registered", metadata.id)
            return False
        self.plugins[metadata.id] = metadata
        logger.info("Plugin registered: %s (%s)", metadata.id, metadata.plugin_type)
        return True

    def unregister(self, plugin_id: str) -> bool:
        """Remove a plugin from the registry."""
        if plugin_id in self.plugins:
            del self.plugins[plugin_id]
            self.instances.pop(plugin_id, None)
            return True
        return False

    def load(self, plugin_id: str) -> Optional[Any]:
        """Dynamically load and instantiate a plugin by ID."""
        metadata = self.plugins.get(plugin_id)
        if not metadata:
            return None

        if plugin_id in self.instances:
            return self.instances[plugin_id]

        try:
            module_path, class_name = metadata.entry_point.rsplit(":", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            instance = cls()
            self.instances[plugin_id] = instance
            logger.info("Plugin loaded: %s", plugin_id)
            return instance
        except (ImportError, AttributeError, ValueError) as e:
            logger.error("Failed to load plugin %s: %s", plugin_id, e)
            return None

    def get_by_type(self, plugin_type: str) -> list[PluginMetadata]:
        """Return all plugins of a given type."""
        return [p for p in self.plugins.values() if p.plugin_type == plugin_type]

    def list_all(self) -> list[PluginMetadata]:
        """Return all registered plugins."""
        return list(self.plugins.values())


plugin_registry = PluginRegistry()

# Register built-in example plugins
plugin_registry.register(
    PluginMetadata(
        id="builtin-code-quality",
        name="Code Quality Gate",
        version="1.0.0",
        author="Agent Orchestrator",
        description="Built-in code quality review gate",
        plugin_type="quality_gate",
        entry_point="agent_orchestrator.governance.governor:GovernanceEngine",
    )
)
