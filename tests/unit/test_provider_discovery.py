"""Tests for ConnectorProviderDiscovery — automatic provider scanning and registration."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_orchestrator.connectors import (
    CapabilityType,
    ConnectorRegistry,
    DiscoveryResult,
    LazyConnectorProvider,
    ProviderLoadError,
    make_lazy_provider,
)
from agent_orchestrator.connectors.discovery import ConnectorProviderDiscovery
from agent_orchestrator.connectors.models import (
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry() -> ConnectorRegistry:
    return ConnectorRegistry()


def _make_provider(
    provider_id: str = "test.provider",
    capability: CapabilityType = CapabilityType.SEARCH,
    enabled: bool = True,
    from_env_returns: object = "self",  # "self" = return instance, None = return None
):
    """Build a minimal fake provider class."""

    class _FakeProvider:
        _from_env_value = from_env_returns

        def __init__(self) -> None:
            pass

        def get_descriptor(self) -> ConnectorProviderDescriptor:
            return ConnectorProviderDescriptor(
                provider_id=provider_id,
                display_name=provider_id,
                capability_types=[capability],
                enabled=enabled,
                operations=[
                    ConnectorOperationDescriptor(
                        operation="query",
                        description="test",
                        capability_type=capability,
                        read_only=True,
                    )
                ],
            )

        async def execute(self, request: ConnectorInvocationRequest) -> ConnectorInvocationResult:
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=provider_id,
                provider=provider_id,
                capability_type=capability,
                operation=request.operation,
                status=ConnectorStatus.SUCCESS,
            )

        @classmethod
        def from_env(cls):
            v = cls._from_env_value
            if v == "self":
                return cls()
            return v  # None → skipped

    _FakeProvider.__name__ = provider_id.replace(".", "_")
    _FakeProvider.__qualname__ = _FakeProvider.__name__
    return _FakeProvider


def _inject_module(module_name: str, cls: type) -> types.ModuleType:
    """Create a fake module containing cls and inject it into sys.modules."""
    mod = types.ModuleType(module_name)
    mod.__name__ = module_name
    mod.__path__ = []  # type: ignore[attr-defined]
    mod.__package__ = module_name.rsplit(".", 1)[0] if "." in module_name else module_name
    cls.__module__ = module_name
    setattr(mod, cls.__name__, cls)
    sys.modules[module_name] = mod
    return mod


# ---------------------------------------------------------------------------
# DiscoveryResult
# ---------------------------------------------------------------------------

class TestDiscoveryResult:
    def test_summary_format(self) -> None:
        r = DiscoveryResult(
            registered=["a", "b"], skipped=["c"], errors=[ProviderLoadError("m", "C", "err")]
        )
        assert "registered=2" in r.summary()
        assert "skipped=1" in r.summary()
        assert "errors=1" in r.summary()

    def test_as_dict_structure(self) -> None:
        r = DiscoveryResult(
            registered=["x"],
            skipped=["y"],
            errors=[ProviderLoadError(module_path="m", class_name="C", error="boom")],
        )
        d = r.as_dict()
        assert d["registered"] == ["x"]
        assert d["skipped"] == ["y"]
        assert d["errors"][0]["error"] == "boom"

    def test_empty_result(self) -> None:
        r = DiscoveryResult()
        assert r.registered == []
        assert r.skipped == []
        assert r.errors == []


# ---------------------------------------------------------------------------
# ConnectorProviderDiscovery — _looks_like_provider
# ---------------------------------------------------------------------------

class TestLooksLikeProvider:
    def setup_method(self) -> None:
        self.discovery = ConnectorProviderDiscovery(_make_registry())

    def test_concrete_provider_accepted(self) -> None:
        cls = _make_provider()
        assert self.discovery._looks_like_provider(cls) is True

    def test_abstract_class_rejected(self) -> None:
        from abc import ABC, abstractmethod

        class AbstractProvider(ABC):
            @abstractmethod
            async def execute(self, req): ...

            @abstractmethod
            def get_descriptor(self): ...

        assert self.discovery._looks_like_provider(AbstractProvider) is False

    def test_missing_execute_rejected(self) -> None:
        class NoExecute:
            def get_descriptor(self): ...

        assert self.discovery._looks_like_provider(NoExecute) is False

    def test_missing_descriptor_rejected(self) -> None:
        class NoDescriptor:
            async def execute(self, req): ...

        assert self.discovery._looks_like_provider(NoDescriptor) is False

    def test_plain_class_rejected(self) -> None:
        class PlainClass:
            pass

        assert self.discovery._looks_like_provider(PlainClass) is False


# ---------------------------------------------------------------------------
# ConnectorProviderDiscovery — _instantiate
# ---------------------------------------------------------------------------

class TestInstantiate:
    def setup_method(self) -> None:
        self.discovery = ConnectorProviderDiscovery(_make_registry())

    def test_from_env_returns_instance(self) -> None:
        cls = _make_provider(from_env_returns="self")
        instance = self.discovery._instantiate(cls)
        assert instance is not None

    def test_from_env_returns_none(self) -> None:
        cls = _make_provider(from_env_returns=None)
        instance = self.discovery._instantiate(cls)
        assert instance is None

    def test_no_from_env_returns_none(self) -> None:
        class NoFromEnv:
            def get_descriptor(self): ...
            async def execute(self, req): ...

        result = self.discovery._instantiate(NoFromEnv)
        assert result is None


# ---------------------------------------------------------------------------
# ConnectorProviderDiscovery — _try_register_class
# ---------------------------------------------------------------------------

class TestTryRegisterClass:
    def setup_method(self) -> None:
        self.registry = _make_registry()
        self.discovery = ConnectorProviderDiscovery(self.registry)

    def test_successful_registration(self) -> None:
        cls = _make_provider("test.provider1")
        result = DiscoveryResult()
        self.discovery._try_register_class(cls, "test_source", result)
        assert "test.provider1" in result.registered
        assert self.registry.get_provider("test.provider1") is not None

    def test_from_env_returns_none_goes_to_skipped(self) -> None:
        cls = _make_provider("test.skipped", from_env_returns=None)
        result = DiscoveryResult()
        self.discovery._try_register_class(cls, "src", result)
        assert len(result.registered) == 0
        assert len(result.skipped) == 1

    def test_no_from_env_goes_to_skipped(self) -> None:
        class NoFromEnv:
            __name__ = "NoFromEnv"
            __module__ = "test"

            def get_descriptor(self):
                return MagicMock(provider_id="no.env")

            async def execute(self, req): ...

        result = DiscoveryResult()
        self.discovery._try_register_class(NoFromEnv, "src", result)
        assert len(result.skipped) == 1
        assert len(result.errors) == 0

    def test_already_registered_provider_goes_to_skipped(self) -> None:
        cls = _make_provider("test.dup")
        result1 = DiscoveryResult()
        self.discovery._try_register_class(cls, "src", result1)
        assert "test.dup" in result1.registered

        result2 = DiscoveryResult()
        self.discovery._try_register_class(cls, "src", result2)
        assert "test.dup" in result2.skipped

    def test_value_error_goes_to_skipped_not_errors(self) -> None:
        class BadCredentials:
            __name__ = "BadCredentials"

            @classmethod
            def from_env(cls):
                raise ValueError("Missing SOME_API_KEY")

            def get_descriptor(self): ...
            async def execute(self, req): ...

        result = DiscoveryResult()
        self.discovery._try_register_class(BadCredentials, "src", result)
        assert "BadCredentials" in result.skipped
        assert len(result.errors) == 0

    def test_unexpected_exception_goes_to_errors(self) -> None:
        class Exploder:
            __name__ = "Exploder"

            @classmethod
            def from_env(cls):
                raise RuntimeError("unexpected boom")

            def get_descriptor(self): ...
            async def execute(self, req): ...

        result = DiscoveryResult()
        self.discovery._try_register_class(Exploder, "src", result)
        assert len(result.errors) == 1
        assert "unexpected boom" in result.errors[0].error


# ---------------------------------------------------------------------------
# ConnectorProviderDiscovery — _scan_module
# ---------------------------------------------------------------------------

class TestScanModule:
    def setup_method(self) -> None:
        self.registry = _make_registry()
        self.discovery = ConnectorProviderDiscovery(self.registry)

    def test_skips_classes_from_other_modules(self) -> None:
        """Classes whose __module__ differs from the scanned module are skipped."""
        cls = _make_provider("foreign.provider")
        cls.__module__ = "some.other.module"

        mod = types.ModuleType("test_scan_module")
        mod.__name__ = "test_scan_module"
        setattr(mod, cls.__name__, cls)

        result = DiscoveryResult()
        self.discovery._scan_module(mod, "test_scan_module", result)
        assert len(result.registered) == 0

    def test_registers_classes_defined_in_module(self) -> None:
        cls = _make_provider("local.provider")
        mod_name = "test_local_module"
        _inject_module(mod_name, cls)

        mod = sys.modules[mod_name]
        result = DiscoveryResult()
        self.discovery._scan_module(mod, mod_name, result)
        assert "local.provider" in result.registered


# ---------------------------------------------------------------------------
# ConnectorProviderDiscovery — discover_directory
# ---------------------------------------------------------------------------

class TestDiscoverDirectory:
    def setup_method(self) -> None:
        self.registry = _make_registry()
        self.discovery = ConnectorProviderDiscovery(self.registry)

    def test_nonexistent_directory_returns_empty_result(self) -> None:
        result = self.discovery.discover_directory(Path("/nonexistent/path/xyz"))
        assert result.registered == []
        assert result.errors == []

    def test_discovers_provider_from_real_file(self, tmp_path: Path) -> None:
        """Write a provider .py file and verify it gets discovered."""
        plugin_code = """\
