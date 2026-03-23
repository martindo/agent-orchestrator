"""Tests for auto-registration — profile → CapabilityRegistration derivation."""

from __future__ import annotations

import pytest

from agent_orchestrator.catalog.auto_register import (
    build_registration_from_profile,
    _build_input_schema,
    _build_output_schema,
    _determine_invocation_modes,
)
from agent_orchestrator.catalog.models import InvocationMode, SecurityClassification
from agent_orchestrator.configuration.models import (
    AgentDefinition,
    AppManifest,
    DelegatedAuthorityConfig,
    FieldDefinition,
    FieldType,
    GovernanceConfig,
    LLMConfig,
    ProfileConfig,
    SettingsConfig,
    WorkflowConfig,
    WorkflowPhaseConfig,
    WorkItemTypeConfig,
)
from agent_orchestrator.contracts.models import LifecycleState


def _make_llm() -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-4o")


def _make_settings(deployment_mode: str = "lite") -> SettingsConfig:
    return SettingsConfig(active_profile="test", deployment_mode=deployment_mode)


def _make_profile(
    *,
    name: str = "test-profile",
    manifest: AppManifest | None = None,
    work_item_types: list[WorkItemTypeConfig] | None = None,
    phases: list[WorkflowPhaseConfig] | None = None,
    review_threshold: float = 0.5,
) -> ProfileConfig:
    workflow = WorkflowConfig(
        name="test-workflow",
        phases=phases or [],
    )
    governance = GovernanceConfig(
        delegated_authority=DelegatedAuthorityConfig(
            review_threshold=review_threshold,
        ),
    )
    return ProfileConfig(
        name=name,
        description="A test profile",
        manifest=manifest,
        workflow=workflow,
        governance=governance,
        work_item_types=work_item_types or [],
    )


class TestBuildRegistrationBasic:
    """Test basic auto-registration without manifest."""

    def test_basic_profile(self) -> None:
        profile = _make_profile(name="my-team")
        settings = _make_settings()
        reg = build_registration_from_profile(profile, settings)

        assert reg.capability_id == "my-team.v1"
        assert reg.display_name == "my-team"
        assert reg.description == "A test profile"
        assert reg.owner == ""
        assert reg.version == "1.0.0"
        assert reg.profile_name == "my-team"
        assert reg.deployment_mode == "lite"
        assert reg.status == LifecycleState.ACTIVE
        assert reg.security_classification == SecurityClassification.INTERNAL

    def test_deployment_mode_from_settings(self) -> None:
        profile = _make_profile()
        settings = _make_settings(deployment_mode="standard")
        reg = build_registration_from_profile(profile, settings)
        assert reg.deployment_mode == "standard"

    def test_review_threshold(self) -> None:
        profile = _make_profile(review_threshold=0.7)
        settings = _make_settings()
        reg = build_registration_from_profile(profile, settings)
        assert reg.review_required_below == 0.7


class TestBuildRegistrationWithManifest:
    """Test auto-registration with manifest metadata."""

    def test_manifest_overrides(self) -> None:
        manifest = AppManifest(
            name="research-team",
            version="2.1.0",
            description="Does research",
            author="Alice",
            requires={"connectors": ["web_search", "database"]},
            produces={"reports": ["summary"], "insights": ["analysis"]},
        )
        profile = _make_profile(manifest=manifest)
        settings = _make_settings()
        reg = build_registration_from_profile(profile, settings)

        assert reg.capability_id == "research-team.v2.1.0"
        assert reg.display_name == "research-team"
        assert reg.description == "Does research"
        assert reg.owner == "Alice"
        assert reg.version == "2.1.0"
        assert reg.required_connectors == ["web_search", "database"]
        assert set(reg.tags) == {"reports", "insights"}

    def test_manifest_empty_name_falls_back(self) -> None:
        manifest = AppManifest(name="", version="1.0.0")
        profile = _make_profile(name="fallback", manifest=manifest)
        settings = _make_settings()
        reg = build_registration_from_profile(profile, settings)
        assert reg.capability_id == "fallback.v1"
        assert reg.display_name == "fallback"


