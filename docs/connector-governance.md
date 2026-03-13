# Connector Runtime Governance

Runtime governance lets administrators control connector availability and permissions without redeploying the service. All governance operations work on frozen Pydantic `ConnectorConfig` objects via immutable copy-and-re-register semantics.

## Overview

The `ConnectorGovernanceService` wraps a `ConnectorRegistry` and provides:

| Concern | API |
|---|---|
| Enable / disable a connector | `enable_connector()`, `disable_connector()` |
| Restrict by module or agent role | `update_scoping()` |
| Add / remove permission policies | `add_policy()`, `remove_policy()` |
| Discover accessible connectors | `discover()` |
| Resolve effective permissions | `get_effective_permissions()` |

The `ConnectorService.execute()` path enforces config-level access (enabled flag, module and role scoping) **before** policy evaluation. Disabled connectors return `UNAVAILABLE`; out-of-scope contexts return `PERMISSION_DENIED`.

---

## Setup

```python
from agent_orchestrator.connectors.registry import ConnectorRegistry
from agent_orchestrator.connectors.governance_service import ConnectorGovernanceService

registry = ConnectorRegistry()
governance = ConnectorGovernanceService(registry)
```

When using the `OrchestrationEngine`, the governance service is available via:

```python
engine.connector_governance_service
```

---

## ConnectorConfig

A `ConnectorConfig` describes how a connector is governed at runtime.

```python
from agent_orchestrator.connectors import (
    CapabilityType,
    ConnectorConfig,
    ConnectorPermissionPolicy,
)

config = ConnectorConfig(
    connector_id="search.brave",
    provider_id="search.brave",
    capability_type=CapabilityType.SEARCH,
    display_name="Brave Search",
    enabled=True,
    scoped_modules=[],          # empty = accessible from all modules
    scoped_agent_roles=[],      # empty = accessible by all roles
    permission_policies=[],
)
registry.register_config(config)
```

All `ConnectorConfig` instances are frozen (Pydantic `model_config = ConfigDict(frozen=True)`). Every governance mutation creates a new copy via `model_copy(update={...})` and re-registers it.

---

## Lifecycle — Enable / Disable

```python
# Disable a connector so it is excluded from discovery and returns UNAVAILABLE
governance.disable_connector("search.brave")

# Re-enable it at runtime
governance.enable_connector("search.brave")
```

Both methods raise `ConnectorGovernanceError` if no config is registered for the given ID.

---

## Scoping

Scoping restricts which modules or agent roles can access a connector.

```python
# Restrict to the "incident-response" module only
governance.update_scoping("ticketing.jira", scoped_modules=["incident-response"])

# Restrict to the "triage" agent role only
governance.update_scoping("ticketing.jira", scoped_agent_roles=["triage"])

# Both module and role restriction
governance.update_scoping(
    "ticketing.jira",
    scoped_modules=["incident-response"],
    scoped_agent_roles=["triage"],
)

# Remove all restrictions (pass an empty list)
governance.update_scoping("ticketing.jira", scoped_modules=[], scoped_agent_roles=[])
```

Pass `None` for a field to leave its existing value unchanged:

```python
# Only update roles; leave scoped_modules as-is
governance.update_scoping("ticketing.jira", scoped_agent_roles=["triage"])
```

### How scoping is enforced

When `ConnectorService.execute()` is called with a `context` dict containing `module_name` and/or `agent_role`, the service checks every enabled `ConnectorConfig` for the requested capability:

- If a config's `scoped_modules` list is **empty**, it matches any module.
- If a config's `scoped_modules` list is **non-empty**, the request's `module_name` must appear in it.
- Same logic applies to `scoped_agent_roles`.

If at least one config passes both checks, execution proceeds. If none pass, the service returns `ConnectorStatus.PERMISSION_DENIED`.

---

## Permission Policies

Permission policies gate specific operations within an accessible connector.

```python
from agent_orchestrator.connectors import ConnectorPermissionPolicy

# Require approval for all write operations (non-read-prefix operations)
policy = ConnectorPermissionPolicy(
    policy_id="require-approval-writes",
    requires_approval=True,
)
governance.add_policy("ticketing.jira", policy)

# Deny a specific operation entirely
policy = ConnectorPermissionPolicy(
    policy_id="deny-delete",
    denied_operations=["delete_ticket"],
)
governance.add_policy("ticketing.jira", policy)

# Restrict by module and role
policy = ConnectorPermissionPolicy(
    policy_id="billing-analyst-only",
    allowed_modules=["billing"],
    allowed_agent_roles=["analyst"],
)
governance.add_policy("ticketing.jira", policy)

# Remove a policy by ID
governance.remove_policy("ticketing.jira", "require-approval-writes")
```

