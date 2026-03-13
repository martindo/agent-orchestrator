"""Tests for ConnectorGovernanceService and ConnectorService config-level access."""

from __future__ import annotations

import pytest

from agent_orchestrator.connectors import (
    CapabilityType,
    ConnectorConfig,
    ConnectorPermissionPolicy,
    ConnectorRegistry,
    ConnectorService,
    ConnectorStatus,
)
from agent_orchestrator.connectors.governance_service import (
    ConnectorDiscoveryItem,
    ConnectorGovernanceError,
    ConnectorGovernanceService,
    EffectivePermissions,
)
from agent_orchestrator.connectors.models import ConnectorProviderDescriptor, ConnectorOperationDescriptor
from agent_orchestrator.connectors.registry import ConnectorProviderProtocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    connector_id: str = "test.conn",
    provider_id: str = "test.provider",
    capability_type: CapabilityType = CapabilityType.SEARCH,
    enabled: bool = True,
    scoped_modules: list[str] | None = None,
    scoped_agent_roles: list[str] | None = None,
    policies: list[ConnectorPermissionPolicy] | None = None,
) -> ConnectorConfig:
    return ConnectorConfig(
        connector_id=connector_id,
        provider_id=provider_id,
        capability_type=capability_type,
        display_name="Test Connector",
        enabled=enabled,
        scoped_modules=scoped_modules or [],
        scoped_agent_roles=scoped_agent_roles or [],
        permission_policies=policies or [],
    )


def _make_registry_with_config(config: ConnectorConfig) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register_config(config)
    return registry


class _FakeProvider:
    """Minimal ConnectorProviderProtocol stub."""

    def __init__(self, provider_id: str, capability: CapabilityType, enabled: bool = True) -> None:
        self._provider_id = provider_id
        self._capability = capability
        self._enabled = enabled

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        return ConnectorProviderDescriptor(
            provider_id=self._provider_id,
            display_name=self._provider_id,
            capability_types=[self._capability],
            enabled=self._enabled,
            operations=[
                ConnectorOperationDescriptor(
                    operation="query",
                    description="Search query",
                    capability_type=self._capability,
                    read_only=True,
                ),
                ConnectorOperationDescriptor(
                    operation="write",
                    description="Write operation",
                    capability_type=self._capability,
                    read_only=False,
                ),
            ],
        )

    async def execute(self, request):  # type: ignore[override]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# ConnectorGovernanceService — enable / disable
# ---------------------------------------------------------------------------

class TestEnableDisable:
    def test_enable_sets_enabled_true(self) -> None:
        registry = _make_registry_with_config(_make_config(enabled=False))
        svc = ConnectorGovernanceService(registry)
        updated = svc.enable_connector("test.conn")
        assert updated.enabled is True

    def test_disable_sets_enabled_false(self) -> None:
        registry = _make_registry_with_config(_make_config(enabled=True))
        svc = ConnectorGovernanceService(registry)
        updated = svc.disable_connector("test.conn")
        assert updated.enabled is False

    def test_enable_re_registers_in_registry(self) -> None:
        registry = _make_registry_with_config(_make_config(enabled=False))
        svc = ConnectorGovernanceService(registry)
        svc.enable_connector("test.conn")
        assert registry.get_config("test.conn").enabled is True  # type: ignore[union-attr]

    def test_disable_re_registers_in_registry(self) -> None:
        registry = _make_registry_with_config(_make_config(enabled=True))
        svc = ConnectorGovernanceService(registry)
        svc.disable_connector("test.conn")
        assert registry.get_config("test.conn").enabled is False  # type: ignore[union-attr]

    def test_enable_unknown_connector_raises(self) -> None:
        svc = ConnectorGovernanceService(ConnectorRegistry())
        with pytest.raises(ConnectorGovernanceError, match="test.conn"):
            svc.enable_connector("test.conn")

    def test_disable_unknown_connector_raises(self) -> None:
        svc = ConnectorGovernanceService(ConnectorRegistry())
        with pytest.raises(ConnectorGovernanceError, match="test.conn"):
            svc.disable_connector("test.conn")

    def test_idempotent_enable(self) -> None:
        registry = _make_registry_with_config(_make_config(enabled=True))
        svc = ConnectorGovernanceService(registry)
        svc.enable_connector("test.conn")
        assert registry.get_config("test.conn").enabled is True  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# ConnectorGovernanceService — scoping
# ---------------------------------------------------------------------------