class TestInputSchemaDerivation:
    """Test input_schema derivation from work_item_types custom_fields."""

    def test_empty_types(self) -> None:
        profile = _make_profile()
        assert _build_input_schema(profile) == {}

    def test_custom_fields_mapped(self) -> None:
        wit = WorkItemTypeConfig(
            id="request",
            name="Request",
            custom_fields=[
                FieldDefinition(name="topic", type=FieldType.STRING, required=True),
                FieldDefinition(name="depth", type=FieldType.INTEGER, required=False, default=3),
                FieldDefinition(
                    name="priority",
                    type=FieldType.ENUM,
                    values=["low", "medium", "high"],
                ),
                FieldDefinition(name="score", type=FieldType.FLOAT),
                FieldDefinition(name="urgent", type=FieldType.BOOLEAN),
            ],
        )
        profile = _make_profile(work_item_types=[wit])
        schema = _build_input_schema(profile)

        assert schema["type"] == "object"
        props = schema["properties"]
        assert props["topic"]["type"] == "string"
        assert props["depth"]["type"] == "integer"
        assert props["depth"]["default"] == 3
        assert props["priority"]["type"] == "string"
        assert props["priority"]["enum"] == ["low", "medium", "high"]
        assert props["score"]["type"] == "number"
        assert props["urgent"]["type"] == "boolean"
        assert schema["required"] == ["topic"]


class TestOutputSchemaDerivation:
    """Test output_schema derivation from phase expected_output_fields."""

    def test_empty_phases(self) -> None:
        profile = _make_profile()
        assert _build_output_schema(profile) == {}

    def test_output_fields_collected(self) -> None:
        phases = [
            WorkflowPhaseConfig(
                id="p1", name="Phase 1", order=1,
                expected_output_fields=["summary", "confidence"],
            ),
            WorkflowPhaseConfig(
                id="p2", name="Phase 2", order=2,
                expected_output_fields=["confidence", "recommendation"],
            ),
        ]
        profile = _make_profile(phases=phases)
        schema = _build_output_schema(profile)

        assert schema["type"] == "object"
        props = schema["properties"]
        assert "summary" in props
        assert "confidence" in props
        assert "recommendation" in props
        # No duplicates
        assert len(props) == 3


class TestInvocationModes:
    """Test invocation mode determination."""

    def test_single_non_terminal_includes_sync(self) -> None:
        phases = [
            WorkflowPhaseConfig(id="p1", name="Phase 1", order=1, is_terminal=False),
        ]
        profile = _make_profile(phases=phases)
        modes = _determine_invocation_modes(profile)
        assert InvocationMode.SYNC in modes
        assert InvocationMode.ASYNC in modes
        assert InvocationMode.EVENT_DRIVEN in modes

    def test_multiple_non_terminal_excludes_sync(self) -> None:
        phases = [
            WorkflowPhaseConfig(id="p1", name="Phase 1", order=1, is_terminal=False),
            WorkflowPhaseConfig(id="p2", name="Phase 2", order=2, is_terminal=False),
        ]
        profile = _make_profile(phases=phases)
        modes = _determine_invocation_modes(profile)
        assert InvocationMode.SYNC not in modes
        assert InvocationMode.ASYNC in modes

    def test_no_phases_includes_sync(self) -> None:
        profile = _make_profile()
        modes = _determine_invocation_modes(profile)
        assert InvocationMode.SYNC in modes


class TestFullRegistration:
    """End-to-end registration with all features."""

    def test_full_registration(self) -> None:
        manifest = AppManifest(
            name="full-test",
            version="3.0.0",
            author="Bob",
            requires={"connectors": ["search"]},
            produces={"artifacts": ["report"]},
        )
        wit = WorkItemTypeConfig(
            id="task",
            name="Task",
            custom_fields=[
                FieldDefinition(name="query", type=FieldType.STRING, required=True),
            ],
        )
        phases = [
            WorkflowPhaseConfig(
                id="analyze", name="Analyze", order=1,
                expected_output_fields=["result"],
            ),
        ]
        profile = _make_profile(
            manifest=manifest,
            work_item_types=[wit],
            phases=phases,
            review_threshold=0.6,
        )
        settings = _make_settings(deployment_mode="enterprise")
        reg = build_registration_from_profile(profile, settings)

        assert reg.capability_id == "full-test.v3.0.0"
        assert reg.deployment_mode == "enterprise"
        assert reg.input_schema["properties"]["query"]["type"] == "string"
        assert reg.output_schema["properties"]["result"]["type"] == "string"
        assert reg.required_connectors == ["search"]
        assert reg.review_required_below == 0.6
        assert InvocationMode.SYNC in reg.invocation_modes
        assert reg.status == LifecycleState.ACTIVE
