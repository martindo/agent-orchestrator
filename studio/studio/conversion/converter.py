"""Bidirectional converter between Studio IR models and runtime ProfileConfig.

This module is the single chokepoint through which all IR ↔ runtime
conversions pass.  Every field is mapped explicitly — no ``**kwargs``
passthrough that silently drops unknown keys.
"""

from __future__ import annotations

import logging
from typing import Any

from studio.exceptions import ConversionError
from studio.ir.models import (
    AgentSpec,
    AppManifestSpec,
    ArtifactTypeSpec,
    ConditionSpec,
    DelegatedAuthoritySpec,
    GovernanceSpec,
    LLMSpec,
    OnFailureAction,
    PhaseSpec,
    PolicySpec,
    QualityGateSpec,
    RetryPolicySpec,
    StatusSpec,
    TeamSpec,
    WorkflowSpec,
    WorkItemFieldSpec,
    WorkItemTypeSpec,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Forward: IR → runtime ProfileConfig
# ---------------------------------------------------------------------------

def _llm_spec_to_dict(spec: LLMSpec) -> dict[str, Any]:
    """Convert LLMSpec → dict matching LLMConfig constructor args."""
    result: dict[str, Any] = {
        "provider": spec.provider,
        "model": spec.model,
        "temperature": spec.temperature,
        "max_tokens": spec.max_tokens,
    }
    if spec.endpoint is not None:
        result["endpoint"] = spec.endpoint
    return result


def _retry_spec_to_dict(spec: RetryPolicySpec) -> dict[str, Any]:
    """Convert RetryPolicySpec → dict matching RetryPolicy constructor args."""
    return {
        "max_retries": spec.max_retries,
        "delay_seconds": spec.delay_seconds,
        "backoff_multiplier": spec.backoff_multiplier,
    }


def _condition_spec_to_dict(spec: ConditionSpec) -> dict[str, Any]:
    """Convert ConditionSpec → dict matching ConditionConfig constructor args."""
    result: dict[str, Any] = {"expression": spec.expression}
    if spec.description:
        result["description"] = spec.description
    return result


def _quality_gate_spec_to_dict(spec: QualityGateSpec) -> dict[str, Any]:
    """Convert QualityGateSpec → dict matching QualityGateConfig constructor args."""
    return {
        "name": spec.name,
        "description": spec.description,
        "conditions": [_condition_spec_to_dict(c) for c in spec.conditions],
        "on_failure": spec.on_failure.value,
    }


def _agent_spec_to_dict(spec: AgentSpec) -> dict[str, Any]:
    """Convert AgentSpec → dict matching AgentDefinition constructor args."""
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "system_prompt": spec.system_prompt,
        "skills": list(spec.skills),
        "phases": list(spec.phases),
        "llm": _llm_spec_to_dict(spec.llm),
        "concurrency": spec.concurrency,
        "retry_policy": _retry_spec_to_dict(spec.retry_policy),
        "enabled": spec.enabled,
    }


def _status_spec_to_dict(spec: StatusSpec) -> dict[str, Any]:
    """Convert StatusSpec → dict matching StatusConfig constructor args."""
    result: dict[str, Any] = {
        "id": spec.id,
        "name": spec.name,
    }
    if spec.description:
        result["description"] = spec.description
    if spec.is_initial:
        result["is_initial"] = True
    if spec.is_terminal:
        result["is_terminal"] = True
    if spec.transitions_to:
        result["transitions_to"] = list(spec.transitions_to)
    return result


def _phase_spec_to_dict(spec: PhaseSpec) -> dict[str, Any]:
    """Convert PhaseSpec → dict matching WorkflowPhaseConfig constructor args."""
    result: dict[str, Any] = {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "order": spec.order,
        "agents": list(spec.agents),
        "parallel": spec.parallel,
        "on_success": spec.on_success,
        "on_failure": spec.on_failure,
        "skippable": spec.skippable,
        "skip": spec.skip,
        "is_terminal": spec.is_terminal,
        "requires_human": spec.requires_human,
    }
    if spec.required_capabilities:
        result["required_capabilities"] = list(spec.required_capabilities)
    if spec.expected_output_fields:
        result["expected_output_fields"] = list(spec.expected_output_fields)
    if spec.entry_conditions:
        result["entry_conditions"] = [
            _condition_spec_to_dict(c) for c in spec.entry_conditions
        ]
    if spec.exit_conditions:
        result["exit_conditions"] = [
            _condition_spec_to_dict(c) for c in spec.exit_conditions
        ]
    if spec.quality_gates:
        result["quality_gates"] = [
            _quality_gate_spec_to_dict(g) for g in spec.quality_gates
        ]
    if spec.critic_agent is not None:
        result["critic_agent"] = spec.critic_agent
    if spec.critic_rubric:
        result["critic_rubric"] = spec.critic_rubric
    if spec.max_phase_retries != 1:
        result["max_phase_retries"] = spec.max_phase_retries
    if spec.retry_backoff_seconds != 1.0:
        result["retry_backoff_seconds"] = spec.retry_backoff_seconds
    return result