class TestScoping:
    def test_update_scoped_modules(self) -> None:
        registry = _make_registry_with_config(_make_config())
        svc = ConnectorGovernanceService(registry)
        updated = svc.update_scoping("test.conn", scoped_modules=["billing", "hr"])
        assert updated.scoped_modules == ["billing", "hr"]

    def test_update_scoped_agent_roles(self) -> None:
        registry = _make_registry_with_config(_make_config())
        svc = ConnectorGovernanceService(registry)
        updated = svc.update_scoping("test.conn", scoped_agent_roles=["analyst"])
        assert updated.scoped_agent_roles == ["analyst"]

    def test_update_both_fields(self) -> None:
        registry = _make_registry_with_config(_make_config())
        svc = ConnectorGovernanceService(registry)
        updated = svc.update_scoping("test.conn", scoped_modules=["m1"], scoped_agent_roles=["r1"])
        assert updated.scoped_modules == ["m1"]
        assert updated.scoped_agent_roles == ["r1"]

    def test_none_leaves_existing_unchanged(self) -> None:
        cfg = _make_config(scoped_modules=["original"])
        registry = _make_registry_with_config(cfg)
        svc = ConnectorGovernanceService(registry)
        updated = svc.update_scoping("test.conn", scoped_modules=None, scoped_agent_roles=["r1"])
        assert updated.scoped_modules == ["original"]

    def test_empty_list_clears_restriction(self) -> None:
        cfg = _make_config(scoped_modules=["billing"])
        registry = _make_registry_with_config(cfg)
        svc = ConnectorGovernanceService(registry)
        updated = svc.update_scoping("test.conn", scoped_modules=[])
        assert updated.scoped_modules == []

    def test_no_args_returns_unchanged_config(self) -> None:
        cfg = _make_config(scoped_modules=["x"])
        registry = _make_registry_with_config(cfg)
        svc = ConnectorGovernanceService(registry)
        returned = svc.update_scoping("test.conn")
        assert returned.scoped_modules == ["x"]

    def test_unknown_connector_raises(self) -> None:
        svc = ConnectorGovernanceService(ConnectorRegistry())
        with pytest.raises(ConnectorGovernanceError):
            svc.update_scoping("missing", scoped_modules=["a"])


# ---------------------------------------------------------------------------
# ConnectorGovernanceService — policy management
# ---------------------------------------------------------------------------

class TestPolicyManagement:
    def _policy(self, pid: str = "p1", **kwargs) -> ConnectorPermissionPolicy:
        kwargs.setdefault("description", "test policy")
        return ConnectorPermissionPolicy(policy_id=pid, **kwargs)

    def test_add_policy_appends(self) -> None:
        registry = _make_registry_with_config(_make_config())
        svc = ConnectorGovernanceService(registry)
        svc.add_policy("test.conn", self._policy("p1"))
        updated = svc.add_policy("test.conn", self._policy("p2"))
        assert [p.policy_id for p in updated.permission_policies] == ["p1", "p2"]

    def test_remove_policy_removes_by_id(self) -> None:
        cfg = _make_config(policies=[self._policy("p1"), self._policy("p2")])
        registry = _make_registry_with_config(cfg)
        svc = ConnectorGovernanceService(registry)
        updated = svc.remove_policy("test.conn", "p1")
        assert [p.policy_id for p in updated.permission_policies] == ["p2"]

    def test_remove_nonexistent_policy_raises(self) -> None:
        registry = _make_registry_with_config(_make_config())
        svc = ConnectorGovernanceService(registry)
        with pytest.raises(ConnectorGovernanceError, match="not found"):
            svc.remove_policy("test.conn", "nonexistent")

    def test_add_policy_to_unknown_connector_raises(self) -> None:
        svc = ConnectorGovernanceService(ConnectorRegistry())
        with pytest.raises(ConnectorGovernanceError):
            svc.add_policy("missing", self._policy())

    def test_remove_policy_from_unknown_connector_raises(self) -> None:
        svc = ConnectorGovernanceService(ConnectorRegistry())
        with pytest.raises(ConnectorGovernanceError):
            svc.remove_policy("missing", "p1")


# ---------------------------------------------------------------------------
# ConnectorGovernanceService — discovery
# ---------------------------------------------------------------------------

