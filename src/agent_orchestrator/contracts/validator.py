"""Contract Validator — validation hooks for capability and artifact contracts.

Resolves registered contracts from the ContractRegistry and validates
payloads against them. Violations are logged clearly and optionally
recorded in the platform audit trail.

Validation is non-blocking by default: the validator logs failures and
returns a ContractValidationResult, but does NOT raise. Callers decide
how to handle the result based on CapabilityContract.failure_semantics.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .models import (
    ArtifactContract,
    ArtifactValidationRule,
    CapabilityContract,
    ContractValidationResult,
    ContractViolation,
    ContractViolationSeverity,
)
from .registry import ContractRegistry

if TYPE_CHECKING:
    from ..governance.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

_JSON_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


class ContractValidator:
    """Validates payloads against registered capability and artifact contracts.

    Inject an instance into ConnectorService or workflow execution components
    to enable contract enforcement. All validation methods return None when no
    matching contract is registered, so existing code remains unaffected.

    Usage::

        registry = ContractRegistry()
        registry.register_capability_contract(my_contract)

        validator = ContractValidator(registry, audit_logger=audit_logger)

        result = validator.validate_capability_input(
            capability_type="search",
            operation_name="query",
            input_payload={"q": "example"},
            context={"run_id": "r1"},
        )
        if result is not None and not result.is_valid:
            # handle violation per failure_semantics
            ...
    """

    def __init__(
        self,
        registry: ContractRegistry,
        audit_logger: "AuditLogger | None" = None,
    ) -> None:
        self._registry = registry
        self._audit_logger = audit_logger

    # ---- Capability input / output validation ----

    def validate_capability_input(
        self,
        capability_type: str,
        operation_name: str,
        input_payload: dict,
        context: dict | None = None,
    ) -> ContractValidationResult | None:
        """Validate connector input parameters against the registered capability contract.

        Args:
            capability_type: Capability type string (e.g. "search").
            operation_name: Operation name (e.g. "query").
            input_payload: The parameters dict being passed to the connector.
            context: Platform context for audit logging (run_id, work_id, etc.).

        Returns:
            ContractValidationResult if a contract is registered, else None.
        """
        contracts = self._registry.find_capability_contracts(capability_type, operation_name)
        if not contracts:
            return None

        contract = contracts[0]
        violations = self._validate_schema(
            input_payload, contract.input_schema, contract.contract_id
        )
        result = ContractValidationResult(
            is_valid=len(violations) == 0,
            contract_id=contract.contract_id,
            violations=violations,
        )
        if not result.is_valid:
            self._log_violation(contract, result, "capability_input", context or {})
        return result

    def validate_capability_output(
        self,
        capability_type: str,
        operation_name: str,
        output_payload: dict,
        context: dict | None = None,
    ) -> ContractValidationResult | None:
        """Validate connector output payload against the registered capability contract.

        Args:
            capability_type: Capability type string.
            operation_name: Operation name.
            output_payload: The payload dict returned by the connector.
            context: Platform context for audit logging.

        Returns:
            ContractValidationResult if a contract is registered, else None.
        """
        contracts = self._registry.find_capability_contracts(capability_type, operation_name)
        if not contracts:
            return None

        contract = contracts[0]
        violations = self._validate_schema(
            output_payload, contract.output_schema, contract.contract_id
        )
        result = ContractValidationResult(
            is_valid=len(violations) == 0,
            contract_id=contract.contract_id,
            violations=violations,
        )
        if not result.is_valid:
            self._log_violation(contract, result, "capability_output", context or {})
        return result

    # ---- Artifact validation ----

    def validate_artifact(
        self,
        artifact_type: str,
        artifact_payload: dict,
        context: dict | None = None,
    ) -> ContractValidationResult | None:
        """Validate an artifact payload against the registered artifact contract.

        Args:
            artifact_type: Artifact type string (e.g. "search_result").
            artifact_payload: The artifact data dict to validate.
            context: Platform context for audit logging.

        Returns:
            ContractValidationResult if a contract is registered, else None.
        """
        contracts = self._registry.find_artifact_contracts(artifact_type)
        if not contracts:
            return None

        contract = contracts[0]
        violations: list[ContractViolation] = []

        violations.extend(
            self._check_required_fields(
                artifact_payload, contract.required_fields, contract.contract_id
            )
        )
        violations.extend(
            self._check_provenance(
                artifact_payload, contract.provenance_requirements, contract.contract_id
            )
        )
        for rule in contract.validation_rules:
            violation = self._apply_rule(rule, artifact_payload, contract.contract_id)
            if violation is not None:
                violations.append(violation)

        result = ContractValidationResult(
            is_valid=len(violations) == 0,
            contract_id=contract.contract_id,
            violations=violations,
        )
        if not result.is_valid:
            self._log_artifact_violation(contract, result, context or {})
        return result

    # ---- Internal: schema validation ----

    def _validate_schema(
        self,
        payload: dict,
        schema: dict,
        contract_id: str,
    ) -> list[ContractViolation]:
        """Validate a dict payload against a JSON Schema fragment.

        Supports: required[], properties.{field}.type.
        """
        if not schema:
            return []

        violations: list[ContractViolation] = []

        required_fields: list[str] = schema.get("required", [])
        violations.extend(
            self._check_required_fields(payload, required_fields, contract_id)
        )

        properties: dict = schema.get("properties", {})
        for field_name, field_schema in properties.items():
            if field_name not in payload:
                continue
            expected_type = field_schema.get("type")
            if expected_type:
                v = self._check_type(
                    payload[field_name], expected_type, field_name, contract_id
                )
                if v is not None:
                    violations.append(v)

        return violations

    def _check_required_fields(
        self,
        payload: dict,
        required: list[str],
        contract_id: str,
    ) -> list[ContractViolation]:
        violations = []
        for field in required:
            if field not in payload:
                violations.append(
                    ContractViolation(
                        contract_id=contract_id,
                        violation_type="missing_required_field",
                        field=field,
                        message=f"Required field '{field}' is missing",
                    )
                )
        return violations

    def _check_provenance(
        self,
        payload: dict,
        provenance_requirements: list[str],
        contract_id: str,
    ) -> list[ContractViolation]:
        """Check provenance keys are present in the payload or its 'provenance' sub-dict."""
        if not provenance_requirements:
            return []
        provenance_data = payload if "provenance" not in payload else payload.get("provenance", {})
        violations = []
        for key in provenance_requirements:
            if key not in provenance_data and key not in payload:
                violations.append(
                    ContractViolation(
                        contract_id=contract_id,
                        violation_type="missing_provenance_field",
                        field=key,
                        message=f"Required provenance field '{key}' is missing",
                    )
                )
        return violations

    def _check_type(
        self,
        value: object,
        expected_type: str,
        field_name: str,
        contract_id: str,
    ) -> ContractViolation | None:
        py_type = _JSON_TYPE_MAP.get(expected_type)
        if py_type is None:
            return None
        if not isinstance(value, py_type):
            return ContractViolation(
                contract_id=contract_id,
                violation_type="type_mismatch",
                field=field_name,
                message=(
                    f"Field '{field_name}' expected type '{expected_type}', "
                    f"got '{type(value).__name__}'"
                ),
            )
        return None

    # ---- Internal: artifact validation rules ----

    def _apply_rule(
        self,
        rule: ArtifactValidationRule,
        payload: dict,
        contract_id: str,
    ) -> ContractViolation | None:
        """Apply a single ArtifactValidationRule to the payload."""
        field = rule.field
        rule_type = rule.rule_type
        params = rule.parameters
        default_msg = rule.message or f"Validation rule '{rule_type}' failed"
        severity = rule.severity

        value = payload.get(field) if field else None

        if rule_type == "min_length":
            min_len = int(params.get("value", 0))
            if value is not None and len(str(value)) < min_len:
                return ContractViolation(
                    contract_id=contract_id,
                    violation_type=rule_type,
                    field=field,
                    message=default_msg,
                    severity=severity,
                )

        elif rule_type == "max_length":
            max_len = int(params.get("value", 0))
            if value is not None and len(str(value)) > max_len:
                return ContractViolation(
                    contract_id=contract_id,
                    violation_type=rule_type,
                    field=field,
                    message=default_msg,
                    severity=severity,
                )

        elif rule_type == "allowed_values":
            allowed = params.get("values", [])
            if value is not None and value not in allowed:
                return ContractViolation(
                    contract_id=contract_id,
                    violation_type=rule_type,
                    field=field,
                    message=default_msg,
                    severity=severity,
                )

        elif rule_type == "type_check":
            expected = params.get("type")
            if value is not None and expected:
                return self._check_type(value, expected, field or "", contract_id)

        elif rule_type == "required_if":
            condition_field = params.get("condition_field")
            condition_value = params.get("condition_value")
            if (
                condition_field
                and payload.get(condition_field) == condition_value
                and (field not in payload or payload[field] is None)
            ):
                return ContractViolation(
                    contract_id=contract_id,
                    violation_type=rule_type,
                    field=field,
                    message=default_msg,
                    severity=severity,
                )

        elif rule_type == "pattern":
            regex = params.get("regex")
            if value is not None and regex:
                try:
                    if not re.fullmatch(regex, str(value)):
                        return ContractViolation(
                            contract_id=contract_id,
                            violation_type=rule_type,
                            field=field,
                            message=default_msg,
                            severity=severity,
                        )
                except re.error:
                    logger.warning(
                        "Invalid regex in contract %s rule %s: %r",
                        contract_id,
                        rule.rule_id,
                        regex,
                    )

        return None

    # ---- Internal: audit logging ----

    def _log_violation(
        self,
        contract: CapabilityContract,
        result: ContractValidationResult,
        validation_phase: str,
        context: dict,
    ) -> None:
        violation_summaries = [
            f"{v.field or '*'}: {v.message}" for v in result.violations
        ]
        logger.warning(
            "Contract violation [%s] contract_id=%s capability=%s op=%s violations=%s",
            validation_phase,
            contract.contract_id,
            contract.capability_type,
            contract.operation_name,
            violation_summaries,
        )
        if self._audit_logger is not None:
            self._emit_audit(
                contract_id=contract.contract_id,
                validation_phase=validation_phase,
                result=result,
                context=context,
                extra={
                    "capability_type": contract.capability_type,
                    "operation_name": contract.operation_name,
                },
            )

    def _log_artifact_violation(
        self,
        contract: ArtifactContract,
        result: ContractValidationResult,
        context: dict,
    ) -> None:
        violation_summaries = [
            f"{v.field or '*'}: {v.message}" for v in result.violations
        ]
        logger.warning(
            "Artifact contract violation contract_id=%s artifact_type=%s violations=%s",
            contract.contract_id,
            contract.artifact_type,
            violation_summaries,
        )
        if self._audit_logger is not None:
            self._emit_audit(
                contract_id=contract.contract_id,
                validation_phase="artifact",
                result=result,
                context=context,
                extra={"artifact_type": contract.artifact_type},
            )

    def _emit_audit(
        self,
        contract_id: str,
        validation_phase: str,
        result: ContractValidationResult,
        context: dict,
        extra: dict,
    ) -> None:
        try:
            from ..governance.audit_logger import RecordType

            violation_dicts = [v.model_dump() for v in result.violations]
            summary = (
                f"contract_violation contract_id={contract_id} "
                f"phase={validation_phase} "
                f"violations={len(violation_dicts)}"
            )
            self._audit_logger.append(
                record_type=RecordType.SYSTEM_EVENT,
                action="contract_violation",
                summary=summary,
                work_id=context.get("work_id", ""),
                data={
                    "contract_id": contract_id,
                    "validation_phase": validation_phase,
                    "is_valid": result.is_valid,
                    "violations": violation_dicts,
                    "run_id": context.get("run_id"),
                    "workflow_id": context.get("workflow_id"),
                    "module_name": context.get("module_name"),
                    "agent_role": context.get("agent_role"),
                    **extra,
                },
            )
        except Exception:
            logger.warning("Failed to emit contract violation audit record", exc_info=True)