from agent_orchestrator.connectors.models import (
    CapabilityType, ConnectorInvocationRequest, ConnectorInvocationResult,
    ConnectorOperationDescriptor, ConnectorProviderDescriptor, ConnectorStatus,
)

class MyPluginProvider:
    @classmethod
    def from_env(cls):
        return cls()

    def get_descriptor(self):
        return ConnectorProviderDescriptor(
            provider_id="plugin.test",
            display_name="Plugin Test",
            capability_types=[CapabilityType.SEARCH],
            operations=[
                ConnectorOperationDescriptor(
                    operation="search",
                    description="search",
                    capability_type=CapabilityType.SEARCH,
                )
            ],
        )

    async def execute(self, request):
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id="plugin.test",
            provider="plugin.test",
            capability_type=request.capability_type,
            operation=request.operation,
            status=ConnectorStatus.SUCCESS,
        )
"""
        plugin_file = tmp_path / "my_plugin_provider.py"
        plugin_file.write_text(plugin_code)

        result = self.discovery.discover_directory(tmp_path)
        assert "plugin.test" in result.registered
        assert self.registry.get_provider("plugin.test") is not None

    def test_skips_underscore_files(self, tmp_path: Path) -> None:
        (tmp_path / "_private.py").write_text("class ShouldBeSkipped: pass\n")
        result = self.discovery.discover_directory(tmp_path)
        assert result.registered == []

    def test_faulty_file_goes_to_errors_not_crash(self, tmp_path: Path) -> None:
        (tmp_path / "broken.py").write_text("raise RuntimeError('import failed')\n")
        result = self.discovery.discover_directory(tmp_path)
        assert len(result.errors) == 1
        assert result.registered == []


# ---------------------------------------------------------------------------
# ConnectorProviderDiscovery — discover_builtin_providers
# ---------------------------------------------------------------------------

class TestDiscoverBuiltinProviders:
    def test_builtin_discovery_returns_discovery_result(self) -> None:
        """discover_builtin_providers() returns a DiscoveryResult (may have skipped)."""
        registry = _make_registry()
        discovery = ConnectorProviderDiscovery(registry)
        result = discovery.discover_builtin_providers()
        assert isinstance(result, DiscoveryResult)

    def test_builtin_discovery_no_crash_on_missing_credentials(self) -> None:
        """All built-in providers without env vars should land in skipped, not errors."""
        registry = _make_registry()
        discovery = ConnectorProviderDiscovery(registry)
        result = discovery.discover_builtin_providers()
        # Providers with from_env() returning None → skipped (credentials missing is normal)
        # Errors should only be unexpected failures
        for error in result.errors:
            assert "credentials" not in error.error.lower(), (
                f"Credential-related failure should be in skipped, not errors: {error}"
            )

    def test_builtin_providers_register_when_env_vars_set(self, monkeypatch) -> None:
        """With credentials set, builtin providers should auto-register."""
        monkeypatch.setenv("GITHUB_API_TOKEN", "ghp_fake_token_for_tests")
        registry = _make_registry()
        discovery = ConnectorProviderDiscovery(registry)
        result = discovery.discover_builtin_providers()
        assert "repository.github" in result.registered
        assert registry.get_provider("repository.github") is not None

    def test_builtin_providers_skipped_without_env_vars(self) -> None:
        """Without credentials, builtin providers land in skipped."""
        import os
        # Ensure no GitHub token is set
        original = os.environ.pop("GITHUB_API_TOKEN", None)
        try:
            registry = _make_registry()
            discovery = ConnectorProviderDiscovery(registry)
            result = discovery.discover_builtin_providers()
            # GitHubRepositoryProvider should be skipped (not an error)
            assert registry.get_provider("repository.github") is None
        finally:
            if original:
                os.environ["GITHUB_API_TOKEN"] = original

    def test_already_registered_providers_not_duplicated(self, monkeypatch) -> None:
        """Running discovery twice doesn't create duplicate registrations."""
        monkeypatch.setenv("BRAVE_API_KEY", "brave_test_key")
        registry = _make_registry()
        discovery = ConnectorProviderDiscovery(registry)
        result1 = discovery.discover_builtin_providers()
        result2 = discovery.discover_builtin_providers()
        # Second pass: brave provider already registered → goes to skipped
        all_registered = result1.registered + result2.registered
        assert all_registered.count("web_search.brave") == 1


