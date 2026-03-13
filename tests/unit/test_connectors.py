"""Tests for the Connector Capability Framework."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_orchestrator.connectors import (
    CapabilityType,
    ConnectorConfig,
    ConnectorCostInfo,
    ConnectorExecutionTrace,
    ConnectorExecutor,
    ConnectorExecutorError,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorPermissionError,
    ConnectorPermissionPolicy,
    ConnectorProviderDescriptor,
    ConnectorRateLimit,
    ConnectorRegistry,
    ConnectorRetryPolicy,
    ConnectorService,
    ConnectorServiceError,
    ConnectorStatus,
    ConnectorTraceStore,
    ExternalArtifact,
    ExternalReference,
    ExternalResourceDescriptor,
    evaluate_permission,
)
from agent_orchestrator.connectors.auth import (
    AuthType, ConnectorAuthConfig, ConnectorSessionContext, build_session_context
)
from agent_orchestrator.connectors.normalized import (
    SearchResultItem, SearchResultArtifact, DocumentArtifact, MessageArtifact,
    TicketArtifact, RepositoryArtifact, TelemetryArtifact, IdentityArtifact,
    NormalizedArtifactBase, get_normalized_type, try_normalize
)
from agent_orchestrator.connectors.permissions import (
    PermissionOutcome, PermissionEvaluationResult, evaluate_permission_detailed
)


# ---- CapabilityType taxonomy ----


def test_capability_type_taxonomy_exists():
    expected = {
        "search", "documents", "messaging", "ticketing", "repository",
        "telemetry", "identity", "external_api", "file_storage", "workflow_action",
    }
    actual = {c.value for c in CapabilityType}
    assert expected.issubset(actual)


def test_capability_type_is_extensible():
    assert CapabilityType.SEARCH.value == "search"
    assert CapabilityType.DOCUMENTS.value == "documents"
    assert CapabilityType.MESSAGING.value == "messaging"
    assert CapabilityType.TICKETING.value == "ticketing"
    assert CapabilityType.REPOSITORY.value == "repository"
    assert CapabilityType.TELEMETRY.value == "telemetry"
    assert CapabilityType.IDENTITY.value == "identity"
    assert CapabilityType.EXTERNAL_API.value == "external_api"
    assert CapabilityType.FILE_STORAGE.value == "file_storage"
    assert CapabilityType.WORKFLOW_ACTION.value == "workflow_action"


# ---- Model tests ----


def test_connector_invocation_request_defaults():
    req = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={"q": "test"},
        context={"run_id": "r1", "workflow_id": "w1"},
    )
    assert req.capability_type == CapabilityType.SEARCH
    assert req.operation == "query"
    assert req.request_id is not None
    assert req.parameters == {"q": "test"}
    assert req.preferred_provider is None
    assert req.timeout_seconds is None


def test_connector_invocation_request_is_frozen():
    req = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    with pytest.raises(Exception):
        req.operation = "mutated"  # type: ignore[misc]


def test_connector_invocation_result_model():
    result = ConnectorInvocationResult(
        request_id="req-1",
        connector_id="test-connector",
        provider="test-provider",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
        payload={"results": []},
    )
    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload == {"results": []}
    assert result.error_message is None


def test_connector_invocation_result_is_frozen():
    result = ConnectorInvocationResult(
        request_id="r",
        connector_id="c",
        provider="p",
        capability_type=CapabilityType.SEARCH,
        operation="q",
        status=ConnectorStatus.SUCCESS,
    )
    with pytest.raises(Exception):
        result.status = ConnectorStatus.FAILURE  # type: ignore[misc]


def test_external_artifact_envelope():
    artifact = ExternalArtifact(
        source_connector="test-connector",
        provider="test-provider",
        capability_type=CapabilityType.DOCUMENTS,
        resource_type="document",
        raw_payload={"content": "hello"},
        provenance={"run_id": "r1"},
    )
    assert artifact.artifact_id is not None
    assert artifact.source_connector == "test-connector"
    assert artifact.raw_payload == {"content": "hello"}
    assert artifact.provenance["run_id"] == "r1"


def test_external_artifact_no_domain_assumptions():
    artifact = ExternalArtifact(
        source_connector="x",
        provider="x",
        capability_type=CapabilityType.EXTERNAL_API,
        resource_type="generic",
    )
    field_names = set(artifact.model_fields.keys())
    domain_fields = {"research_finding", "security_event", "code_review", "incident"}
    assert not domain_fields.intersection(field_names)


def test_connector_cost_info_model():
    cost = ConnectorCostInfo(
        request_cost=0.001,
        usage_units=100.0,
        provider_reported_cost=0.001,
        estimated_cost=0.001,
        currency="USD",
        unit_label="tokens",
    )
    assert cost.request_cost == 0.001
    assert cost.currency == "USD"


def test_connector_cost_info_defaults():
    cost = ConnectorCostInfo()
    assert cost.request_cost is None
    assert cost.currency == "USD"


def test_connector_permission_policy_defaults():
    policy = ConnectorPermissionPolicy(
        description="Allow search for all",
        allowed_capability_types=[CapabilityType.SEARCH],
        read_only=True,
    )
    assert policy.enabled is True
    assert CapabilityType.SEARCH in policy.allowed_capability_types
    assert policy.policy_id is not None


def test_connector_operation_descriptor():
    op = ConnectorOperationDescriptor(
        operation="query",
        description="Perform a search query",
        capability_type=CapabilityType.SEARCH,
        read_only=True,
        required_parameters=["q"],
        optional_parameters=["limit", "offset"],
    )
    assert op.operation == "query"
    assert op.read_only is True
    assert "q" in op.required_parameters


def test_connector_provider_descriptor():
    desc = ConnectorProviderDescriptor(
        provider_id="my-search",
        display_name="My Search",
        capability_types=[CapabilityType.SEARCH],
        enabled=True,
    )
    assert desc.provider_id == "my-search"
    assert CapabilityType.SEARCH in desc.capability_types


def test_connector_config_model():
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.SEARCH,
        provider_id="p1",
    )
    assert config.connector_id == "c1"
    assert config.enabled is True
    assert config.scoped_modules == []
    assert config.permission_policies == []


def test_external_reference_model():
    ref = ExternalReference(
        provider="github",
        resource_type="pull_request",
        external_id="42",
        url="https://github.com/org/repo/pull/42",
    )
    assert ref.ref_id is not None
    assert ref.external_id == "42"


def test_external_resource_descriptor_model():
    desc = ExternalResourceDescriptor(
        resource_type="issue",
        provider="jira",
        capability_type=CapabilityType.TICKETING,
        description="A Jira issue",
    )
    assert desc.resource_type == "issue"
    assert desc.capability_type == CapabilityType.TICKETING


# ---- ConnectorRegistry tests ----


def _make_mock_provider(provider_id: str, capability_types: list[CapabilityType], enabled: bool = True):
    mock = MagicMock()
    mock.get_descriptor.return_value = ConnectorProviderDescriptor(
        provider_id=provider_id,
        display_name=provider_id.capitalize(),
        capability_types=capability_types,
        enabled=enabled,
    )
    return mock


def test_registry_register_and_list():
    registry = ConnectorRegistry()
    mock_provider = _make_mock_provider("test", [CapabilityType.SEARCH])
    registry.register_provider(mock_provider)
    providers = registry.list_providers()
    assert len(providers) == 1
    assert providers[0].provider_id == "test"


def test_registry_find_by_capability():
    registry = ConnectorRegistry()
    mock_provider = _make_mock_provider("search-p", [CapabilityType.SEARCH])
    registry.register_provider(mock_provider)
    found = registry.find_providers_for_capability(CapabilityType.SEARCH)
    assert len(found) == 1
    found_none = registry.find_providers_for_capability(CapabilityType.MESSAGING)
    assert len(found_none) == 0


def test_registry_find_excludes_disabled_providers():
    registry = ConnectorRegistry()
    disabled = _make_mock_provider("disabled-p", [CapabilityType.SEARCH], enabled=False)
    registry.register_provider(disabled)
    found = registry.find_providers_for_capability(CapabilityType.SEARCH)
    assert len(found) == 0


def test_registry_unregister():
    registry = ConnectorRegistry()
    mock_provider = _make_mock_provider("test", [CapabilityType.SEARCH])
    registry.register_provider(mock_provider)
    registry.unregister_provider("test")
    assert len(registry.list_providers()) == 0


def test_registry_unregister_nonexistent_is_noop():
    registry = ConnectorRegistry()
    registry.unregister_provider("does-not-exist")
    assert len(registry.list_providers()) == 0


def test_registry_config_register_and_get():
    registry = ConnectorRegistry()
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.SEARCH,
        provider_id="p1",
    )
    registry.register_config(config)
    assert registry.get_config("c1") is not None
    assert registry.get_config("c1").connector_id == "c1"
    assert len(registry.list_configs()) == 1


def test_registry_get_provider_returns_none_if_missing():
    registry = ConnectorRegistry()
    assert registry.get_provider("nonexistent") is None


def test_registry_multiple_providers_for_same_capability():
    registry = ConnectorRegistry()
    p1 = _make_mock_provider("p1", [CapabilityType.SEARCH])
    p2 = _make_mock_provider("p2", [CapabilityType.SEARCH])
    registry.register_provider(p1)
    registry.register_provider(p2)
    found = registry.find_providers_for_capability(CapabilityType.SEARCH)
    assert len(found) == 2


# ---- ConnectorService tests ----


@pytest.mark.asyncio
async def test_connector_service_execute_success():
    registry = ConnectorRegistry()
    mock_provider = _make_mock_provider("search-p", [CapabilityType.SEARCH])
    mock_provider.execute = AsyncMock(return_value=ConnectorInvocationResult(
        request_id="req-1",
        connector_id="search-p",
        provider="search-p",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
        payload={"results": ["a", "b"]},
    ))
    registry.register_provider(mock_provider)
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={"q": "test"},
        context={"run_id": "r1"},
    )
    assert result.status == ConnectorStatus.SUCCESS
    assert result.payload == {"results": ["a", "b"]}
    mock_provider.execute.assert_called_once()


@pytest.mark.asyncio
async def test_connector_service_no_provider():
    registry = ConnectorRegistry()
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={},
    )
    assert result.status == ConnectorStatus.UNAVAILABLE
    assert "No provider available" in result.error_message


@pytest.mark.asyncio
async def test_connector_service_string_capability_type():
    registry = ConnectorRegistry()
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type="search",
        operation="query",
        parameters={},
    )
    assert result.status == ConnectorStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_connector_service_invalid_capability_type():
    registry = ConnectorRegistry()
    service = ConnectorService(registry=registry)
    with pytest.raises(ConnectorServiceError, match="Unknown capability_type"):
        await service.execute(
            capability_type="not_a_valid_type_xyz",
            operation="query",
            parameters={},
        )


@pytest.mark.asyncio
async def test_connector_service_preferred_provider():
    registry = ConnectorRegistry()
    p1 = _make_mock_provider("p1", [CapabilityType.SEARCH])
    p2 = _make_mock_provider("p2", [CapabilityType.SEARCH])
    p2.execute = AsyncMock(return_value=ConnectorInvocationResult(
        request_id="r",
        connector_id="p2",
        provider="p2",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
    ))
    registry.register_provider(p1)
    registry.register_provider(p2)
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={},
        preferred_provider="p2",
    )
    assert result.provider == "p2"


@pytest.mark.asyncio
async def test_connector_service_provider_raises_exception():
    registry = ConnectorRegistry()
    mock_provider = _make_mock_provider("error-p", [CapabilityType.SEARCH])
    mock_provider.execute = AsyncMock(side_effect=RuntimeError("provider exploded"))
    registry.register_provider(mock_provider)
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={},
    )
    assert result.status == ConnectorStatus.FAILURE
    assert "provider exploded" in result.error_message


@pytest.mark.asyncio
async def test_connector_service_wrap_result_as_artifact():
    registry = ConnectorRegistry()
    service = ConnectorService(registry=registry)
    result = ConnectorInvocationResult(
        request_id="req-1",
        connector_id="test",
        provider="test",
        capability_type=CapabilityType.DOCUMENTS,
        operation="fetch",
        status=ConnectorStatus.SUCCESS,
        payload={"title": "Doc A"},
    )
    artifact = service.wrap_result_as_artifact(
        result, resource_type="document", provenance={"run_id": "r1"}
    )
    assert isinstance(artifact, ExternalArtifact)
    assert artifact.resource_type == "document"
    assert artifact.raw_payload == {"title": "Doc A"}
    assert artifact.provenance["run_id"] == "r1"
    assert artifact.provenance["request_id"] == "req-1"
    assert artifact.provenance["status"] == "success"


@pytest.mark.asyncio
async def test_connector_service_wrap_result_no_provenance():
    registry = ConnectorRegistry()
    service = ConnectorService(registry=registry)
    result = ConnectorInvocationResult(
        request_id="req-2",
        connector_id="test",
        provider="test",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
    )
    artifact = service.wrap_result_as_artifact(result, resource_type="result")
    assert artifact.provenance["request_id"] == "req-2"


@pytest.mark.asyncio
async def test_connector_service_audit_integration():
    registry = ConnectorRegistry()
    mock_audit = MagicMock()
    mock_audit.append = MagicMock()
    service = ConnectorService(registry=registry, audit_logger=mock_audit)
    await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={},
        context={"run_id": "r1"},
    )
    mock_audit.append.assert_called_once()


@pytest.mark.asyncio
async def test_connector_service_no_audit_when_not_configured():
    registry = ConnectorRegistry()
    # No audit_logger provided — should not raise
    service = ConnectorService(registry=registry, audit_logger=None)
    result = await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={},
    )
    assert result.status == ConnectorStatus.UNAVAILABLE


def test_connector_service_list_available_capabilities_empty():
    registry = ConnectorRegistry()
    service = ConnectorService(registry=registry)
    caps = service.list_available_capabilities()
    assert caps == []


def test_connector_service_list_available_capabilities():
    registry = ConnectorRegistry()
    p1 = _make_mock_provider("p1", [CapabilityType.SEARCH, CapabilityType.DOCUMENTS])
    p2 = _make_mock_provider("p2", [CapabilityType.MESSAGING])
    registry.register_provider(p1)
    registry.register_provider(p2)
    service = ConnectorService(registry=registry)
    caps = service.list_available_capabilities()
    assert CapabilityType.SEARCH in caps
    assert CapabilityType.DOCUMENTS in caps
    assert CapabilityType.MESSAGING in caps


def test_connector_service_list_providers():
    registry = ConnectorRegistry()
    p1 = _make_mock_provider("p1", [CapabilityType.SEARCH])
    registry.register_provider(p1)
    service = ConnectorService(registry=registry)
    providers = service.list_providers()
    assert len(providers) == 1
    assert providers[0].provider_id == "p1"


# ---- Permission hook tests ----


def test_permission_hook_allows_by_default():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    assert evaluate_permission(request, []) is True


def test_permission_hook_deny_capability():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    policy = ConnectorPermissionPolicy(
        description="Block search",
        denied_capability_types=[CapabilityType.SEARCH],
    )
    assert evaluate_permission(request, [policy]) is False


def test_permission_hook_deny_operation():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.TICKETING,
        operation="delete_ticket",
    )
    policy = ConnectorPermissionPolicy(
        description="No deletes",
        denied_operations=["delete_ticket"],
    )
    assert evaluate_permission(request, [policy]) is False


def test_permission_hook_allow_specific_capability():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    policy = ConnectorPermissionPolicy(
        description="Allow search only",
        allowed_capability_types=[CapabilityType.SEARCH],
    )
    assert evaluate_permission(request, [policy]) is True


def test_permission_hook_deny_wrong_capability_with_allowlist():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.MESSAGING,
        operation="send",
    )
    policy = ConnectorPermissionPolicy(
        description="Allow search only",
        allowed_capability_types=[CapabilityType.SEARCH],
    )
    assert evaluate_permission(request, [policy]) is False


def test_permission_hook_module_scoping_no_match():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        context={"module_name": "other_module"},
    )
    policy = ConnectorPermissionPolicy(
        description="Only for mymodule",
        allowed_modules=["mymodule"],
        allowed_capability_types=[CapabilityType.SEARCH],
    )
    # Policy doesn't apply to other_module → default permit
    assert evaluate_permission(request, [policy]) is True


def test_permission_hook_module_scoping_match():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        context={"module_name": "mymodule"},
    )
    policy = ConnectorPermissionPolicy(
        description="Only for mymodule",
        allowed_modules=["mymodule"],
        allowed_capability_types=[CapabilityType.SEARCH],
    )
    assert evaluate_permission(request, [policy]) is True


def test_permission_hook_agent_role_scoping():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        context={"agent_role": "reader"},
    )
    policy = ConnectorPermissionPolicy(
        description="Admin only",
        allowed_agent_roles=["admin"],
        denied_capability_types=[CapabilityType.SEARCH],
    )
    # Policy doesn't apply to "reader" role → default permit
    assert evaluate_permission(request, [policy]) is True


def test_permission_hook_disabled_policy_is_skipped():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    policy = ConnectorPermissionPolicy(
        description="Would deny, but disabled",
        denied_capability_types=[CapabilityType.SEARCH],
        enabled=False,
    )
    assert evaluate_permission(request, [policy]) is True


def test_permission_hook_allowed_operation():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.TICKETING,
        operation="read_ticket",
    )
    policy = ConnectorPermissionPolicy(
        description="Read-only ticketing",
        allowed_operations=["read_ticket"],
    )
    assert evaluate_permission(request, [policy]) is True


def test_permission_hook_denied_by_operation_allowlist():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.TICKETING,
        operation="create_ticket",
    )
    policy = ConnectorPermissionPolicy(
        description="Read-only ticketing",
        allowed_operations=["read_ticket"],
    )
    assert evaluate_permission(request, [policy]) is False


@pytest.mark.asyncio
async def test_connector_service_permission_denied_returns_result():
    registry = ConnectorRegistry()
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.SEARCH,
        provider_id="p1",
        permission_policies=[
            ConnectorPermissionPolicy(
                description="Deny all search",
                denied_capability_types=[CapabilityType.SEARCH],
            )
        ],
    )
    registry.register_config(config)
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])
    registry.register_provider(mock_provider)
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={},
    )
    assert result.status == ConnectorStatus.PERMISSION_DENIED
    assert "Denied" in result.error_message


# ---- No domain-specific assumptions ----


def test_no_domain_specific_assumptions_in_models():
    """Core connector models must not contain domain-specific field names."""
    import agent_orchestrator.connectors as connector_module

    domain_terms = {
        "research", "security", "development", "incident", "vulnerability",
        "code_review", "finding", "threat", "breach", "pull_request",
        "deployment", "patient", "invoice", "customer",
    }
    for name, obj in inspect.getmembers(connector_module):
        if inspect.isclass(obj) and hasattr(obj, "model_fields"):
            for field_name in obj.model_fields:
                for term in domain_terms:
                    assert term not in field_name.lower(), (
                        f"Domain-specific term '{term}' found in {name}.{field_name}"
                    )


def test_connector_permission_error_is_importable():
    # Verify ConnectorPermissionError is importable and is an Exception subclass
    assert issubclass(ConnectorPermissionError, Exception)


def test_connector_service_error_inherits_orchestrator_error():
    from agent_orchestrator.exceptions import OrchestratorError
    assert issubclass(ConnectorServiceError, OrchestratorError)


# ---- Phase 10: New model tests ----


def test_connector_retry_policy_defaults():
    policy = ConnectorRetryPolicy()
    assert policy.max_retries == 0
    assert policy.delay_seconds == 1.0
    assert policy.backoff_multiplier == 2.0


def test_connector_rate_limit_model():
    rate_limit = ConnectorRateLimit(max_requests_per_minute=60, max_cost_per_hour=1.0)
    assert rate_limit.max_requests_per_minute == 60


def test_connector_provider_descriptor_new_fields():
    desc = ConnectorProviderDescriptor(
        provider_id="versioned-provider",
        display_name="Versioned",
        capability_types=[CapabilityType.SEARCH],
        version="1.2.0",
        auth_required=True,
        parameter_schemas={"query": {"q": "string"}},
    )
    assert desc.version == "1.2.0"
    assert desc.auth_required is True


def test_connector_config_new_fields():
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.SEARCH,
        provider_id="p1",
        retry_policy=ConnectorRetryPolicy(max_retries=2),
        rate_limit=ConnectorRateLimit(max_requests_per_minute=30),
        version="2.0",
    )
    assert config.retry_policy.max_retries == 2
    assert config.rate_limit.max_requests_per_minute == 30


# ---- Phase 10: ConnectorExecutionTrace and ConnectorTraceStore tests ----


def test_execution_trace_model():
    trace = ConnectorExecutionTrace(
        request_id="req-1",
        connector_id="c1",
        provider="p1",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
        duration_ms=42.0,
    )
    assert trace.trace_id is not None
    assert trace.attempt_number == 1


def test_trace_store_record_and_query():
    store = ConnectorTraceStore()
    trace = ConnectorExecutionTrace(
        request_id="req-1",
        run_id="run-1",
        connector_id="c1",
        provider="p1",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
    )
    store.record(trace)
    results = store.query(run_id="run-1")
    assert len(results) == 1
    assert results[0].run_id == "run-1"


def test_trace_store_limit():
    store = ConnectorTraceStore(max_entries=3)
    for i in range(5):
        store.record(ConnectorExecutionTrace(
            request_id=f"req-{i}",
            connector_id="c1",
            provider="p1",
            capability_type=CapabilityType.SEARCH,
            operation="query",
            status=ConnectorStatus.SUCCESS,
        ))
    assert len(store.query(limit=100)) == 3


def test_trace_store_summary():
    store = ConnectorTraceStore()
    store.record(ConnectorExecutionTrace(
        request_id="r1",
        connector_id="c1",
        provider="p1",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
    ))
    summary = store.get_summary()
    assert summary["total_traces"] == 1
    assert "success" in summary["by_status"]


# ---- Phase 10: ConnectorExecutor tests ----


@pytest.mark.asyncio
async def test_executor_success():
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])
    mock_provider.execute = AsyncMock(return_value=ConnectorInvocationResult(
        request_id="req-1",
        connector_id="p1",
        provider="p1",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
    ))
    executor = ConnectorExecutor()
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    result = await executor.execute(mock_provider, request)
    assert result.status == ConnectorStatus.SUCCESS


@pytest.mark.asyncio
async def test_executor_timeout():
    import asyncio
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])

    async def slow_execute(req):
        await asyncio.sleep(10)

    mock_provider.execute = slow_execute
    executor = ConnectorExecutor()
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        timeout_seconds=0.01,
    )
    result = await executor.execute(mock_provider, request)
    assert result.status == ConnectorStatus.TIMEOUT


@pytest.mark.asyncio
async def test_executor_retry_on_failure():
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])
    call_count = 0

    async def flaky_execute(req):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return ConnectorInvocationResult(
                request_id=req.request_id,
                connector_id="p1",
                provider="p1",
                capability_type=CapabilityType.SEARCH,
                operation="query",
                status=ConnectorStatus.FAILURE,
                error_message="flaky",
            )
        return ConnectorInvocationResult(
            request_id=req.request_id,
            connector_id="p1",
            provider="p1",
            capability_type=CapabilityType.SEARCH,
            operation="query",
            status=ConnectorStatus.SUCCESS,
        )

    mock_provider.execute = flaky_execute
    executor = ConnectorExecutor()
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    retry_policy = ConnectorRetryPolicy(max_retries=3, delay_seconds=0.001)
    result = await executor.execute(mock_provider, request, retry_policy=retry_policy)
    assert result.status == ConnectorStatus.SUCCESS
    assert call_count == 3


@pytest.mark.asyncio
async def test_executor_records_traces():
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])
    mock_provider.execute = AsyncMock(return_value=ConnectorInvocationResult(
        request_id="req-1",
        connector_id="p1",
        provider="p1",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
    ))
    trace_store = ConnectorTraceStore()
    executor = ConnectorExecutor(trace_store=trace_store)
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        context={"run_id": "r1"},
    )
    await executor.execute(mock_provider, request)
    traces = trace_store.query()
    assert len(traces) == 1
    assert traces[0].run_id == "r1"


@pytest.mark.asyncio
async def test_executor_records_cost_metrics():
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])
    mock_provider.execute = AsyncMock(return_value=ConnectorInvocationResult(
        request_id="req-1",
        connector_id="p1",
        provider="p1",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
        cost_info=ConnectorCostInfo(request_cost=0.01, usage_units=100),
    ))
    mock_metrics = MagicMock()
    executor = ConnectorExecutor(metrics=mock_metrics)
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    await executor.execute(mock_provider, request)
    assert mock_metrics.record.called


@pytest.mark.asyncio
async def test_executor_exception_normalized_to_failure():
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])
    mock_provider.execute = AsyncMock(side_effect=RuntimeError("boom"))
    executor = ConnectorExecutor()
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    result = await executor.execute(mock_provider, request)
    assert result.status == ConnectorStatus.FAILURE
    assert "boom" in result.error_message


# ---- Phase 10: Registry operation-based lookup tests ----


def test_registry_find_provider_for_operation_with_declared_ops():
    registry = ConnectorRegistry()
    mock = MagicMock()
    mock.get_descriptor.return_value = ConnectorProviderDescriptor(
        provider_id="p1",
        display_name="P1",
        capability_types=[CapabilityType.SEARCH],
        operations=[ConnectorOperationDescriptor(
            operation="query",
            description="Search query",
            capability_type=CapabilityType.SEARCH,
        )],
        enabled=True,
    )
    registry.register_provider(mock)
    result = registry.find_provider_for_operation(CapabilityType.SEARCH, "query")
    assert result is mock


def test_registry_find_provider_for_operation_fallback():
    registry = ConnectorRegistry()
    mock = _make_mock_provider("p1", [CapabilityType.SEARCH])
    registry.register_provider(mock)
    # Provider has no declared operations — falls back to first enabled
    result = registry.find_provider_for_operation(CapabilityType.SEARCH, "anything")
    assert result is mock


def test_registry_find_provider_for_operation_preferred():
    registry = ConnectorRegistry()
    p1 = _make_mock_provider("p1", [CapabilityType.SEARCH])
    p2 = _make_mock_provider("p2", [CapabilityType.SEARCH])
    registry.register_provider(p1)
    registry.register_provider(p2)
    result = registry.find_provider_for_operation(
        CapabilityType.SEARCH, "query", preferred_provider="p2"
    )
    assert result.get_descriptor().provider_id == "p2"


# ---- Phase 10: Service with new features ----


@pytest.mark.asyncio
async def test_connector_service_get_traces():
    registry = ConnectorRegistry()
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])
    mock_provider.execute = AsyncMock(return_value=ConnectorInvocationResult(
        request_id="req-1",
        connector_id="p1",
        provider="p1",
        capability_type=CapabilityType.SEARCH,
        operation="query",
        status=ConnectorStatus.SUCCESS,
    ))
    registry.register_provider(mock_provider)
    service = ConnectorService(registry=registry)
    await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={},
        context={"run_id": "r1"},
    )
    traces = service.get_traces(run_id="r1")
    assert len(traces) == 1


@pytest.mark.asyncio
async def test_connector_service_get_trace_summary():
    registry = ConnectorRegistry()
    service = ConnectorService(registry=registry)
    summary = service.get_trace_summary()
    assert "total_traces" in summary


def test_connector_service_get_configs():
    registry = ConnectorRegistry()
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.SEARCH,
        provider_id="p1",
    )
    registry.register_config(config)
    service = ConnectorService(registry=registry)
    configs = service.get_configs()
    assert len(configs) == 1
    assert configs[0].connector_id == "c1"


@pytest.mark.asyncio
async def test_connector_service_uses_retry_from_config():
    """Service picks up retry policy from ConnectorConfig."""
    registry = ConnectorRegistry()
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.SEARCH,
        provider_id="p1",
        retry_policy=ConnectorRetryPolicy(max_retries=1, delay_seconds=0.001),
    )
    registry.register_config(config)
    call_count = 0
    mock_provider = _make_mock_provider("p1", [CapabilityType.SEARCH])

    async def flaky(req):
        nonlocal call_count
        call_count += 1
        return ConnectorInvocationResult(
            request_id=req.request_id,
            connector_id="p1",
            provider="p1",
            capability_type=CapabilityType.SEARCH,
            operation="query",
            status=ConnectorStatus.FAILURE,
            error_message="err",
        )

    mock_provider.execute = flaky
    registry.register_provider(mock_provider)
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type=CapabilityType.SEARCH,
        operation="query",
        parameters={},
    )
    assert result.status == ConnectorStatus.FAILURE
    assert call_count == 2  # initial + 1 retry


def test_connector_executor_error_inherits_orchestrator_error():
    from agent_orchestrator.exceptions import OrchestratorError
    assert issubclass(ConnectorExecutorError, OrchestratorError)


# ---- Auth abstraction tests ----


def test_auth_type_values():
    assert AuthType.NONE.value == "none"
    assert AuthType.API_KEY.value == "api_key"
    assert AuthType.BEARER_TOKEN.value == "bearer_token"
    assert AuthType.OAUTH2.value == "oauth2"
    assert AuthType.BASIC.value == "basic"
    assert AuthType.CUSTOM.value == "custom"


def test_connector_auth_config_defaults():
    config = ConnectorAuthConfig()
    assert config.auth_type == AuthType.NONE
    assert config.credential_env_var is None
    assert config.scopes == []


def test_connector_auth_config_api_key():
    config = ConnectorAuthConfig(
        auth_type=AuthType.API_KEY,
        credential_env_var="MY_SERVICE_API_KEY",
        credential_header="X-API-Key",
    )
    assert config.auth_type == AuthType.API_KEY
    assert config.credential_env_var == "MY_SERVICE_API_KEY"
    assert config.credential_header == "X-API-Key"


def test_build_session_context_returns_none_for_none_config():
    assert build_session_context(None) is None


def test_build_session_context_returns_none_for_auth_none():
    config = ConnectorAuthConfig(auth_type=AuthType.NONE)
    assert build_session_context(config) is None


def test_build_session_context_api_key():
    config = ConnectorAuthConfig(
        auth_type=AuthType.API_KEY,
        credential_env_var="MY_KEY",
    )
    ctx = build_session_context(config)
    assert ctx is not None
    assert ctx.auth_type == AuthType.API_KEY
    assert ctx.credential_env_var == "MY_KEY"


def test_session_context_to_log_summary_hides_credentials():
    ctx = ConnectorSessionContext(
        auth_type=AuthType.API_KEY,
        credential_env_var="SECRET_KEY",
    )
    summary = ctx.to_log_summary()
    assert "SECRET_KEY" not in str(summary)
    assert summary["has_credential_env_var"] is True
    assert summary["auth_type"] == "api_key"


def test_connector_auth_config_is_frozen():
    config = ConnectorAuthConfig(auth_type=AuthType.API_KEY)
    with pytest.raises(Exception):
        config.auth_type = AuthType.NONE  # type: ignore[misc]


# ---- Normalized artifact tests ----


def test_search_result_artifact():
    artifact = SearchResultArtifact(
        source_connector="search-conn",
        provider="search-p",
        query="test query",
        results=[
            SearchResultItem(rank=1, title="Result 1", snippet="A snippet", url="https://example.com"),
        ],
        total_count=1,
    )
    assert artifact.capability_type == CapabilityType.SEARCH
    assert len(artifact.results) == 1
    assert artifact.results[0].rank == 1
    assert artifact.artifact_id is not None


def test_document_artifact():
    artifact = DocumentArtifact(
        source_connector="docs-conn",
        provider="docs-p",
        title="My Doc",
        content="Hello world",
        content_type="text/plain",
    )
    assert artifact.capability_type == CapabilityType.DOCUMENTS
    assert artifact.content == "Hello world"


def test_message_artifact():
    artifact = MessageArtifact(
        source_connector="msg-conn",
        provider="msg-p",
        channel="#general",
        sender="user@example.com",
        body="Hello team",
    )
    assert artifact.capability_type == CapabilityType.MESSAGING
    assert artifact.channel == "#general"


def test_ticket_artifact():
    artifact = TicketArtifact(
        source_connector="ticket-conn",
        provider="ticket-p",
        ticket_id="TICKET-42",
        title="Fix the bug",
        status="open",
        priority="high",
    )
    assert artifact.capability_type == CapabilityType.TICKETING
    assert artifact.ticket_id == "TICKET-42"


def test_repository_artifact():
    artifact = RepositoryArtifact(
        source_connector="repo-conn",
        provider="repo-p",
        name="my-repo",
        url="https://github.com/org/my-repo",
        default_branch="main",
    )
    assert artifact.capability_type == CapabilityType.REPOSITORY
    assert artifact.name == "my-repo"


def test_telemetry_artifact():
    artifact = TelemetryArtifact(
        source_connector="tel-conn",
        provider="tel-p",
        metric_name="cpu.usage",
        value=42.5,
        unit="percent",
        labels={"host": "server-1"},
    )
    assert artifact.capability_type == CapabilityType.TELEMETRY
    assert artifact.value == 42.5


def test_identity_artifact():
    artifact = IdentityArtifact(
        source_connector="id-conn",
        provider="id-p",
        principal_id="user-123",
        display_name="Test User",
        email="user@example.com",
        roles=["admin", "viewer"],
    )
    assert artifact.capability_type == CapabilityType.IDENTITY
    assert "admin" in artifact.roles


def test_normalized_artifacts_are_frozen():
    artifact = SearchResultArtifact(
        source_connector="c",
        provider="p",
        query="q",
    )
    with pytest.raises(Exception):
        artifact.query = "mutated"  # type: ignore[misc]


def test_get_normalized_type():
    assert get_normalized_type(CapabilityType.SEARCH) is SearchResultArtifact
    assert get_normalized_type(CapabilityType.DOCUMENTS) is DocumentArtifact
    assert get_normalized_type(CapabilityType.MESSAGING) is MessageArtifact
    assert get_normalized_type(CapabilityType.TICKETING) is TicketArtifact
    assert get_normalized_type(CapabilityType.REPOSITORY) is RepositoryArtifact
    assert get_normalized_type(CapabilityType.TELEMETRY) is TelemetryArtifact
    assert get_normalized_type(CapabilityType.IDENTITY) is IdentityArtifact
    assert get_normalized_type(CapabilityType.EXTERNAL_API) is None
    assert get_normalized_type(CapabilityType.FILE_STORAGE) is not None  # FileStorageArtifact added
    assert get_normalized_type(CapabilityType.WORKFLOW_ACTION) is None


def test_try_normalize_search():
    result = try_normalize(
        payload={"query": "test"},
        capability_type=CapabilityType.SEARCH,
        source_connector="s",
        provider="p",
    )
    assert isinstance(result, SearchResultArtifact)


def test_try_normalize_no_schema():
    result = try_normalize(
        payload={"data": 1},
        capability_type=CapabilityType.EXTERNAL_API,
        source_connector="s",
        provider="p",
    )
    assert result is None


def test_try_normalize_bad_payload_returns_none():
    # Missing required fields — should not raise, just return None
    result = try_normalize(
        payload={"unexpected_field": "value"},
        capability_type=CapabilityType.TICKETING,  # ticket_id required
        source_connector="s",
        provider="p",
    )
    assert result is None


def test_normalized_artifacts_have_no_domain_terms():
    """Normalized artifact models must not contain domain-specific field names."""
    import agent_orchestrator.connectors.normalized as norm_module
    domain_terms = {
        "threat", "incident", "vulnerability", "breach",
        "malware", "patient", "invoice", "shipment",
    }
    for name, obj in inspect.getmembers(norm_module):
        if inspect.isclass(obj) and hasattr(obj, "model_fields"):
            for field_name in obj.model_fields:
                for term in domain_terms:
                    assert term not in field_name.lower(), (
                        f"Domain term '{term}' found in {name}.{field_name}"
                    )


# ---- PermissionEvaluationResult tests ----


def test_permission_detailed_allows_by_default():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    result = evaluate_permission_detailed(request, [])
    assert result.outcome == PermissionOutcome.ALLOW
    assert result.matched_policy_id is None


def test_permission_detailed_deny_capability():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="query",
    )
    policy = ConnectorPermissionPolicy(
        description="Block search",
        denied_capability_types=[CapabilityType.SEARCH],
    )
    result = evaluate_permission_detailed(request, [policy])
    assert result.outcome == PermissionOutcome.DENY
    assert result.matched_policy_id == policy.policy_id


def test_permission_detailed_requires_approval_for_write():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.TICKETING,
        operation="create_ticket",
    )
    policy = ConnectorPermissionPolicy(
        description="Write requires approval",
        requires_approval=True,
        allowed_capability_types=[CapabilityType.TICKETING],
    )
    result = evaluate_permission_detailed(request, [policy])
    assert result.outcome == PermissionOutcome.REQUIRES_APPROVAL


def test_permission_detailed_read_ops_not_gated_by_approval():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.TICKETING,
        operation="get_ticket",
    )
    policy = ConnectorPermissionPolicy(
        description="Write requires approval",
        requires_approval=True,
        allowed_capability_types=[CapabilityType.TICKETING],
    )
    result = evaluate_permission_detailed(request, [policy])
    assert result.outcome == PermissionOutcome.ALLOW


def test_permission_detailed_deny_operation():
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.TICKETING,
        operation="delete_ticket",
    )
    policy = ConnectorPermissionPolicy(
        description="No deletes",
        denied_operations=["delete_ticket"],
    )
    result = evaluate_permission_detailed(request, [policy])
    assert result.outcome == PermissionOutcome.DENY


def test_permission_policy_requires_approval_field():
    policy = ConnectorPermissionPolicy(
        description="Approval required",
        requires_approval=True,
    )
    assert policy.requires_approval is True


def test_permission_policy_requires_approval_default_false():
    policy = ConnectorPermissionPolicy(description="Normal policy")
    assert policy.requires_approval is False


# ---- Service REQUIRES_APPROVAL tests ----


@pytest.mark.asyncio
async def test_connector_service_requires_approval_status():
    registry = ConnectorRegistry()
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.TICKETING,
        provider_id="p1",
        permission_policies=[
            ConnectorPermissionPolicy(
                description="Write requires approval",
                requires_approval=True,
                allowed_capability_types=[CapabilityType.TICKETING],
            )
        ],
    )
    registry.register_config(config)
    mock_provider = _make_mock_provider("p1", [CapabilityType.TICKETING])
    registry.register_provider(mock_provider)
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type=CapabilityType.TICKETING,
        operation="create_ticket",
        parameters={},
    )
    assert result.status == ConnectorStatus.REQUIRES_APPROVAL


@pytest.mark.asyncio
async def test_connector_service_reads_bypass_approval():
    registry = ConnectorRegistry()
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.TICKETING,
        provider_id="p1",
        permission_policies=[
            ConnectorPermissionPolicy(
                description="Write requires approval",
                requires_approval=True,
                allowed_capability_types=[CapabilityType.TICKETING],
            )
        ],
    )
    registry.register_config(config)
    mock_provider = _make_mock_provider("p1", [CapabilityType.TICKETING])
    mock_provider.execute = AsyncMock(return_value=ConnectorInvocationResult(
        request_id="req-1",
        connector_id="p1",
        provider="p1",
        capability_type=CapabilityType.TICKETING,
        operation="get_ticket",
        status=ConnectorStatus.SUCCESS,
    ))
    registry.register_provider(mock_provider)
    service = ConnectorService(registry=registry)
    result = await service.execute(
        capability_type=CapabilityType.TICKETING,
        operation="get_ticket",
        parameters={},
    )
    assert result.status == ConnectorStatus.SUCCESS


# ---- ConnectorCostMetadata tests ----


def test_connector_cost_metadata_model():
    from agent_orchestrator.connectors import ConnectorCostMetadata
    metadata = ConnectorCostMetadata(
        billing_label="search-prod",
        cost_center="engineering",
        unit_price=0.001,
        currency="USD",
    )
    assert metadata.billing_label == "search-prod"
    assert metadata.cost_center == "engineering"


def test_connector_config_with_cost_metadata():
    from agent_orchestrator.connectors import ConnectorCostMetadata
    config = ConnectorConfig(
        connector_id="c1",
        display_name="C1",
        capability_type=CapabilityType.SEARCH,
        provider_id="p1",
        cost_metadata=ConnectorCostMetadata(billing_label="search-prod"),
    )
    assert config.cost_metadata.billing_label == "search-prod"


def test_connector_status_requires_approval_value():
    assert ConnectorStatus.REQUIRES_APPROVAL.value == "requires_approval"
