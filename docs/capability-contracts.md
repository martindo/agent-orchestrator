# Capability Contracts

Capability contracts define the interface contract for connector capability operations. They specify what inputs are required, what outputs are expected, and how the platform should behave when validation fails — without encoding any domain-specific logic.

## Overview

A `CapabilityContract` governs a single (capability_type, operation_name) pair. When a `ContractValidator` is wired into `ConnectorService`, it automatically validates inputs before execution and outputs after execution.

Validation is **non-blocking by default** (`failure_semantics = warn_only`): failures are logged as warnings and recorded in the audit trail, but execution is not halted. Callers may upgrade enforcement by reading the `ContractValidationResult` and raising `ContractViolationError` themselves.

## Contract Fields

| Field | Type | Description |
|---|---|---|
| `contract_id` | `str` | Unique identifier. Auto-generated UUID if not provided. |
| `capability_type` | `str` | Matches `CapabilityType` enum values (e.g. `"search"`, `"ticketing"`). Any string is valid. |
| `operation_name` | `str` | The operation this contract governs (e.g. `"query"`, `"create_issue"`). |
| `description` | `str` | Human-readable description. |
| `input_schema` | `dict` | JSON Schema fragment for validating input parameters. |
| `output_schema` | `dict` | JSON Schema fragment for validating output payload. |
| `read_write_classification` | `ReadWriteClassification` | `read_only`, `write_only`, or `read_write`. |
| `permission_requirements` | `list[str]` | Platform permission tokens required before invocation. |
| `timeout_policy` | `ContractTimeoutPolicy \| None` | Timeout and on-timeout behaviour. |
| `retry_policy` | `ContractRetryPolicy \| None` | Retry configuration. |
| `audit_requirements` | `AuditRequirement` | `none`, `invocation`, or `full`. |
| `cost_reporting_required` | `bool` | Whether cost metadata must be reported. |
| `failure_semantics` | `FailureSemantic` | How validation failures are handled. |
| `metadata` | `dict` | Arbitrary key/value extension point for domain modules. |

## Schema Validation

`input_schema` and `output_schema` follow a subset of JSON Schema:

```json
{
  "required": ["q", "limit"],
  "properties": {
    "q":     { "type": "string" },
    "limit": { "type": "integer" }
  }
}
```

Supported JSON Schema types: `string`, `integer`, `number`, `boolean`, `array`, `object`, `null`.

Fields not listed in `properties` are permitted (open-world assumption).

## Failure Semantics

| Value | Behaviour |
|---|---|
| `warn_only` | Log warning; execution continues. Default. |
| `fail_fast` | Caller may raise `ContractViolationError` on non-`is_valid` results. |
| `return_partial` | Domain hint: return whatever partial data is available. |
| `retry` | Domain hint: retry the operation. |
| `skip` | Domain hint: skip this step. |

## Registration

```python
from agent_orchestrator.contracts import (
    AuditRequirement,
    CapabilityContract,
    ContractRegistry,
    ContractValidator,
    ReadWriteClassification,
)

registry = ContractRegistry()

registry.register_capability_contract(
    CapabilityContract(
        contract_id="search-query-v1",
        capability_type="search",
        operation_name="query",
        description="Web search query contract",
        input_schema={
            "required": ["q"],
            "properties": {
                "q":     { "type": "string" },
                "limit": { "type": "integer" },
            },
        },
        output_schema={
            "required": ["results"],
        },
        read_write_classification=ReadWriteClassification.READ_ONLY,
        audit_requirements=AuditRequirement.INVOCATION,
    )
)
```

## Wiring into ConnectorService

```python
from agent_orchestrator.contracts import ContractValidator
from agent_orchestrator.connectors import ConnectorService

validator = ContractValidator(registry, audit_logger=audit_logger)

service = ConnectorService(
    registry=connector_registry,
    audit_logger=audit_logger,
    contract_validator=validator,  # optional — omit for no validation
)
```

When a `contract_validator` is present, `ConnectorService.execute()` calls:

1. `validator.validate_capability_input(...)` before provider execution
2. `validator.validate_capability_output(...)` after provider execution (if payload is non-null)

Both calls are **exception-safe**: internal errors are logged as warnings and do not propagate.

## REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/contracts/capability` | List all capability contracts |
| `POST` | `/api/v1/contracts/capability` | Register a capability contract |
| `GET` | `/api/v1/contracts/capability/{id}` | Get a contract by ID |
| `DELETE` | `/api/v1/contracts/capability/{id}` | Unregister a contract |
| `POST` | `/api/v1/contracts/capability/{id}/validate-input` | Validate a payload against input schema |
| `POST` | `/api/v1/contracts/capability/{id}/validate-output` | Validate a payload against output schema |

### Example: Register via API

```http
POST /api/v1/contracts/capability
Content-Type: application/json

{
  "contract_id": "search-query-v1",
  "capability_type": "search",
  "operation_name": "query",
  "input_schema": {
    "required": ["q"],
    "properties": { "q": { "type": "string" } }
  },
  "failure_semantics": "warn_only"
}
```

## Domain Extension Pattern

Domain modules register contracts at startup against the platform's `ContractRegistry`. They never modify `agent_orchestrator` source code:

```python
# my_domain/startup.py
from agent_orchestrator.contracts import CapabilityContract, ContractRegistry

def register_domain_contracts(registry: ContractRegistry) -> None:
    registry.register_capability_contract(
        CapabilityContract(
            contract_id="content-mod-classify-v1",
            capability_type="external_api",
            operation_name="classify_content",
            input_schema={"required": ["text"]},
            output_schema={"required": ["label", "confidence"]},
        )
    )
```

The platform calls `register_domain_contracts(app.state.contract_registry)` during domain initialisation.

## Audit Trail

Contract violations are recorded in the platform audit trail as `SYSTEM_EVENT` records with `action="contract_violation"`. Each record includes:

- `contract_id` — which contract was violated
- `validation_phase` — `"capability_input"` or `"capability_output"`
- `violations` — list of violation objects with `field`, `violation_type`, `message`
- `run_id`, `workflow_id`, `module_name`, `agent_role` from execution context
