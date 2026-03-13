"""Tests for ExecutionContext, DeploymentMode, and context helpers."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from agent_orchestrator.configuration.models import (
    DeploymentMode,
    ExecutionContext,
    PersistenceBackend,
    SettingsConfig,
)
from agent_orchestrator.core.context import (
    context_tags,
    create_root_context,
    create_run_context,
)
from agent_orchestrator.core.event_bus import Event, EventType
from agent_orchestrator.core.work_queue import WorkItem
from agent_orchestrator.governance.audit_logger import AuditLogger, AuditRecord, RecordType


# ---- DeploymentMode enum ----


class TestDeploymentMode:
    def test_values(self) -> None:
        assert DeploymentMode.LITE.value == "lite"
        assert DeploymentMode.STANDARD.value == "standard"
        assert DeploymentMode.ENTERPRISE.value == "enterprise"

    def test_from_string(self) -> None:
        assert DeploymentMode("lite") == DeploymentMode.LITE
        assert DeploymentMode("standard") == DeploymentMode.STANDARD
        assert DeploymentMode("enterprise") == DeploymentMode.ENTERPRISE


# ---- PersistenceBackend extended ----


class TestPersistenceBackendExtended:
    def test_postgresql_value(self) -> None:
        assert PersistenceBackend.POSTGRESQL.value == "postgresql"

    def test_all_backends(self) -> None:
        values = {b.value for b in PersistenceBackend}
        assert values == {"file", "sqlite", "postgresql"}


# ---- ExecutionContext model ----


class TestExecutionContext:
    def test_defaults(self) -> None:
        ctx = ExecutionContext()
        assert ctx.app_id == "default"
        assert ctx.run_id == ""
        assert ctx.tenant_id == "default"
        assert ctx.environment == "development"
        assert ctx.deployment_mode == DeploymentMode.LITE
        assert ctx.profile_name == ""
        assert ctx.extra == {}

    def test_immutability(self) -> None:
        ctx = ExecutionContext()
        with pytest.raises(ValidationError):
            ctx.app_id = "other"  # type: ignore[misc]

    def test_custom_values(self) -> None:
        ctx = ExecutionContext(
            app_id="myapp",
            run_id="run-123",
            tenant_id="tenant-a",
            environment="production",
            deployment_mode=DeploymentMode.ENTERPRISE,
            profile_name="prod-profile",
            extra={"region": "us-east-1"},
        )
        assert ctx.app_id == "myapp"
        assert ctx.run_id == "run-123"
        assert ctx.deployment_mode == DeploymentMode.ENTERPRISE
        assert ctx.extra["region"] == "us-east-1"


# ---- SettingsConfig with deployment_mode ----


class TestSettingsConfigDeploymentMode:
    def test_default_deployment_mode(self) -> None:
        s = SettingsConfig(active_profile="test")
        assert s.deployment_mode == "lite"

    def test_valid_modes(self) -> None:
        for mode in ("lite", "standard", "enterprise"):
            s = SettingsConfig(active_profile="test", deployment_mode=mode)
            assert s.deployment_mode == mode

    def test_invalid_mode(self) -> None:
        with pytest.raises(ValidationError):
            SettingsConfig(active_profile="test", deployment_mode="invalid")

    def test_postgresql_backend(self) -> None:
        s = SettingsConfig(active_profile="test", persistence_backend="postgresql")
        assert s.persistence_backend == "postgresql"


# ---- Context helpers ----


class TestCreateRootContext:
    def test_basic(self) -> None:
        settings = SettingsConfig(
            active_profile="my-profile",
            deployment_mode="standard",
        )
        ctx = create_root_context(settings)
        assert ctx.app_id == "default"
        assert ctx.run_id == ""
        assert ctx.deployment_mode == DeploymentMode.STANDARD
        assert ctx.profile_name == "my-profile"

    def test_profile_override(self) -> None:
        settings = SettingsConfig(active_profile="default")
        ctx = create_root_context(settings, profile_name="override")
        assert ctx.profile_name == "override"


class TestCreateRunContext:
    def test_generates_run_id(self) -> None:
        root = ExecutionContext(app_id="app1", deployment_mode=DeploymentMode.LITE)
        run = create_run_context(root)
        assert run.run_id != ""
        assert run.app_id == "app1"
        assert run.deployment_mode == DeploymentMode.LITE

    def test_explicit_run_id(self) -> None:
        root = ExecutionContext()
        run = create_run_context(root, run_id="explicit-id")
        assert run.run_id == "explicit-id"

    def test_inherits_parent_fields(self) -> None:
        root = ExecutionContext(
            app_id="app",
            tenant_id="tenant",
            environment="staging",
            deployment_mode=DeploymentMode.ENTERPRISE,
            profile_name="prod",
            extra={"key": "val"},
        )
        run = create_run_context(root)
        assert run.app_id == root.app_id
        assert run.tenant_id == root.tenant_id
        assert run.environment == root.environment
        assert run.deployment_mode == root.deployment_mode
        assert run.profile_name == root.profile_name
        assert run.extra == root.extra


class TestContextTags:
    def test_returns_flat_dict(self) -> None:
        ctx = ExecutionContext(
            app_id="myapp",
            run_id="run-1",
            tenant_id="t1",
            environment="prod",
            deployment_mode=DeploymentMode.STANDARD,
            profile_name="p1",
        )
        tags = context_tags(ctx)
        assert tags == {
            "app_id": "myapp",
            "run_id": "run-1",
            "tenant_id": "t1",
            "environment": "prod",
            "deployment_mode": "standard",
            "profile_name": "p1",
        }


# ---- Data structure extensions ----


class TestWorkItemExtensions:
    def test_default_fields(self) -> None:
        item = WorkItem(id="w1", type_id="t1", title="Test")
        assert item.run_id == ""
        assert item.app_id == "default"

    def test_custom_fields(self) -> None:
        item = WorkItem(id="w1", type_id="t1", title="Test", run_id="r1", app_id="a1")
        assert item.run_id == "r1"
        assert item.app_id == "a1"


class TestEventExtensions:
    def test_default_fields(self) -> None:
        event = Event(type=EventType.WORK_SUBMITTED, data={})
        assert event.app_id == ""
        assert event.run_id == ""

    def test_custom_fields(self) -> None:
        event = Event(
            type=EventType.WORK_SUBMITTED,
            data={},
            app_id="app1",
            run_id="run1",
        )
        assert event.app_id == "app1"
        assert event.run_id == "run1"


class TestAuditRecordExtensions:
    def test_default_fields(self) -> None:
        record = AuditRecord(
            sequence=1,
            record_type=RecordType.DECISION,
            action="test",
            summary="test",
        )
        assert record.app_id == ""
        assert record.run_id == ""

    def test_custom_fields(self) -> None:
        record = AuditRecord(
            sequence=1,
            record_type=RecordType.DECISION,
            action="test",
            summary="test",
            app_id="app1",
            run_id="run1",
        )
        assert record.app_id == "app1"
        assert record.run_id == "run1"


class TestAuditLoggerQueryFiltering:
    def test_query_by_app_id(self, tmp_path: "pytest.TempPathFactory") -> None:
        logger = AuditLogger(tmp_path / "audit")  # type: ignore[arg-type]
        logger.append(RecordType.DECISION, "a1", "s1", app_id="app1")
        logger.append(RecordType.DECISION, "a2", "s2", app_id="app2")
        logger.append(RecordType.DECISION, "a3", "s3", app_id="app1")

        results = logger.query(app_id="app1")
        assert len(results) == 2
        assert all(r["app_id"] == "app1" for r in results)

    def test_query_by_run_id(self, tmp_path: "pytest.TempPathFactory") -> None:
        logger = AuditLogger(tmp_path / "audit")  # type: ignore[arg-type]
        logger.append(RecordType.STATE_CHANGE, "a1", "s1", run_id="run-x")
        logger.append(RecordType.STATE_CHANGE, "a2", "s2", run_id="run-y")

        results = logger.query(run_id="run-x")
        assert len(results) == 1
        assert results[0]["run_id"] == "run-x"

    def test_query_combined_filters(self, tmp_path: "pytest.TempPathFactory") -> None:
        logger = AuditLogger(tmp_path / "audit")  # type: ignore[arg-type]
        logger.append(RecordType.DECISION, "a1", "s1", app_id="app1", run_id="r1")
        logger.append(RecordType.DECISION, "a2", "s2", app_id="app1", run_id="r2")
        logger.append(RecordType.DECISION, "a3", "s3", app_id="app2", run_id="r1")

        results = logger.query(app_id="app1", run_id="r1")
        assert len(results) == 1


# ---- Public exports ----


class TestPublicExports:
    def test_execution_context_exported(self) -> None:
        from agent_orchestrator import ExecutionContext
        assert ExecutionContext is not None

    def test_deployment_mode_exported(self) -> None:
        from agent_orchestrator import DeploymentMode
        assert DeploymentMode is not None