def _field_spec_to_dict(spec: WorkItemFieldSpec) -> dict[str, Any]:
    """Convert WorkItemFieldSpec → dict matching FieldDefinition constructor args."""
    result: dict[str, Any] = {
        "name": spec.name,
        "type": spec.type.value,
        "required": spec.required,
    }
    if spec.default is not None:
        result["default"] = spec.default
    if spec.values is not None:
        result["values"] = list(spec.values)
    return result


def _artifact_spec_to_dict(spec: ArtifactTypeSpec) -> dict[str, Any]:
    """Convert ArtifactTypeSpec → dict matching ArtifactTypeConfig constructor args."""
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "file_extensions": list(spec.file_extensions),
    }


def _work_item_type_spec_to_dict(spec: WorkItemTypeSpec) -> dict[str, Any]:
    """Convert WorkItemTypeSpec → dict for WorkItemTypeConfig."""
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "custom_fields": [_field_spec_to_dict(f) for f in spec.custom_fields],
        "artifact_types": [_artifact_spec_to_dict(a) for a in spec.artifact_types],
    }


def _manifest_spec_to_dict(spec: AppManifestSpec) -> dict[str, Any]:
    """Convert AppManifestSpec → dict matching AppManifest constructor args."""
    return {
        "name": spec.name,
        "version": spec.version,
        "description": spec.description,
        "platform_version": spec.platform_version,
        "requires": dict(spec.requires),
        "produces": dict(spec.produces),
        "hooks": dict(spec.hooks),
        "author": spec.author,
    }


def ir_to_profile_dict(team: TeamSpec) -> dict[str, Any]:
    """Convert a TeamSpec into a plain dict suitable for ProfileConfig(**d).

    Returns:
        Nested dict that can be passed directly to
        ``ProfileConfig(**ir_to_profile_dict(team))``.

    Raises:
        ConversionError: If the conversion fails.
    """
    try:
        result: dict[str, Any] = {
            "name": team.name,
            "description": team.description,
            "agents": [_agent_spec_to_dict(a) for a in team.agents],
            "workflow": {
                "name": team.workflow.name,
                "description": team.workflow.description,
                "statuses": [_status_spec_to_dict(s) for s in team.workflow.statuses],
                "phases": [_phase_spec_to_dict(p) for p in team.workflow.phases],
            },
            "governance": {
                "delegated_authority": {
                    "auto_approve_threshold": team.governance.delegated_authority.auto_approve_threshold,
                    "review_threshold": team.governance.delegated_authority.review_threshold,
                    "abort_threshold": team.governance.delegated_authority.abort_threshold,
                    "work_type_overrides": dict(team.governance.delegated_authority.work_type_overrides),
                },
                "policies": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "description": p.description,
                        "scope": p.scope,
                        "action": p.action,
                        "conditions": list(p.conditions),
                        "priority": p.priority,
                        "enabled": p.enabled,
                        "tags": list(p.tags),
                    }
                    for p in team.governance.policies
                ],
            },
            "work_item_types": [
                _work_item_type_spec_to_dict(w) for w in team.work_item_types
            ],
        }
        if team.manifest is not None:
            result["manifest"] = _manifest_spec_to_dict(team.manifest)
        return result
    except (KeyError, TypeError, AttributeError) as exc:
        raise ConversionError(f"Failed to convert TeamSpec to profile dict: {exc}") from exc


