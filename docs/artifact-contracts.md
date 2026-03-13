# Artifact Contracts

Artifact contracts define the structural and lifecycle contract for workflow artifacts — the data objects that flow between agents, workflow phases, and connectors. They specify required fields, validation rules, provenance requirements, and lifecycle state models without encoding domain-specific logic.

## Overview

An `ArtifactContract` governs a named `artifact_type`. The `ContractValidator` validates artifact payloads before they are passed to consumers or stored.

Validation is **non-blocking by default**: failures are logged and audited, but execution is not halted unless the caller raises `ContractViolationError`.

## Contract Fields

| Field | Type | Description |
|---|---|---|
| `contract_id` | `str` | Unique identifier. Auto-generated UUID if not provided. |
| `artifact_type` | `str` | Name of the artifact type this contract governs. |
| `description` | `str` | Human-readable description. |
| `required_fields` | `list[str]` | Fields that must be present in every artifact of this type. |
| `optional_fields` | `list[str]` | Known optional fields; other fields are also permitted. |
| `validation_rules` | `list[ArtifactValidationRule]` | Ordered validation rules applied to the payload. |
| `provenance_requirements` | `list[str]` | Provenance keys producers must include. |
| `lifecycle_state_model` | `list[LifecycleState]` | Valid lifecycle states for this artifact type. |
| `initial_lifecycle_state` | `LifecycleState` | Default initial state. |
| `producer_constraints` | `list[str]` | Agent roles or module names permitted to produce this artifact. |
| `consumer_constraints` | `list[str]` | Agent roles or module names permitted to consume this artifact. |
| `metadata` | `dict` | Arbitrary extension point for domain modules. |

## Validation Rules

`ArtifactValidationRule` supports the following `rule_type` values:

| `rule_type` | Parameters | Description |
|---|---|---|
| `min_length` | `{"value": int}` | String/list length must be ≥ value. |
| `max_length` | `{"value": int}` | String/list length must be ≤ value. |
| `allowed_values` | `{"values": list}` | Field value must be one of the allowed values. |
| `type_check` | `{"type": "string"\|"integer"\|"number"\|"boolean"\|"array"\|"object"}` | Field must be the given JSON type. |
| `required_if` | `{"condition_field": str, "condition_value": Any}` | Field is required when `condition_field == condition_value`. |
| `pattern` | `{"regex": str}` | Field value must match the regex (full match). |

Additional `rule_type` values can be defined by domain modules and interpreted by domain-level validators that extend `ContractValidator`.

### Rule Severity

Each rule carries a `severity` (`"error"` or `"warning"`). The platform currently logs all violations regardless of severity; domain modules may choose to treat `"warning"` violations differently.

## Lifecycle States

Built-in lifecycle states:

- `draft` — artifact created but not yet approved for use
- `active` — artifact is live and can be consumed
- `deprecated` — artifact is being phased out
- `archived` — artifact is retained for audit but no longer consumed
- `expired` — artifact has passed its validity period

The platform does not enforce lifecycle transitions automatically; the `lifecycle_state_model` list documents valid states for human governance.

## Registration

```python
from agent_orchestrator.contracts import (
    ArtifactContract,
    ArtifactValidationRule,
    ContractRegistry,
    ContractValidator,
    LifecycleState,
)

registry = ContractRegistry()

registry.register_artifact_contract(
    ArtifactContract(
        contract_id="ticket-v1",
        artifact_type="ticket",
        description="A support ticket artifact",
        required_fields=["title", "priority", "status"],
        optional_fields=["description", "assignee", "labels"],
        validation_rules=[
            ArtifactValidationRule(
                field="priority",
                rule_type="allowed_values",
                parameters={"values": ["low", "medium", "high", "critical"]},
                message="Priority must be one of: low, medium, high, critical",
            ),
            ArtifactValidationRule(
                field="title",
                rule_type="min_length",
                parameters={"value": 3},
                message="Title must be at least 3 characters",
            ),
            ArtifactValidationRule(
                field="resolution",
                rule_type="required_if",
                parameters={"condition_field": "status", "condition_value": "closed"},
                message="Resolution is required when status is closed",
            ),
        ],
        lifecycle_state_model=[
            LifecycleState.DRAFT,
            LifecycleState.ACTIVE,
            LifecycleState.ARCHIVED,
        ],
        provenance_requirements=["source_connector", "created_by"],
    )
)
```

## Validation

```python
validator = ContractValidator(registry)

result = validator.validate_artifact(
    artifact_type="ticket",
    artifact_payload={
        "title": "Login fails",
        "priority": "high",
        "status": "open",
        "provenance": {
            "source_connector": "jira",
            "created_by": "agent:researcher",
        },
    },
)

if result is not None and not result.is_valid:
    for v in result.violations:
        print(f"  [{v.severity}] {v.field}: {v.message}")
```

## REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/contracts/artifact` | List all artifact contracts |
| `POST` | `/api/v1/contracts/artifact` | Register an artifact contract |
| `GET` | `/api/v1/contracts/artifact/{id}` | Get a contract by ID |
| `DELETE` | `/api/v1/contracts/artifact/{id}` | Unregister a contract |
| `POST` | `/api/v1/contracts/artifact/{id}/validate` | Validate a payload against the contract |

### Example: Register via API

```http
POST /api/v1/contracts/artifact
Content-Type: application/json

{
  "contract_id": "ticket-v1",
  "artifact_type": "ticket",
  "required_fields": ["title", "priority", "status"],
  "validation_rules": [
    {
      "field": "priority",
      "rule_type": "allowed_values",
      "parameters": { "values": ["low", "medium", "high"] },
      "message": "Invalid priority"
    }
  ]
}
```

### Example: Validate via API

```http
POST /api/v1/contracts/artifact/ticket-v1/validate
Content-Type: application/json

{
  "payload": { "title": "Bug", "priority": "critical", "status": "open" }
}
```

Response:

```json
{
  "is_valid": true,
  "contract_id": "ticket-v1",
  "violations": [],
  "validated_at": "2026-03-11T10:00:00Z"
}
```

## Provenance Validation

If `provenance_requirements` is set, the validator checks that each key is present in either the top-level payload or its `provenance` sub-dict:

```python
ArtifactContract(
    contract_id="doc-v1",
    artifact_type="document",
    required_fields=["content"],
    provenance_requirements=["source_url", "retrieved_at"],
)
```

An artifact missing `source_url` will produce a `missing_provenance_field` violation.

## Domain Extension Pattern

Domain modules define and register contracts at startup:

```python
# my_domain/contracts.py
from agent_orchestrator.contracts import ArtifactContract, ArtifactValidationRule, ContractRegistry

def register_domain_artifact_contracts(registry: ContractRegistry) -> None:
    registry.register_artifact_contract(
        ArtifactContract(
            contract_id="moderation-verdict-v1",
            artifact_type="moderation_verdict",
            required_fields=["label", "confidence", "reviewed_at"],
            validation_rules=[
                ArtifactValidationRule(
                    field="confidence",
                    rule_type="type_check",
                    parameters={"type": "number"},
                ),
            ],
        )
    )
```

## Audit Trail

Artifact contract violations are recorded as `SYSTEM_EVENT` audit records with `action="contract_violation"` and `validation_phase="artifact"`. Each record includes:

- `contract_id` and `artifact_type`
- `violations` list with `field`, `violation_type`, `message`, `severity`
- Execution context: `run_id`, `workflow_id`, `module_name`, `agent_role`
