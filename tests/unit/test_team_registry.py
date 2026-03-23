"""Tests for TeamRegistry — CRUD, find, summary."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_orchestrator.catalog.models import (
    CapabilityRegistration,
    InvocationMode,
    MemoryUsagePolicy,
    SecurityClassification,
)
from agent_orchestrator.catalog.registry import TeamRegistry
from agent_orchestrator.contracts.models import LifecycleState


def _make_reg(
    capability_id: str = "test.v1",
    *,
    profile_name: str = "test-profile",
    tags: list[str] | None = None,
    status: LifecycleState = LifecycleState.ACTIVE,
) -> CapabilityRegistration:
    """Create a test registration with minimal required fields."""
    now = datetime.now(timezone.utc)
    return CapabilityRegistration(
        capability_id=capability_id,
        display_name=capability_id,
        profile_name=profile_name,
        tags=tags or [],
        status=status,
        registered_at=now,
        updated_at=now,
    )


class TestTeamRegistryRegister:
    """Test register and get operations."""

    def test_register_and_get(self) -> None:
        registry = TeamRegistry()
        reg = _make_reg("cap.v1")
        registry.register(reg)
        result = registry.get("cap.v1")
        assert result is not None
        assert result.capability_id == "cap.v1"

    def test_register_upsert(self) -> None:
        registry = TeamRegistry()
        reg1 = _make_reg("cap.v1", profile_name="old")
        reg2 = _make_reg("cap.v1", profile_name="new")
        registry.register(reg1)
        registry.register(reg2)
        result = registry.get("cap.v1")
        assert result is not None
        assert result.profile_name == "new"

    def test_get_nonexistent(self) -> None:
        registry = TeamRegistry()
        assert registry.get("nonexistent") is None


class TestTeamRegistryFind:
    """Test find with various filters."""

    def setup_method(self) -> None:
        self.registry = TeamRegistry()
        self.registry.register(_make_reg("a.v1", tags=["research", "ml"], status=LifecycleState.ACTIVE))
        self.registry.register(_make_reg("b.v1", tags=["research"], status=LifecycleState.DRAFT))
        self.registry.register(_make_reg("c.v1", tags=["ml"], profile_name="other", status=LifecycleState.ACTIVE))

    def test_find_by_tags(self) -> None:
        results = self.registry.find(tags=["research"])
        assert len(results) == 2
        ids = {r.capability_id for r in results}
        assert ids == {"a.v1", "b.v1"}

    def test_find_by_multiple_tags(self) -> None:
        results = self.registry.find(tags=["research", "ml"])
        assert len(results) == 1
        assert results[0].capability_id == "a.v1"

    def test_find_by_status(self) -> None:
        results = self.registry.find(status=LifecycleState.DRAFT)
        assert len(results) == 1
        assert results[0].capability_id == "b.v1"

    def test_find_by_profile_name(self) -> None:
        results = self.registry.find(profile_name="other")
        assert len(results) == 1
        assert results[0].capability_id == "c.v1"

    def test_find_combined_filters(self) -> None:
        results = self.registry.find(tags=["ml"], status=LifecycleState.ACTIVE)
        assert len(results) == 2
        ids = {r.capability_id for r in results}
        assert ids == {"a.v1", "c.v1"}

    def test_find_no_match(self) -> None:
        results = self.registry.find(tags=["nonexistent"])
        assert results == []

    def test_find_no_filters_returns_all(self) -> None:
        results = self.registry.find()
        assert len(results) == 3


class TestTeamRegistryListAll:
    """Test list_all operation."""

    def test_list_all_empty(self) -> None:
        registry = TeamRegistry()
        assert registry.list_all() == []

    def test_list_all(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("a.v1"))
        registry.register(_make_reg("b.v1"))
        assert len(registry.list_all()) == 2


class TestTeamRegistryUnregister:
    """Test unregister operation."""

    def test_unregister_existing(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("cap.v1"))
        assert registry.unregister("cap.v1") is True
        assert registry.get("cap.v1") is None

    def test_unregister_nonexistent(self) -> None:
        registry = TeamRegistry()
        assert registry.unregister("nonexistent") is False


class TestTeamRegistrySummary:
    """Test summary operation."""

    def test_summary_empty(self) -> None:
        registry = TeamRegistry()
        summary = registry.summary()
        assert summary["total"] == 0
        assert summary["capability_ids"] == []
        assert summary["by_status"] == {}

    def test_summary_with_data(self) -> None:
        registry = TeamRegistry()
        registry.register(_make_reg("a.v1", status=LifecycleState.ACTIVE))
        registry.register(_make_reg("b.v1", status=LifecycleState.ACTIVE))
        registry.register(_make_reg("c.v1", status=LifecycleState.DRAFT))
        summary = registry.summary()
        assert summary["total"] == 3
        assert set(summary["capability_ids"]) == {"a.v1", "b.v1", "c.v1"}
        assert summary["by_status"]["active"] == 2
        assert summary["by_status"]["draft"] == 1


class TestCapabilityRegistrationModel:
    """Test the CapabilityRegistration model itself."""

    def test_frozen(self) -> None:
        reg = _make_reg("cap.v1")
        with pytest.raises(Exception):
            reg.capability_id = "changed"  # type: ignore[misc]

    def test_defaults(self) -> None:
        now = datetime.now(timezone.utc)
        reg = CapabilityRegistration(
            capability_id="test.v1",
            display_name="Test",
            profile_name="test",
            registered_at=now,
            updated_at=now,
        )
        assert reg.version == "1.0.0"
        assert reg.security_classification == SecurityClassification.INTERNAL
        assert reg.memory_usage_policy == MemoryUsagePolicy.NONE
        assert reg.invocation_modes == [InvocationMode.ASYNC]
        assert reg.status == LifecycleState.DRAFT
        assert reg.tags == []
        assert reg.description == ""