def ir_to_profile(team: TeamSpec) -> object:
    """Convert TeamSpec → runtime ProfileConfig instance.

    Imports the runtime model lazily so Studio can function without
    the runtime installed (using dict-based YAML generation instead).

    Raises:
        ConversionError: If the runtime module is unavailable or conversion fails.
    """
    try:
        from agent_orchestrator.configuration.models import ProfileConfig
    except ImportError as exc:
        raise ConversionError(
            "agent-orchestrator runtime not installed; cannot create ProfileConfig"
        ) from exc

    profile_dict = ir_to_profile_dict(team)
    try:
        return ProfileConfig(**profile_dict)
    except Exception as exc:
        raise ConversionError(f"ProfileConfig construction failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Reverse: runtime ProfileConfig → IR
# ---------------------------------------------------------------------------

def _llm_config_to_spec(llm: object) -> LLMSpec:
    """Convert runtime LLMConfig → LLMSpec."""
    return LLMSpec(
        provider=llm.provider,  # type: ignore[attr-defined]
        model=llm.model,  # type: ignore[attr-defined]
        temperature=llm.temperature,  # type: ignore[attr-defined]
        max_tokens=llm.max_tokens,  # type: ignore[attr-defined]
        endpoint=llm.endpoint,  # type: ignore[attr-defined]
    )


def _retry_policy_to_spec(rp: object) -> RetryPolicySpec:
    """Convert runtime RetryPolicy → RetryPolicySpec."""
    return RetryPolicySpec(
        max_retries=rp.max_retries,  # type: ignore[attr-defined]
        delay_seconds=rp.delay_seconds,  # type: ignore[attr-defined]
        backoff_multiplier=rp.backoff_multiplier,  # type: ignore[attr-defined]
    )


def _condition_config_to_spec(cc: object) -> ConditionSpec:
    """Convert runtime ConditionConfig → ConditionSpec."""
    return ConditionSpec(
        expression=cc.expression,  # type: ignore[attr-defined]
        description=cc.description,  # type: ignore[attr-defined]
    )


def _quality_gate_to_spec(qg: object) -> QualityGateSpec:
    """Convert runtime QualityGateConfig → QualityGateSpec."""
    raw_action = qg.on_failure  # type: ignore[attr-defined]
    try:
        action = OnFailureAction(raw_action)
    except ValueError:
        action = OnFailureAction.BLOCK
    return QualityGateSpec(
        name=qg.name,  # type: ignore[attr-defined]
        description=qg.description,  # type: ignore[attr-defined]
        conditions=[
            _condition_config_to_spec(c)
            for c in qg.conditions  # type: ignore[attr-defined]
        ],
        on_failure=action,
    )


def _agent_def_to_spec(ad: object) -> AgentSpec:
    """Convert runtime AgentDefinition → AgentSpec."""
    return AgentSpec(
        id=ad.id,  # type: ignore[attr-defined]
        name=ad.name,  # type: ignore[attr-defined]
        description=ad.description,  # type: ignore[attr-defined]
        system_prompt=ad.system_prompt,  # type: ignore[attr-defined]
        skills=list(ad.skills),  # type: ignore[attr-defined]
        phases=list(ad.phases),  # type: ignore[attr-defined]
        llm=_llm_config_to_spec(ad.llm),  # type: ignore[attr-defined]
        concurrency=ad.concurrency,  # type: ignore[attr-defined]
        retry_policy=_retry_policy_to_spec(ad.retry_policy),  # type: ignore[attr-defined]
        enabled=ad.enabled,  # type: ignore[attr-defined]
    )


def _status_config_to_spec(sc: object) -> StatusSpec:
    """Convert runtime StatusConfig → StatusSpec."""
    return StatusSpec(
        id=sc.id,  # type: ignore[attr-defined]
        name=sc.name,  # type: ignore[attr-defined]
        description=getattr(sc, "description", ""),
        is_initial=sc.is_initial,  # type: ignore[attr-defined]
        is_terminal=sc.is_terminal,  # type: ignore[attr-defined]
        transitions_to=list(sc.transitions_to),  # type: ignore[attr-defined]
    )


def _phase_config_to_spec(pc: object) -> PhaseSpec:
    """Convert runtime WorkflowPhaseConfig → PhaseSpec."""
    return PhaseSpec(
        id=pc.id,  # type: ignore[attr-defined]
        name=pc.name,  # type: ignore[attr-defined]
        description=pc.description,  # type: ignore[attr-defined]
        order=pc.order,  # type: ignore[attr-defined]
        agents=list(pc.agents),  # type: ignore[attr-defined]
        parallel=pc.parallel,  # type: ignore[attr-defined]
        entry_conditions=[
            _condition_config_to_spec(c)
            for c in pc.entry_conditions  # type: ignore[attr-defined]
        ],
        exit_conditions=[
            _condition_config_to_spec(c)
            for c in pc.exit_conditions  # type: ignore[attr-defined]
        ],
        quality_gates=[
            _quality_gate_to_spec(g)
            for g in pc.quality_gates  # type: ignore[attr-defined]
        ],
        critic_agent=pc.critic_agent,  # type: ignore[attr-defined]
        critic_rubric=pc.critic_rubric,  # type: ignore[attr-defined]
        max_phase_retries=pc.max_phase_retries,  # type: ignore[attr-defined]
        retry_backoff_seconds=pc.retry_backoff_seconds,  # type: ignore[attr-defined]
        on_success=pc.on_success,  # type: ignore[attr-defined]
        on_failure=pc.on_failure,  # type: ignore[attr-defined]
        skippable=pc.skippable,  # type: ignore[attr-defined]
        skip=pc.skip,  # type: ignore[attr-defined]
        is_terminal=pc.is_terminal,  # type: ignore[attr-defined]
        requires_human=pc.requires_human,  # type: ignore[attr-defined]
        required_capabilities=list(getattr(pc, "required_capabilities", [])),
        expected_output_fields=list(getattr(pc, "expected_output_fields", [])),
    )


def _field_def_to_spec(fd: object) -> WorkItemFieldSpec:
    """Convert runtime FieldDefinition → WorkItemFieldSpec."""
    from studio.ir.models import FieldType as IRFieldType

    raw_type = fd.type  # type: ignore[attr-defined]
    field_type = IRFieldType(raw_type.value if hasattr(raw_type, "value") else raw_type)
    return WorkItemFieldSpec(
        name=fd.name,  # type: ignore[attr-defined]
        type=field_type,
        required=fd.required,  # type: ignore[attr-defined]
        default=fd.default,  # type: ignore[attr-defined]
        values=list(fd.values) if fd.values is not None else None,  # type: ignore[attr-defined]
    )


def _artifact_type_to_spec(at: object) -> ArtifactTypeSpec:
    """Convert runtime ArtifactTypeConfig → ArtifactTypeSpec."""
    return ArtifactTypeSpec(
        id=at.id,  # type: ignore[attr-defined]
        name=at.name,  # type: ignore[attr-defined]
        description=getattr(at, "description", ""),
        file_extensions=list(at.file_extensions),  # type: ignore[attr-defined]
    )


def _work_item_type_to_spec(wit: object) -> WorkItemTypeSpec:
    """Convert runtime WorkItemTypeConfig → WorkItemTypeSpec."""
    return WorkItemTypeSpec(
        id=wit.id,  # type: ignore[attr-defined]
        name=wit.name,  # type: ignore[attr-defined]
        description=wit.description,  # type: ignore[attr-defined]
        custom_fields=[
            _field_def_to_spec(f) for f in wit.custom_fields  # type: ignore[attr-defined]
        ],
        artifact_types=[
            _artifact_type_to_spec(a) for a in wit.artifact_types  # type: ignore[attr-defined]
        ],
    )


def _manifest_to_spec(m: object) -> AppManifestSpec:
    """Convert runtime AppManifest → AppManifestSpec."""
    return AppManifestSpec(
        name=m.name,  # type: ignore[attr-defined]
        version=m.version,  # type: ignore[attr-defined]
        description=m.description,  # type: ignore[attr-defined]
        platform_version=m.platform_version,  # type: ignore[attr-defined]
        requires=dict(m.requires),  # type: ignore[attr-defined]
        produces=dict(m.produces),  # type: ignore[attr-defined]
        hooks=dict(m.hooks),  # type: ignore[attr-defined]
        author=m.author,  # type: ignore[attr-defined]
    )


def profile_to_ir(profile: object) -> TeamSpec:
    """Convert a runtime ProfileConfig into a Studio TeamSpec.

    Accepts ``object`` so Studio can work with any object exposing the
    same attribute names (duck typing), but the typical input is a real
    ``agent_orchestrator.configuration.models.ProfileConfig``.

    Raises:
        ConversionError: If a required attribute is missing.
    """
    try:
        workflow_obj = profile.workflow  # type: ignore[attr-defined]
        governance_obj = profile.governance  # type: ignore[attr-defined]

        workflow = WorkflowSpec(
            name=workflow_obj.name,
            description=workflow_obj.description,
            statuses=[_status_config_to_spec(s) for s in workflow_obj.statuses],
            phases=[_phase_config_to_spec(p) for p in workflow_obj.phases],
        )

        da = governance_obj.delegated_authority
        governance = GovernanceSpec(
            delegated_authority=DelegatedAuthoritySpec(
                auto_approve_threshold=da.auto_approve_threshold,
                review_threshold=da.review_threshold,
                abort_threshold=da.abort_threshold,
                work_type_overrides=dict(da.work_type_overrides),
            ),
            policies=[
                PolicySpec(
                    id=p.id,
                    name=p.name,
                    description=p.description,
                    scope=p.scope,
                    action=p.action,
                    conditions=list(p.conditions),
                    priority=p.priority,
                    enabled=p.enabled,
                    tags=list(p.tags),
                )
                for p in governance_obj.policies
            ],
        )

        manifest_obj = getattr(profile, "manifest", None)
        manifest = _manifest_to_spec(manifest_obj) if manifest_obj is not None else None

        return TeamSpec(
            name=profile.name,  # type: ignore[attr-defined]
            description=profile.description,  # type: ignore[attr-defined]
            agents=[_agent_def_to_spec(a) for a in profile.agents],  # type: ignore[attr-defined]
            workflow=workflow,
            governance=governance,
            work_item_types=[
                _work_item_type_to_spec(w)
                for w in profile.work_item_types  # type: ignore[attr-defined]
            ],
            manifest=manifest,
        )
    except AttributeError as exc:
        raise ConversionError(
            f"ProfileConfig missing expected attribute: {exc}"
        ) from exc
