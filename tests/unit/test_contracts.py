"""Tests for the Contract Framework (capability and artifact contracts)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_orchestrator.contracts import (
    ArtifactContract,
    ArtifactValidationRule,
    AuditRequirement,
    CapabilityContract,
    ContractRegistry,
    ContractRetryPolicy,
    ContractTimeoutPolicy,
    ContractValidationResult,
    ContractValidator,
    ContractViolation,
    ContractViolationSeverity,
    FailureSemantic,
    LifecycleState,
    ReadWriteClassification,
)
from agent_orchestrator.exceptions import ContractError, ContractViolationError


# ============================================================
# Model instantiation
# ============================================================


class TestCapabilityContractModel:
    def test_minimal_contract_creation(self):
        contract = CapabilityContract(
            contract_id="c1",
            capability_type="search",
            operation_name="query",
        )
        assert contract.contract_id == "c1"
        assert contract.capability_type == "search"
        assert contract.operation_name == "query"
        assert contract.description == ""
        assert contract.input_schema == {}
        assert contract.output_schema == {}

    def test_default_enums(self):
        contract = CapabilityContract(
            contract_id="c2",
            capability_type="search",
            operation_name="query",
        )
        assert contract.read_write_classification == ReadWriteClassification.READ_ONLY
        assert contract.audit_requirements == AuditRequirement.INVOCATION
        assert contract.failure_semantics == FailureSemantic.WARN_ONLY
        assert contract.cost_reporting_required is False

    def test_full_contract_creation(self):
        contract = CapabilityContract(
            contract_id="c3",
            capability_type="ticketing",
            operation_name="create_issue",
            description="Creates a ticket",
            input_schema={"required": ["title"], "properties": {"title": {"type": "string"}}},
            output_schema={"required": ["ticket_id"]},
            read_write_classification=ReadWriteClassification.WRITE_ONLY,
            permission_requirements=["ticketing:write"],
            timeout_policy=ContractTimeoutPolicy(timeout_seconds=30.0),
            retry_policy=ContractRetryPolicy(max_retries=2),
            audit_requirements=AuditRequirement.FULL,
            cost_reporting_required=True,
            failure_semantics=FailureSemantic.FAIL_FAST,
            metadata={"owner": "platform"},
        )
        assert contract.read_write_classification == ReadWriteClassification.WRITE_ONLY
        assert contract.permission_requirements == ["ticketing:write"]
        assert contract.timeout_policy.timeout_seconds == 30.0
        assert contract.retry_policy.max_retries == 2
        assert contract.cost_reporting_required is True

    def test_contract_is_frozen(self):
        contract = CapabilityContract(
            contract_id="c4",
            capability_type="search",
            operation_name="query",
        )
        with pytest.raises(Exception):
            contract.contract_id = "modified"  # type: ignore[misc]

    def test_auto_generated_contract_id(self):
        c1 = CapabilityContract(capability_type="search", operation_name="query")
        c2 = CapabilityContract(capability_type="search", operation_name="query")
        assert c1.contract_id != c2.contract_id


class TestArtifactContractModel:
    def test_minimal_artifact_contract(self):
        contract = ArtifactContract(
            contract_id="a1",
            artifact_type="search_result",
        )
        assert contract.contract_id == "a1"
        assert contract.artifact_type == "search_result"
        assert contract.required_fields == []
        assert contract.validation_rules == []

    def test_full_artifact_contract(self):
        rule = ArtifactValidationRule(
            field="title",
            rule_type="min_length",
            parameters={"value": 1},
            message="Title cannot be empty",
        )
        contract = ArtifactContract(
            contract_id="a2",
            artifact_type="document",
            required_fields=["title", "content"],
            optional_fields=["summary"],
            validation_rules=[rule],
            provenance_requirements=["source_url"],
            lifecycle_state_model=[LifecycleState.DRAFT, LifecycleState.ACTIVE],
            producer_constraints=["researcher"],
            consumer_constraints=["reviewer"],
        )
        assert "title" in contract.required_fields
        assert len(contract.validation_rules) == 1
        assert contract.validation_rules[0].rule_type == "min_length"
        assert LifecycleState.ACTIVE in contract.lifecycle_state_model

    def test_artifact_contract_is_frozen(self):
        contract = ArtifactContract(contract_id="a3", artifact_type="doc")
        with pytest.raises(Exception):
            contract.artifact_type = "modified"  # type: ignore[misc]


class TestArtifactValidationRule:
    def test_rule_creation(self):
        rule = ArtifactValidationRule(
            field="status",
            rule_type="allowed_values",
            parameters={"values": ["open", "closed"]},
            message="Invalid status value",
            severity=ContractViolationSeverity.ERROR,
        )
        assert rule.field == "status"
        assert rule.rule_type == "allowed_values"
        assert rule.severity == ContractViolationSeverity.ERROR

    def test_auto_generated_rule_id(self):
        r1 = ArtifactValidationRule(field="f", rule_type="min_length", parameters={"value": 1})
        r2 = ArtifactValidationRule(field="f", rule_type="min_length", parameters={"value": 1})
        assert r1.rule_id != r2.rule_id


# ============================================================
# ContractRegistry
# ============================================================


class TestContractRegistry:
    def test_register_and_get_capability_contract(self):
        registry = ContractRegistry()
        contract = CapabilityContract(
            contract_id="r1",
            capability_type="search",
            operation_name="query",
        )
        registry.register_capability_contract(contract)
        result = registry.get_capability_contract("r1")
        assert result is not None
        assert result.contract_id == "r1"

    def test_get_nonexistent_capability_contract_returns_none(self):
        registry = ContractRegistry()
        assert registry.get_capability_contract("missing") is None

    def test_register_and_get_artifact_contract(self):
        registry = ContractRegistry()
        contract = ArtifactContract(contract_id="ar1", artifact_type="ticket")
        registry.register_artifact_contract(contract)
        result = registry.get_artifact_contract("ar1")
        assert result is not None
        assert result.artifact_type == "ticket"

    def test_get_nonexistent_artifact_contract_returns_none(self):
        registry = ContractRegistry()
        assert registry.get_artifact_contract("missing") is None

    def test_find_capability_contracts_matches_type_and_operation(self):
        registry = ContractRegistry()
        c1 = CapabilityContract(contract_id="fc1", capability_type="search", operation_name="query")
        c2 = CapabilityContract(contract_id="fc2", capability_type="search", operation_name="autocomplete")
        c3 = CapabilityContract(contract_id="fc3", capability_type="documents", operation_name="query")
        for c in (c1, c2, c3):
            registry.register_capability_contract(c)

        results = registry.find_capability_contracts("search", "query")
        assert len(results) == 1
        assert results[0].contract_id == "fc1"

    def test_find_capability_contracts_returns_empty_for_no_match(self):
        registry = ContractRegistry()
        assert registry.find_capability_contracts("search", "nonexistent") == []

    def test_find_artifact_contracts_matches_type(self):
        registry = ContractRegistry()
        a1 = ArtifactContract(contract_id="fa1", artifact_type="ticket")
        a2 = ArtifactContract(contract_id="fa2", artifact_type="document")
        registry.register_artifact_contract(a1)
        registry.register_artifact_contract(a2)

        results = registry.find_artifact_contracts("ticket")
        assert len(results) == 1
        assert results[0].contract_id == "fa1"

    def test_find_artifact_contracts_returns_empty_for_no_match(self):
        registry = ContractRegistry()
        assert registry.find_artifact_contracts("unknown_type") == []

    def test_list_capability_contracts(self):
        registry = ContractRegistry()
        for i in range(3):
            registry.register_capability_contract(
                CapabilityContract(contract_id=f"lc{i}", capability_type="search", operation_name=f"op{i}")
            )
        assert len(registry.list_capability_contracts()) == 3

    def test_list_artifact_contracts(self):
        registry = ContractRegistry()
        for i in range(2):
            registry.register_artifact_contract(
                ArtifactContract(contract_id=f"la{i}", artifact_type=f"type_{i}")
            )
        assert len(registry.list_artifact_contracts()) == 2

    def test_unregister_capability_contract_returns_true(self):
        registry = ContractRegistry()
        contract = CapabilityContract(contract_id="ur1", capability_type="search", operation_name="query")
        registry.register_capability_contract(contract)
        assert registry.unregister_capability_contract("ur1") is True
        assert registry.get_capability_contract("ur1") is None

    def test_unregister_capability_contract_returns_false_when_missing(self):
        registry = ContractRegistry()
        assert registry.unregister_capability_contract("missing") is False

    def test_unregister_artifact_contract_returns_true(self):
        registry = ContractRegistry()
        contract = ArtifactContract(contract_id="uar1", artifact_type="doc")
        registry.register_artifact_contract(contract)
        assert registry.unregister_artifact_contract("uar1") is True
        assert registry.get_artifact_contract("uar1") is None

    def test_unregister_artifact_contract_returns_false_when_missing(self):
        registry = ContractRegistry()
        assert registry.unregister_artifact_contract("missing") is False

    def test_re_registering_same_id_replaces_contract(self):
        registry = ContractRegistry()
        c1 = CapabilityContract(contract_id="dup1", capability_type="search", operation_name="query")
        c2 = CapabilityContract(contract_id="dup1", capability_type="search", operation_name="query", description="v2")
        registry.register_capability_contract(c1)
        registry.register_capability_contract(c2)
        result = registry.get_capability_contract("dup1")
        assert result.description == "v2"

    def test_summary(self):
        registry = ContractRegistry()
        registry.register_capability_contract(
            CapabilityContract(contract_id="s1", capability_type="search", operation_name="query")
        )
        registry.register_artifact_contract(
            ArtifactContract(contract_id="s2", artifact_type="doc")
        )
        summary = registry.summary()
        assert summary["capability_contracts"] == 1
        assert summary["artifact_contracts"] == 1
        assert "s1" in summary["capability_contract_ids"]
        assert "s2" in summary["artifact_contract_ids"]


# ============================================================
# ContractValidator
# ============================================================


@pytest.fixture()
def registry():
    return ContractRegistry()


@pytest.fixture()
def validator(registry):
    return ContractValidator(registry)


class TestContractValidatorCapabilityInput:
    def test_returns_none_when_no_contract_registered(self, validator):
        result = validator.validate_capability_input("search", "query", {"q": "test"})
        assert result is None

    def test_valid_input_passes(self, registry, validator):
        contract = CapabilityContract(
            contract_id="v1",
            capability_type="search",
            operation_name="query",
            input_schema={"required": ["q"], "properties": {"q": {"type": "string"}}},
        )
        registry.register_capability_contract(contract)
        result = validator.validate_capability_input("search", "query", {"q": "hello"})
        assert result is not None
        assert result.is_valid is True
        assert result.violations == []

    def test_missing_required_field_fails(self, registry, validator):
        contract = CapabilityContract(
            contract_id="v2",
            capability_type="search",
            operation_name="query",
            input_schema={"required": ["q"]},
        )
        registry.register_capability_contract(contract)
        result = validator.validate_capability_input("search", "query", {})
        assert result is not None
        assert result.is_valid is False
        assert any(v.field == "q" for v in result.violations)

    def test_type_mismatch_fails(self, registry, validator):
        contract = CapabilityContract(
            contract_id="v3",
            capability_type="search",
            operation_name="query",
            input_schema={"properties": {"limit": {"type": "integer"}}},
        )
        registry.register_capability_contract(contract)
        result = validator.validate_capability_input("search", "query", {"limit": "not-a-number"})
        assert result is not None
        assert result.is_valid is False
        assert any(v.violation_type == "type_mismatch" for v in result.violations)

    def test_extra_fields_are_allowed(self, registry, validator):
        contract = CapabilityContract(
            contract_id="v4",
            capability_type="search",
            operation_name="query",
            input_schema={"required": ["q"]},
        )
        registry.register_capability_contract(contract)
        result = validator.validate_capability_input(
            "search", "query", {"q": "test", "extra_field": 123}
        )
        assert result.is_valid is True

    def test_empty_schema_always_passes(self, registry, validator):
        contract = CapabilityContract(
            contract_id="v5",
            capability_type="search",
            operation_name="query",
            input_schema={},
        )
        registry.register_capability_contract(contract)
        result = validator.validate_capability_input("search", "query", {})
        assert result.is_valid is True


class TestContractValidatorCapabilityOutput:
    def test_returns_none_when_no_contract_registered(self, validator):
        result = validator.validate_capability_output("search", "query", {"results": []})
        assert result is None

    def test_valid_output_passes(self, registry, validator):
        contract = CapabilityContract(
            contract_id="vo1",
            capability_type="search",
            operation_name="query",
            output_schema={"required": ["results"]},
        )
        registry.register_capability_contract(contract)
        result = validator.validate_capability_output("search", "query", {"results": []})
        assert result.is_valid is True

    def test_missing_output_field_fails(self, registry, validator):
        contract = CapabilityContract(
            contract_id="vo2",
            capability_type="search",
            operation_name="query",
            output_schema={"required": ["results", "total_count"]},
        )
        registry.register_capability_contract(contract)
        result = validator.validate_capability_output("search", "query", {"results": []})
        assert result.is_valid is False
        fields = [v.field for v in result.violations]
        assert "total_count" in fields


class TestContractValidatorArtifact:
    def test_returns_none_when_no_contract_registered(self, validator):
        result = validator.validate_artifact("unknown_type", {"key": "value"})
        assert result is None

    def test_valid_artifact_passes(self, registry, validator):
        contract = ArtifactContract(
            contract_id="av1",
            artifact_type="ticket",
            required_fields=["title", "priority"],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {"title": "Bug", "priority": "high"})
        assert result.is_valid is True

    def test_missing_required_field_fails(self, registry, validator):
        contract = ArtifactContract(
            contract_id="av2",
            artifact_type="ticket",
            required_fields=["title", "priority"],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {"title": "Bug"})
        assert result.is_valid is False
        assert any(v.field == "priority" for v in result.violations)
        assert any(v.violation_type == "missing_required_field" for v in result.violations)

    def test_validation_rule_min_length_fails(self, registry, validator):
        rule = ArtifactValidationRule(
            field="title",
            rule_type="min_length",
            parameters={"value": 5},
            message="Title too short",
        )
        contract = ArtifactContract(
            contract_id="av3",
            artifact_type="ticket",
            required_fields=["title"],
            validation_rules=[rule],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {"title": "Hi"})
        assert result.is_valid is False
        assert any(v.violation_type == "min_length" for v in result.violations)

    def test_validation_rule_max_length_passes(self, registry, validator):
        rule = ArtifactValidationRule(
            field="title",
            rule_type="max_length",
            parameters={"value": 100},
        )
        contract = ArtifactContract(
            contract_id="av4",
            artifact_type="ticket",
            required_fields=["title"],
            validation_rules=[rule],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {"title": "Short title"})
        assert result.is_valid is True

    def test_validation_rule_allowed_values_fails(self, registry, validator):
        rule = ArtifactValidationRule(
            field="status",
            rule_type="allowed_values",
            parameters={"values": ["open", "closed"]},
            message="Invalid status",
        )
        contract = ArtifactContract(
            contract_id="av5",
            artifact_type="ticket",
            required_fields=["status"],
            validation_rules=[rule],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {"status": "pending"})
        assert result.is_valid is False

    def test_validation_rule_allowed_values_passes(self, registry, validator):
        rule = ArtifactValidationRule(
            field="status",
            rule_type="allowed_values",
            parameters={"values": ["open", "closed"]},
        )
        contract = ArtifactContract(
            contract_id="av6",
            artifact_type="ticket",
            required_fields=["status"],
            validation_rules=[rule],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {"status": "open"})
        assert result.is_valid is True

    def test_validation_rule_pattern_fails(self, registry, validator):
        rule = ArtifactValidationRule(
            field="code",
            rule_type="pattern",
            parameters={"regex": r"[A-Z]{3}-\d{4}"},
            message="Invalid code format",
        )
        contract = ArtifactContract(
            contract_id="av7",
            artifact_type="release",
            required_fields=["code"],
            validation_rules=[rule],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("release", {"code": "abc-1234"})
        assert result.is_valid is False

    def test_validation_rule_pattern_passes(self, registry, validator):
        rule = ArtifactValidationRule(
            field="code",
            rule_type="pattern",
            parameters={"regex": r"[A-Z]{3}-\d{4}"},
        )
        contract = ArtifactContract(
            contract_id="av8",
            artifact_type="release",
            required_fields=["code"],
            validation_rules=[rule],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("release", {"code": "ABC-1234"})
        assert result.is_valid is True

    def test_required_if_rule_triggers(self, registry, validator):
        rule = ArtifactValidationRule(
            field="resolution",
            rule_type="required_if",
            parameters={"condition_field": "status", "condition_value": "closed"},
            message="resolution required when status=closed",
        )
        contract = ArtifactContract(
            contract_id="av9",
            artifact_type="ticket",
            required_fields=["status"],
            validation_rules=[rule],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {"status": "closed"})
        assert result.is_valid is False

    def test_required_if_rule_does_not_trigger_when_condition_unmet(self, registry, validator):
        rule = ArtifactValidationRule(
            field="resolution",
            rule_type="required_if",
            parameters={"condition_field": "status", "condition_value": "closed"},
        )
        contract = ArtifactContract(
            contract_id="av10",
            artifact_type="ticket",
            required_fields=["status"],
            validation_rules=[rule],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {"status": "open"})
        assert result.is_valid is True

    def test_multiple_violations_collected(self, registry, validator):
        contract = ArtifactContract(
            contract_id="av11",
            artifact_type="ticket",
            required_fields=["title", "priority", "status"],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {})
        assert result.is_valid is False
        assert len(result.violations) == 3

    def test_validation_result_contains_contract_id(self, registry, validator):
        contract = ArtifactContract(
            contract_id="av12",
            artifact_type="ticket",
            required_fields=["title"],
        )
        registry.register_artifact_contract(contract)
        result = validator.validate_artifact("ticket", {})
        assert result.contract_id == "av12"
        assert all(v.contract_id == "av12" for v in result.violations)


class TestContractValidatorAuditLogging:
    def test_violations_logged_to_audit_logger(self, registry):
        audit_logger = MagicMock()
        validator = ContractValidator(registry, audit_logger=audit_logger)

        contract = CapabilityContract(
            contract_id="audit1",
            capability_type="search",
            operation_name="query",
            input_schema={"required": ["q"]},
        )
        registry.register_capability_contract(contract)

        result = validator.validate_capability_input("search", "query", {})
        assert result.is_valid is False
        audit_logger.append.assert_called_once()
        call_kwargs = audit_logger.append.call_args[1]
        assert call_kwargs["action"] == "contract_violation"
        assert "contract_id" in call_kwargs["data"]

    def test_no_audit_call_when_no_violations(self, registry):
        audit_logger = MagicMock()
        validator = ContractValidator(registry, audit_logger=audit_logger)

        contract = CapabilityContract(
            contract_id="audit2",
            capability_type="search",
            operation_name="query",
            input_schema={"required": ["q"]},
        )
        registry.register_capability_contract(contract)

        validator.validate_capability_input("search", "query", {"q": "test"})
        audit_logger.append.assert_not_called()

    def test_artifact_violations_logged(self, registry):
        audit_logger = MagicMock()
        validator = ContractValidator(registry, audit_logger=audit_logger)

        contract = ArtifactContract(
            contract_id="audit3",
            artifact_type="doc",
            required_fields=["title"],
        )
        registry.register_artifact_contract(contract)

        result = validator.validate_artifact("doc", {})
        assert result.is_valid is False
        audit_logger.append.assert_called_once()


# ============================================================
# Exceptions
# ============================================================


class TestContractExceptions:
    def test_contract_error_is_orchestrator_error(self):
        from agent_orchestrator.exceptions import OrchestratorError
        assert issubclass(ContractError, OrchestratorError)

    def test_contract_violation_error_is_contract_error(self):
        assert issubclass(ContractViolationError, ContractError)

    def test_contract_violation_error_can_be_raised(self):
        with pytest.raises(ContractViolationError):
            raise ContractViolationError("Input contract violation: missing field 'q'")


# ============================================================
# Domain extension — no platform core modification required
# ============================================================


class TestDomainExtension:
    """Demonstrates that domain modules extend contracts without touching platform code."""

    def test_domain_module_can_register_own_contracts(self):
        """A domain module creates a fresh registry and registers contracts."""
        domain_registry = ContractRegistry()

        # Domain-specific contract registered at domain startup
        domain_registry.register_capability_contract(
            CapabilityContract(
                contract_id="content-mod-classify-v1",
                capability_type="external_api",
                operation_name="classify_content",
                description="Content moderation classification contract",
                input_schema={
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string"},
                        "threshold": {"type": "number"},
                    },
                },
                output_schema={"required": ["label", "confidence"]},
                read_write_classification=ReadWriteClassification.READ_ONLY,
                audit_requirements=AuditRequirement.FULL,
            )
        )
        domain_registry.register_artifact_contract(
            ArtifactContract(
                contract_id="content-mod-verdict-v1",
                artifact_type="moderation_verdict",
                required_fields=["label", "confidence", "reviewed_at"],
                optional_fields=["reviewer_id", "notes"],
                lifecycle_state_model=[LifecycleState.DRAFT, LifecycleState.ACTIVE, LifecycleState.ARCHIVED],
            )
        )

        assert domain_registry.get_capability_contract("content-mod-classify-v1") is not None
        assert domain_registry.get_artifact_contract("content-mod-verdict-v1") is not None

    def test_domain_module_validation_works_independently(self):
        """A domain module can validate without touching platform core."""
        domain_registry = ContractRegistry()
        domain_registry.register_artifact_contract(
            ArtifactContract(
                contract_id="sw-dev-pr-v1",
                artifact_type="pull_request",
                required_fields=["title", "branch", "base_branch"],
            )
        )
        validator = ContractValidator(domain_registry)

        valid = validator.validate_artifact(
            "pull_request",
            {"title": "Fix bug", "branch": "fix/123", "base_branch": "main"},
        )
        assert valid.is_valid is True

        invalid = validator.validate_artifact("pull_request", {"title": "Fix bug"})
        assert invalid.is_valid is False
        missing = {v.field for v in invalid.violations}
        assert "branch" in missing
        assert "base_branch" in missing

    def test_multiple_domains_can_use_separate_registries(self):
        """Two domain modules can each have their own registry without interference."""
        registry_a = ContractRegistry()
        registry_b = ContractRegistry()

        registry_a.register_artifact_contract(
            ArtifactContract(contract_id="domain-a-contract", artifact_type="type_a")
        )
        registry_b.register_artifact_contract(
            ArtifactContract(contract_id="domain-b-contract", artifact_type="type_b")
        )

        assert registry_a.get_artifact_contract("domain-a-contract") is not None
        assert registry_a.get_artifact_contract("domain-b-contract") is None
        assert registry_b.get_artifact_contract("domain-b-contract") is not None
        assert registry_b.get_artifact_contract("domain-a-contract") is None


# ============================================================
# ConnectorService integration
# ============================================================


class TestConnectorServiceContractIntegration:
    """Verify contract validator hooks are invoked from ConnectorService."""

    @pytest.mark.asyncio
    async def test_service_passes_input_to_contract_validator(self):
        from unittest.mock import AsyncMock, MagicMock

        from agent_orchestrator.connectors import (
            CapabilityType,
            ConnectorRegistry,
            ConnectorService,
            ContractValidator,
        )

        registry = ConnectorRegistry()
        mock_validator = MagicMock(spec=ContractValidator)
        mock_validator.validate_capability_input.return_value = None
        mock_validator.validate_capability_output.return_value = None

        service = ConnectorService(registry=registry, contract_validator=mock_validator)

        # No providers registered — will return UNAVAILABLE without executing
        result = await service.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={"q": "test"},
            context={},
        )

        mock_validator.validate_capability_input.assert_called_once_with(
            "search", "query", {"q": "test"}, {}
        )

    @pytest.mark.asyncio
    async def test_service_without_contract_validator_still_works(self):
        from agent_orchestrator.connectors import (
            CapabilityType,
            ConnectorRegistry,
            ConnectorService,
        )

        registry = ConnectorRegistry()
        service = ConnectorService(registry=registry)
        result = await service.execute(
            capability_type=CapabilityType.SEARCH,
            operation="query",
            parameters={"q": "test"},
            context={},
        )
        # Should complete without error (UNAVAILABLE status)
        assert result.status.value in ("unavailable", "permission_denied")