class TestDiscover:
    def _register(
        self,
        registry: ConnectorRegistry,
        connector_id: str,
        *,
        enabled: bool = True,
        scoped_modules: list[str] | None = None,
        scoped_agent_roles: list[str] | None = None,
    ) -> None:
        registry.register_config(_make_config(
            connector_id=connector_id,
            enabled=enabled,
            scoped_modules=scoped_modules,
            scoped_agent_roles=scoped_agent_roles,
        ))

    def test_discover_returns_enabled_connectors(self) -> None:
        registry = ConnectorRegistry()
        self._register(registry, "c1", enabled=True)
        self._register(registry, "c2", enabled=False)
        svc = ConnectorGovernanceService(registry)
        items = svc.discover()
        ids = [i.connector_id for i in items]
        assert "c1" in ids
        assert "c2" not in ids

    def test_discover_filters_by_module(self) -> None:
        registry = ConnectorRegistry()
        self._register(registry, "all", scoped_modules=[])
        self._register(registry, "billing-only", scoped_modules=["billing"])
        self._register(registry, "hr-only", scoped_modules=["hr"])
        svc = ConnectorGovernanceService(registry)
        items = svc.discover(module_name="billing")
        ids = [i.connector_id for i in items]
        assert "all" in ids
        assert "billing-only" in ids
        assert "hr-only" not in ids

    def test_discover_filters_by_role(self) -> None:
        registry = ConnectorRegistry()
        self._register(registry, "all", scoped_agent_roles=[])
        self._register(registry, "analyst-only", scoped_agent_roles=["analyst"])
        svc = ConnectorGovernanceService(registry)
        items = svc.discover(agent_role="analyst")
        ids = [i.connector_id for i in items]
        assert "all" in ids
        assert "analyst-only" in ids

    def test_discover_no_module_excludes_scoped(self) -> None:
        registry = ConnectorRegistry()
        self._register(registry, "billing-only", scoped_modules=["billing"])
        svc = ConnectorGovernanceService(registry)
        items = svc.discover(module_name=None)
        assert items == []

    def test_discover_empty_registry_returns_empty(self) -> None:
        svc = ConnectorGovernanceService(ConnectorRegistry())
        assert svc.discover() == []

    def test_discover_returns_discovery_items(self) -> None:
        registry = _make_registry_with_config(_make_config())
        svc = ConnectorGovernanceService(registry)
        items = svc.discover()
        assert len(items) == 1
        assert isinstance(items[0], ConnectorDiscoveryItem)

    def test_discover_item_as_dict(self) -> None:
        registry = _make_registry_with_config(_make_config())
        svc = ConnectorGovernanceService(registry)
        d = svc.discover()[0].as_dict()
        assert "connector_id" in d
        assert "provider_available" in d
        assert "available_operations" in d

    def test_discover_includes_provider_operations_when_registered(self) -> None:
        registry = _make_registry_with_config(_make_config(provider_id="test.provider"))
        provider = _FakeProvider("test.provider", CapabilityType.SEARCH)
        registry.register_provider(provider)  # type: ignore[arg-type]
        svc = ConnectorGovernanceService(registry)
        items = svc.discover()
        assert set(items[0].available_operations) == {"query", "write"}
        assert items[0].provider_available is True


# ---------------------------------------------------------------------------
# ConnectorGovernanceService — effective permissions
# ---------------------------------------------------------------------------