### Read-only bypass

Operations whose names begin with a read-like prefix (`get`, `list`, `read`, `fetch`, `query`, `search`) are never gated as `REQUIRES_APPROVAL`, even if a `requires_approval=True` policy is attached. This is enforced inside `evaluate_permission_detailed()`.

---

## Discovery

`discover()` returns all connectors accessible in a given execution context.

```python
# All accessible connectors (no context filter)
items = governance.discover()

# Accessible in the "incident-response" module by a "triage" agent
items = governance.discover(module_name="incident-response", agent_role="triage")

for item in items:
    print(item.connector_id, item.capability_type, item.available_operations)
```

Each `ConnectorDiscoveryItem` is a frozen dataclass:

| Field | Type | Description |
|---|---|---|
| `connector_id` | `str` | Config ID |
| `provider_id` | `str` | Provider ID |
| `capability_type` | `str` | Capability type value |
| `display_name` | `str` | Human-readable label |
| `provider_available` | `bool` | Whether the provider is registered and enabled |
| `available_operations` | `list[str]` | Operations exposed by the provider |
| `scoped_modules` | `list[str]` | Active module restrictions |
| `scoped_agent_roles` | `list[str]` | Active role restrictions |

Call `.as_dict()` for a JSON-serialisable representation.

---

## Effective Permissions

`get_effective_permissions()` evaluates which operations are allowed, denied, or gated for approval in a given context.

```python
perms = governance.get_effective_permissions(
    "ticketing.jira",
    module_name="incident-response",
    agent_role="triage",
)

print(perms.allowed_operations)           # ["get_ticket", "search_tickets", "create_ticket"]
print(perms.denied_operations)            # []
print(perms.requires_approval_operations) # ["update_ticket"]
```

`EffectivePermissions` fields:

| Field | Type |
|---|---|
| `connector_id` | `str` |
| `enabled` | `bool` |
| `scoped_modules` | `list[str]` |
| `scoped_agent_roles` | `list[str]` |
| `allowed_operations` | `list[str]` |
| `denied_operations` | `list[str]` |
| `requires_approval_operations` | `list[str]` |

---

## REST API

All governance operations are exposed via the connector routes.

### Register a config

```
POST /connectors/configs
{
  "connector_id": "ticketing.jira",
  "provider_id": "ticketing.jira",
  "capability_type": "ticketing",
  "display_name": "Jira",
  "enabled": true,
  "scoped_modules": [],
  "scoped_agent_roles": []
}
```

### Get a config

```
GET /connectors/configs/{connector_id}
```

### Enable / disable

```
POST /connectors/configs/{connector_id}/enable
POST /connectors/configs/{connector_id}/disable
```

### Update scoping

```
PUT /connectors/configs/{connector_id}/scoping
{
  "scoped_modules": ["incident-response"],
  "scoped_agent_roles": ["triage"]
}
```

Pass `null` for a field to leave it unchanged.

### Manage policies

```
POST /connectors/configs/{connector_id}/policies
{
  "policy_id": "require-approval-writes",
  "requires_approval": true,
  "allowed_modules": [],
  "allowed_agent_roles": [],
  "denied_operations": []
}

DELETE /connectors/configs/{connector_id}/policies/{policy_id}
```

### Discovery

```
GET /connectors/discovery
GET /connectors/discovery?module_name=incident-response&agent_role=triage
```

Response:

```json
{
  "connectors": [
    {
      "connector_id": "ticketing.jira",
      "provider_id": "ticketing.jira",
      "capability_type": "ticketing",
      "display_name": "Jira",
      "provider_available": true,
      "available_operations": ["create_ticket", "update_ticket", "get_ticket", "search_tickets"],
      "scoped_modules": ["incident-response"],
      "scoped_agent_roles": ["triage"]
    }
  ]
}
```

### Effective permissions

```
GET /connectors/configs/{connector_id}/permissions
GET /connectors/configs/{connector_id}/permissions?module_name=incident-response&agent_role=triage
```

---

## Domain-agnosticism

The governance layer operates entirely on `CapabilityType` enum values and string operation names. No domain-specific fields or models are introduced. Domain modules interact with the governance service through the same connector framework APIs they use for execution.