# ---------------------------------------------------------------------------
# ConnectorProviderDiscovery — discover_entry_points
# ---------------------------------------------------------------------------

class TestDiscoverEntryPoints:
    def test_returns_empty_if_no_entry_points(self) -> None:
        registry = _make_registry()
        discovery = ConnectorProviderDiscovery(registry)
        # Group is unlikely to have real entries in test env
        result = discovery.discover_entry_points(group="agent_orchestrator.connectors.test_group")
        assert isinstance(result, DiscoveryResult)

    def test_entry_point_load_error_goes_to_errors(self) -> None:
        registry = _make_registry()
        discovery = ConnectorProviderDiscovery(registry)

        mock_ep = MagicMock()
        mock_ep.name = "bad_plugin"
        mock_ep.value = "some.module:SomeClass"
        mock_ep.load.side_effect = ImportError("module not found")

        with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
            result = discovery.discover_entry_points(group="agent_orchestrator.connectors")
        assert len(result.errors) == 1
        assert "module not found" in result.errors[0].error


# ---------------------------------------------------------------------------
# LazyConnectorProvider
# ---------------------------------------------------------------------------

class TestLazyConnectorProvider:
    def _descriptor(self, pid: str = "lazy.test") -> ConnectorProviderDescriptor:
        return ConnectorProviderDescriptor(
            provider_id=pid,
            display_name="Lazy Test",
            capability_types=[CapabilityType.SEARCH],
            operations=[],
        )

    def test_get_descriptor_returns_hint_before_init(self) -> None:
        calls = []
        def factory():
            calls.append(1)
            return MagicMock(get_descriptor=lambda: self._descriptor("factory.pid"))

        lazy = LazyConnectorProvider(
            factory=factory,
            provider_id="lazy.test",
            display_name="Lazy Test",
            capability_types=[CapabilityType.SEARCH],
            operations=[],
        )
        d = lazy.get_descriptor()
        assert d.provider_id == "lazy.test"
        assert calls == []  # factory not called yet

    @pytest.mark.asyncio
    async def test_execute_triggers_factory(self) -> None:
        inner = MagicMock()
        inner.execute = AsyncMock(
            return_value=ConnectorInvocationResult(
                request_id="r1",
                connector_id="lazy.test",
                provider="lazy.test",
                capability_type=CapabilityType.SEARCH,
                operation="query",
                status=ConnectorStatus.SUCCESS,
            )
        )
        calls = []

        def factory():
            calls.append(1)
            return inner

        lazy = LazyConnectorProvider(
            factory=factory,
            provider_id="lazy.test",
            display_name="Lazy Test",
            capability_types=[CapabilityType.SEARCH],
            operations=[],
        )
        req = ConnectorInvocationRequest(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
        )
        await lazy.execute(req)
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_factory_called_only_once(self) -> None:
        calls = []
        inner = MagicMock()
        inner.execute = AsyncMock(
            return_value=ConnectorInvocationResult(
                request_id="r1",
                connector_id="lazy.test",
                provider="lazy.test",
                capability_type=CapabilityType.SEARCH,
                operation="query",
                status=ConnectorStatus.SUCCESS,
            )
        )

        def factory():
            calls.append(1)
            return inner

        lazy = LazyConnectorProvider(
            factory=factory,
            provider_id="lazy.test",
            display_name="Lazy Test",
            capability_types=[CapabilityType.SEARCH],
            operations=[],
        )
        req = ConnectorInvocationRequest(
            capability_type=CapabilityType.SEARCH, operation="query", parameters={}
        )
        await lazy.execute(req)
        await lazy.execute(req)
        assert calls == [1]  # factory called only once

    @pytest.mark.asyncio
    async def test_factory_failure_returns_unavailable(self) -> None:
        def bad_factory():
            raise RuntimeError("cannot connect to secrets manager")

        lazy = LazyConnectorProvider(
            factory=bad_factory,
            provider_id="lazy.bad",
            display_name="Bad",
            capability_types=[CapabilityType.SEARCH],
            operations=[],
        )
        req = ConnectorInvocationRequest(
            capability_type=CapabilityType.SEARCH, operation="query", parameters={}
        )
        result = await lazy.execute(req)
        assert result.status == ConnectorStatus.UNAVAILABLE
        assert "cannot connect" in (result.error_message or "")

    def test_make_lazy_provider_helper(self) -> None:
        lazy = make_lazy_provider(
            factory=lambda: None,
            provider_id="helper.test",
            display_name="Helper Test",
            capability_types=[CapabilityType.SEARCH],
            operations=[],
        )
        assert isinstance(lazy, LazyConnectorProvider)
        assert lazy.get_descriptor().provider_id == "helper.test"