class TestEffectivePermissions:
    def test_all_operations_allowed_by_default(self) -> None:
        registry = _make_registry_with_config(_make_config(provider_id="test.provider"))
        provider = _FakeProvider("test.provider", CapabilityType.SEARCH)
        registry.register_provider(provider)  # type: ignore[arg-type]
        svc = ConnectorGovernanceService(registry)
        perms = svc.get_effective_permissions("test.conn")
        assert "query" in perms.allowed_operations
        assert "write" in perms.allowed_operations
        assert perms.denied_operations == []

    def test_denied_operation_appears_in_denied_list(self) -> None:
        policy = ConnectorPermissionPolicy(
            policy_id="p1",
            description="deny write",
            denied_operations=["write"],
        )
        cfg = _make_config(provider_id="test.provider", policies=[policy])
        registry = _make_registry_with_config(cfg)
        provider = _FakeProvider("test.provider", CapabilityType.SEARCH)
        registry.register_provider(provider)  # type: ignore[arg-type]
        svc = ConnectorGovernanceService(registry)
        perms = svc.get_effective_permissions("test.conn")
        assert "write" in perms.denied_operations
        assert "write" not in perms.allowed_operations

    def test_requires_approval_write_operation(self) -> None:
        policy = ConnectorPermissionPolicy(
            policy_id="p1", description="require approval", requires_approval=True
        )
        cfg = _make_config(provider_id="test.provider", policies=[policy])
        registry = _make_registry_with_config(cfg)
        provider = _FakeProvider("test.provider", CapabilityType.SEARCH)
        registry.register_provider(provider)  # type: ignore[arg-type]
        svc = ConnectorGovernanceService(registry)
        perms = svc.get_effective_permissions("test.conn")
        # write is not read-only, not a read prefix — should require approval
        assert "write" in perms.requires_approval_operations
        # query starts with a read-like prefix — bypasses approval
        assert "query" in perms.allowed_operations

    def test_effective_permissions_reflects_enabled_flag(self) -> None:
        registry = _make_registry_with_config(_make_config(enabled=False))
        svc = ConnectorGovernanceService(registry)
        perms = svc.get_effective_permissions("test.conn")
        assert perms.enabled is False

    def test_effective_permissions_unknown_connector_raises(self) -> None:
        svc = ConnectorGovernanceService(ConnectorRegistry())
        with pytest.raises(ConnectorGovernanceError):
            svc.get_effective_permissions("missing")

    def test_effective_permissions_as_dict(self) -> None:
        registry = _make_registry_with_config(_make_config())
        svc = ConnectorGovernanceService(registry)
        d = svc.get_effective_permissions("test.conn").as_dict()
        assert "connector_id" in d
        assert "allowed_operations" in d
        assert "denied_operations" in d
        assert "requires_approval_operations" in d


# ---------------------------------------------------------------------------
# ConnectorService — config-level access enforcement
# ---------------------------------------------------------------------------

class TestConnectorServiceConfigAccess:
    """Tests for the new _check_config_access() method in ConnectorService."""

    def _service(self, registry: ConnectorRegistry) -> ConnectorService:
        return ConnectorService(registry=registry)

    @pytest.mark.asyncio
    async def test_no_configs_registered_allows_execution(self) -> None:
        """When no ConnectorConfig is registered, access check passes through."""
        registry = ConnectorRegistry()
        svc = self._service(registry)
        # No provider either — expect UNAVAILABLE (from provider lookup), not PERMISSION_DENIED
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
        )
        assert result.status == ConnectorStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_disabled_connector_returns_unavailable(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(enabled=False))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
        )
        assert result.status == ConnectorStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_enabled_connector_proceeds(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(enabled=True))
        # No provider → UNAVAILABLE (not PERMISSION_DENIED, meaning access check passed)
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
        )
        assert result.status == ConnectorStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_module_scoping_blocks_wrong_module(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(scoped_modules=["billing"]))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
            context={"module_name": "hr"},
        )
        assert result.status == ConnectorStatus.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_module_scoping_allows_correct_module(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(scoped_modules=["billing"]))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
            context={"module_name": "billing"},
        )
        # Access check passed; no provider → UNAVAILABLE
        assert result.status == ConnectorStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_role_scoping_blocks_wrong_role(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(scoped_agent_roles=["analyst"]))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
            context={"agent_role": "reader"},
        )
        assert result.status == ConnectorStatus.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_role_scoping_allows_correct_role(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(scoped_agent_roles=["analyst"]))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
            context={"agent_role": "analyst"},
        )
        assert result.status == ConnectorStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_unscoped_connector_accessible_from_any_module(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(scoped_modules=[]))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
            context={"module_name": "anything"},
        )
        assert result.status == ConnectorStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_all_disabled_returns_unavailable_not_permission_denied(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(connector_id="c1", enabled=False))
        registry.register_config(_make_config(connector_id="c2", enabled=False))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
        )
        assert result.status == ConnectorStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_one_enabled_one_disabled_proceeds(self) -> None:
        registry = ConnectorRegistry()
        registry.register_config(_make_config(connector_id="c1", enabled=True))
        registry.register_config(_make_config(connector_id="c2", enabled=False))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={},
        )
        # Access check passes because at least one config is enabled
        assert result.status == ConnectorStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_permission_denied_policy_still_enforced(self) -> None:
        policy = ConnectorPermissionPolicy(
            policy_id="block-write",
            description="block write",
            denied_operations=["write"],
        )
        registry = ConnectorRegistry()
        registry.register_config(_make_config(policies=[policy]))
        svc = self._service(registry)
        result = await svc.execute(
            capability_type=CapabilityType.SEARCH,
            operation="write",
            parameters={},
        )
        assert result.status == ConnectorStatus.PERMISSION_DENIED
