"""ConnectorProviderDiscovery — automatic provider scanning and registration.

Discovers classes implementing ConnectorProviderProtocol from:
  1. The bundled connectors/providers package (builtin)
  2. External filesystem directories (plugin directories)
  3. Setuptools/importlib.metadata entry points

Faulty providers are logged and skipped — they never crash the platform.

Usage::

    discovery = ConnectorProviderDiscovery(registry)
    result = discovery.discover_builtin_providers()
    logger.info("Discovery: %s", result.summary())
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from .registry import ConnectorRegistry

logger = logging.getLogger(__name__)

_BUILTIN_PROVIDERS_PACKAGE = "agent_orchestrator.connectors.providers"


@dataclass
class ProviderLoadError:
    """Records a single provider load or registration failure."""

    module_path: str
    class_name: str
    error: str


@dataclass
class DiscoveryResult:
    """Summary of one provider discovery pass."""

    registered: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[ProviderLoadError] = field(default_factory=list)

    def summary(self) -> str:
        """Return a one-line human-readable summary."""
        return (
            f"registered={len(self.registered)} "
            f"skipped={len(self.skipped)} "
            f"errors={len(self.errors)}"
        )

    def as_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "registered": list(self.registered),
            "skipped": list(self.skipped),
            "errors": [
                {"module_path": e.module_path, "class_name": e.class_name, "error": e.error}
                for e in self.errors
            ],
        }


class ConnectorProviderDiscovery:
    """Discovers and auto-registers connector providers.

    Supports three discovery sources:

    * **Builtin** — scans ``agent_orchestrator.connectors.providers`` package recursively.
    * **Directory** — imports every non-underscore ``.py`` file from a path.
    * **Entry points** — loads classes registered under a setuptools entry-point group.

    Provider classes must implement ``ConnectorProviderProtocol``:
      - ``get_descriptor() -> ConnectorProviderDescriptor``
      - ``async execute(request) -> ConnectorInvocationResult``

    Auto-instantiation uses a ``from_env()`` classmethod if present.  If a
    class does not declare ``from_env()``, it is skipped (not an error).
    ``from_env()`` should return ``None`` when required credentials are absent
    and raise only on unexpected errors.

    All failures are isolated: a broken provider is logged and skipped while
    the platform continues running.

    Usage::

        discovery = ConnectorProviderDiscovery(registry)
        result = discovery.discover_builtin_providers()
        result2 = discovery.discover_directory(Path("/opt/connectors"))
    """

    def __init__(self, registry: ConnectorRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Public discovery methods
    # ------------------------------------------------------------------

    def discover_builtin_providers(self) -> DiscoveryResult:
        """Scan the bundled providers package and register discovered providers."""
        result = DiscoveryResult()
        try:
            package = importlib.import_module(_BUILTIN_PROVIDERS_PACKAGE)
        except ImportError as exc:
            logger.error("Cannot import builtin providers package: %s", exc)
            return result

        for module_info in pkgutil.walk_packages(
            package.__path__,
            prefix=f"{_BUILTIN_PROVIDERS_PACKAGE}.",
        ):
            last_segment = module_info.name.split(".")[-1]
            if last_segment.startswith("_"):
                continue  # skip _base.py, __init__.py
            self._process_module_path(module_info.name, result)

        logger.info("Builtin provider discovery: %s", result.summary())
        return result

    def discover_directory(self, directory: Path) -> DiscoveryResult:
        """Scan an external directory for provider modules."""
        result = DiscoveryResult()
        if not directory.is_dir():
            logger.warning("Provider discovery directory not found: %s", directory)
            return result

        for py_file in sorted(directory.rglob("*.py")):
            if py_file.name.startswith("_"):
                continue
            self._process_file(py_file, result)

        logger.info("Directory discovery (%s): %s", directory, result.summary())
        return result

    def discover_entry_points(
        self, group: str = "agent_orchestrator.connectors"
    ) -> DiscoveryResult:
        """Discover providers registered as importlib.metadata entry points."""
        result = DiscoveryResult()
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group=group)
        except Exception as exc:
            logger.debug("Entry-point discovery skipped: %s", exc)
            return result

        for ep in eps:
            try:
                cls = ep.load()
                self._try_register_class(cls, ep.value, result)
            except Exception as exc:
                result.errors.append(
                    ProviderLoadError(
                        module_path=ep.value, class_name=ep.name, error=str(exc)
                    )
                )
                logger.warning("Entry-point load error %r: %s", ep.name, exc)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_module_path(self, module_path: str, result: DiscoveryResult) -> None:
        """Import a dotted module path and scan it for provider classes."""
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            result.errors.append(
                ProviderLoadError(module_path=module_path, class_name="", error=str(exc))
            )
            logger.warning("Provider module import error %r: %s", module_path, exc)
            return
        self._scan_module(module, module_path, result)

    def _process_file(self, py_file: Path, result: DiscoveryResult) -> None:
        """Import a .py file as a dynamic module and scan it."""
        module_name = f"_ao_plugin_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as exc:
            result.errors.append(
                ProviderLoadError(module_path=str(py_file), class_name="", error=str(exc))
            )
            logger.warning("Plugin file import error %r: %s", py_file, exc)
            return
        self._scan_module(module, str(py_file), result)

    def _scan_module(
        self, module: ModuleType, source: str, result: DiscoveryResult
    ) -> None:
        """Find provider classes defined in a module and attempt registration."""
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue  # skip classes imported from other modules
            if not self._looks_like_provider(obj):
                continue
            self._try_register_class(obj, source, result)

    def _looks_like_provider(self, cls: type) -> bool:
        """Return True if cls appears to be a concrete provider implementation."""
        if inspect.isabstract(cls):
            return False
        has_execute = callable(getattr(cls, "execute", None))
        has_descriptor = callable(getattr(cls, "get_descriptor", None))
        return has_execute and has_descriptor

    def _try_register_class(
        self, cls: type, source: str, result: DiscoveryResult
    ) -> None:
        """Instantiate a provider class and register it, handling all failures."""
        class_name = cls.__name__
        try:
            instance = self._instantiate(cls)
        except ValueError as exc:
            # Missing credentials — intentional skip, not an error
            result.skipped.append(class_name)
            logger.debug("Provider %r skipped (missing credentials): %s", class_name, exc)
            return
        except Exception as exc:
            result.errors.append(
                ProviderLoadError(module_path=source, class_name=class_name, error=str(exc))
            )
            logger.warning(
                "Provider instantiation error %r (source=%s): %s", class_name, source, exc
            )
            return

        if instance is None:
            result.skipped.append(class_name)
            logger.debug(
                "Provider %r skipped (from_env() returned None or no from_env)",
                class_name,
            )
            return

        try:
            descriptor = instance.get_descriptor()  # type: ignore[union-attr]
            provider_id = descriptor.provider_id
            if self._registry.get_provider(provider_id) is not None:
                result.skipped.append(provider_id)
                logger.debug(
                    "Provider %r already registered, skipping auto-discovery", provider_id
                )
                return
            self._registry.register_provider(instance)  # type: ignore[arg-type]
            result.registered.append(provider_id)
            logger.info(
                "Auto-registered provider: %s (capability=%s, source=%s)",
                provider_id,
                [c.value for c in descriptor.capability_types],
                source,
            )
        except Exception as exc:
            result.errors.append(
                ProviderLoadError(module_path=source, class_name=class_name, error=str(exc))
            )
            logger.warning(
                "Provider registration error %r: %s", class_name, exc
            )

    def _instantiate(self, cls: type) -> Any:
        """Create a provider instance via from_env() or return None.

        Returns:
            A provider instance, or None if the provider cannot be configured.

        Raises:
            ValueError: If required credentials are missing (treated as skip).
            Exception: On unexpected instantiation failures (treated as error).
        """
        from_env = getattr(cls, "from_env", None)
        if callable(from_env):
            return from_env()
        # No from_env() — cannot auto-instantiate; skip silently
        return None


def make_lazy_provider(
    factory: Callable[[], Any],
    provider_id: str,
    display_name: str,
    capability_types: list,
    operations: list,
) -> "LazyConnectorProvider":
    """Create a lazy-initialised provider wrapper.

    The provider's factory is not called until the first ``execute()`` call.

    Args:
        factory: Zero-arg callable returning the real provider instance.
        provider_id: Provider ID for the descriptor hint.
        display_name: Human-readable name.
        capability_types: List of CapabilityType values.
        operations: List of ConnectorOperationDescriptor values.

    Returns:
        A LazyConnectorProvider wrapping the factory.
    """
    return LazyConnectorProvider(factory, provider_id, display_name, capability_types, operations)


class LazyConnectorProvider:
    """Defers provider instantiation until the first execute() call.

    Useful when credential resolution is slow (e.g., fetching from a secrets
    manager) or when providers should not initialize at platform startup.

    The get_descriptor() method returns a pre-built hint descriptor so the
    provider appears in discovery before it is initialised.

    Usage::

        provider = make_lazy_provider(
            factory=lambda: JiraTicketingProvider(
                base_url=os.environ["JIRA_BASE_URL"],
                api_token=os.environ["JIRA_API_TOKEN"],
            ),
            provider_id="ticketing.jira",
            display_name="Jira",
            capability_types=[CapabilityType.TICKETING],
            operations=_TICKETING_OPS,
        )
        registry.register_provider(provider)
    """

    def __init__(
        self,
        factory: Callable[[], Any],
        provider_id: str,
        display_name: str,
        capability_types: list,
        operations: list,
    ) -> None:
        from .models import ConnectorProviderDescriptor

        self._factory = factory
        self._provider_id = provider_id
        self._instance: Any = None
        self._init_error: Exception | None = None
        self._descriptor_hint = ConnectorProviderDescriptor(
            provider_id=provider_id,
            display_name=display_name,
            capability_types=capability_types,
            operations=operations,
            enabled=True,
        )

    def get_descriptor(self):
        """Return the real descriptor once initialised, else the hint."""
        if self._instance is not None:
            return self._instance.get_descriptor()
        return self._descriptor_hint

    async def execute(self, request):
        """Execute via the underlying provider, initialising on first call."""
        from .models import ConnectorInvocationResult, ConnectorStatus

        if self._instance is None and self._init_error is None:
            try:
                self._instance = self._factory()
            except Exception as exc:
                self._init_error = exc
                logger.error(
                    "Lazy provider %r failed to initialise: %s", self._provider_id, exc
                )

        if self._init_error is not None:
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self._provider_id,
                provider=self._provider_id,
                capability_type=request.capability_type,
                operation=request.operation,
                status=ConnectorStatus.UNAVAILABLE,
                error_message=f"Provider initialisation failed: {self._init_error}",
            )

        return await self._instance.execute(request)