# ---------------------------------------------------------------------------
# Interface validation — from_env() on builtin providers
# ---------------------------------------------------------------------------

class TestBuiltinFromEnvMethods:
    """Verify that all builtin providers implement from_env() correctly."""

    @pytest.mark.parametrize("provider_class,env_vars", [
        (
            "agent_orchestrator.connectors.providers.web_search.tavily.TavilySearchProvider",
            {"TAVILY_API_KEY": "test_key"},
        ),
        (
            "agent_orchestrator.connectors.providers.web_search.serpapi.SerpAPISearchProvider",
            {"SERPAPI_API_KEY": "test_key"},
        ),
        (
            "agent_orchestrator.connectors.providers.web_search.brave.BraveSearchProvider",
            {"BRAVE_API_KEY": "test_key"},
        ),
        (
            "agent_orchestrator.connectors.providers.documents.confluence.ConfluenceDocumentsProvider",
            {"CONFLUENCE_BASE_URL": "https://example.atlassian.net", "CONFLUENCE_API_TOKEN": "tok"},
        ),
        (
            "agent_orchestrator.connectors.providers.messaging.slack.SlackMessagingProvider",
            {"SLACK_BOT_TOKEN": "xoxb-test"},
        ),
        (
            "agent_orchestrator.connectors.providers.messaging.teams.TeamsMessagingProvider",
            {"TEAMS_WEBHOOK_URL": "https://outlook.office.com/webhook/test"},
        ),
        (
            "agent_orchestrator.connectors.providers.ticketing.jira.JiraTicketingProvider",
            {"JIRA_BASE_URL": "https://test.atlassian.net", "JIRA_API_TOKEN": "tok"},
        ),
        (
            "agent_orchestrator.connectors.providers.ticketing.linear.LinearTicketingProvider",
            {"LINEAR_API_KEY": "lin_api_test"},
        ),
        (
            "agent_orchestrator.connectors.providers.repository.github.GitHubRepositoryProvider",
            {"GITHUB_API_TOKEN": "ghp_test"},
        ),
        (
            "agent_orchestrator.connectors.providers.repository.gitlab.GitLabRepositoryProvider",
            {"GITLAB_API_TOKEN": "glpat-test"},
        ),
    ])
    def test_from_env_returns_instance_with_credentials(
        self, provider_class: str, env_vars: dict, monkeypatch
    ) -> None:
        for k, v in env_vars.items():
            monkeypatch.setenv(k, v)
        module_path, class_name = provider_class.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        instance = cls.from_env()
        assert instance is not None, f"{class_name}.from_env() should return instance when credentials are set"

    @pytest.mark.parametrize("provider_class,required_env", [
        ("agent_orchestrator.connectors.providers.web_search.tavily.TavilySearchProvider", "TAVILY_API_KEY"),
        ("agent_orchestrator.connectors.providers.repository.github.GitHubRepositoryProvider", "GITHUB_API_TOKEN"),
        ("agent_orchestrator.connectors.providers.repository.gitlab.GitLabRepositoryProvider", "GITLAB_API_TOKEN"),
        ("agent_orchestrator.connectors.providers.ticketing.linear.LinearTicketingProvider", "LINEAR_API_KEY"),
        ("agent_orchestrator.connectors.providers.messaging.slack.SlackMessagingProvider", "SLACK_BOT_TOKEN"),
    ])
    def test_from_env_returns_none_without_credentials(
        self, provider_class: str, required_env: str, monkeypatch
    ) -> None:
        monkeypatch.delenv(required_env, raising=False)
        module_path, class_name = provider_class.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        instance = cls.from_env()
        assert instance is None, (
            f"{class_name}.from_env() should return None when {required_env!r} is not set"
        )

    @pytest.mark.parametrize("provider_class", [
        "agent_orchestrator.connectors.providers.messaging.email.EmailMessagingProvider",
    ])
    def test_email_from_env_returns_none_without_credentials(
        self, provider_class: str, monkeypatch
    ) -> None:
        for var in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_ADDRESS"):
            monkeypatch.delenv(var, raising=False)
        module_path, class_name = provider_class.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        assert cls.from_env() is None

    def test_email_from_env_returns_instance_with_all_required(self, monkeypatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
        monkeypatch.setenv("SMTP_USERNAME", "user@test.com")
        monkeypatch.setenv("SMTP_PASSWORD", "secret")
        monkeypatch.setenv("SMTP_FROM_ADDRESS", "from@test.com")
        from agent_orchestrator.connectors.providers.messaging.email import EmailMessagingProvider
        instance = EmailMessagingProvider.from_env()
        assert instance is not None

    def test_confluence_from_env_requires_both_url_and_token(self, monkeypatch) -> None:
        monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://example.atlassian.net")
        monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
        from agent_orchestrator.connectors.providers.documents.confluence import (
            ConfluenceDocumentsProvider,
        )
        assert ConfluenceDocumentsProvider.from_env() is None

    def test_jira_from_env_requires_both_url_and_token(self, monkeypatch) -> None:
        monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        from agent_orchestrator.connectors.providers.ticketing.jira import JiraTicketingProvider
        assert JiraTicketingProvider.from_env() is None


# ---------------------------------------------------------------------------
# ConnectorProviderDescriptor — configuration_schema field
# ---------------------------------------------------------------------------

class TestConfigurationSchemaField:
    def test_default_configuration_schema_is_empty_dict(self) -> None:
        d = ConnectorProviderDescriptor(
            provider_id="test",
            display_name="Test",
            capability_types=[CapabilityType.SEARCH],
        )
        assert d.configuration_schema == {}

    def test_configuration_schema_can_be_set(self) -> None:
        schema = {"SEARCH_API_KEY": {"type": "string", "required": True}}
        d = ConnectorProviderDescriptor(
            provider_id="test",
            display_name="Test",
            capability_types=[CapabilityType.SEARCH],
            configuration_schema=schema,
        )
        assert d.configuration_schema == schema
