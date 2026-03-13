"""Connector registry — thread-safe store for provider instances and configs."""

from __future__ import annotations

import logging
import threading
from typing import Protocol, runtime_checkable

from .models import (
    CapabilityType,
    ConnectorConfig,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorProviderDescriptor,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class ConnectorProviderProtocol(Protocol):
    """Structural protocol for connector providers.

    Implementors do not need to inherit — structural compatibility is sufficient.
    """

    async def execute(
        self,
        request: ConnectorInvocationRequest,
    ) -> ConnectorInvocationResult: ...

    def get_descriptor(self) -> ConnectorProviderDescriptor: ...


class ConnectorRegistry:
    """Thread-safe registry for connector providers and configuration.

    Manages provider instances and connector configs separately so
    that config can be loaded independently from runtime providers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._providers: dict[str, ConnectorProviderProtocol] = {}
        self._configs: dict[str, ConnectorConfig] = {}

    def register_provider(self, provider: ConnectorProviderProtocol) -> None:
        """Register a connector provider.

        Args:
            provider: Provider implementing ConnectorProviderProtocol.
        """
        descriptor = provider.get_descriptor()
        with self._lock:
            self._providers[descriptor.provider_id] = provider
        logger.info("Registered connector provider: %s", descriptor.provider_id)

    def unregister_provider(self, provider_id: str) -> None:
        """Remove a registered connector provider.

        Args:
            provider_id: ID of the provider to remove.
        """
        with self._lock:
            removed = self._providers.pop(provider_id, None)
        if removed:
            logger.info("Unregistered connector provider: %s", provider_id)

    def register_config(self, config: ConnectorConfig) -> None:
        """Register a connector configuration.

        Args:
            config: ConnectorConfig instance.
        """
        with self._lock:
            self._configs[config.connector_id] = config
        logger.debug("Registered connector config: %s", config.connector_id)

    def get_provider(self, provider_id: str) -> ConnectorProviderProtocol | None:
        """Look up a provider by ID.

        Args:
            provider_id: Provider identifier.

        Returns:
            Provider instance or None if not registered.
        """
        with self._lock:
            return self._providers.get(provider_id)

    def get_config(self, connector_id: str) -> ConnectorConfig | None:
        """Look up a connector config by ID.

        Args:
            connector_id: Connector identifier.

        Returns:
            ConnectorConfig or None if not registered.
        """
        with self._lock:
            return self._configs.get(connector_id)

    def list_providers(self) -> list[ConnectorProviderDescriptor]:
        """Return descriptors for all registered providers."""
        with self._lock:
            return [p.get_descriptor() for p in self._providers.values()]

    def list_configs(self) -> list[ConnectorConfig]:
        """Return all registered connector configurations."""
        with self._lock:
            return list(self._configs.values())

    def find_providers_for_capability(
        self, capability_type: CapabilityType
    ) -> list[ConnectorProviderProtocol]:
        """Find all enabled providers that support a given capability type.

        Args:
            capability_type: The capability type to search for.

        Returns:
            List of matching enabled provider instances.
        """
        with self._lock:
            return [
                p
                for p in self._providers.values()
                if capability_type in p.get_descriptor().capability_types
                and p.get_descriptor().enabled
            ]

    def find_provider_for_operation(
        self,
        capability_type: CapabilityType,
        operation: str,
        preferred_provider: str | None = None,
    ) -> ConnectorProviderProtocol | None:
        """Find the best provider for a specific capability type and operation.

        If preferred_provider is specified and it supports the capability, use it.
        Otherwise fall back to first provider that declares support for the operation.
        If no provider declares operations, fall back to first enabled provider for
        the capability.

        Args:
            capability_type: The capability type required.
            operation: The specific operation name.
            preferred_provider: Optional preferred provider ID.

        Returns:
            Provider instance or None if none available.
        """
        with self._lock:
            providers = [
                p
                for p in self._providers.values()
                if capability_type in p.get_descriptor().capability_types
                and p.get_descriptor().enabled
            ]
        if not providers:
            return None

        if preferred_provider:
            for p in providers:
                if p.get_descriptor().provider_id == preferred_provider:
                    return p

        # Prefer providers that explicitly declare the operation
        for p in providers:
            ops = [op.operation for op in p.get_descriptor().operations]
            if ops and operation in ops:
                return p

        # Fall back to first enabled provider
        return providers[0] if providers else None
