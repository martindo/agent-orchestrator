# Ticketing Connector Capability

The **ticketing** capability lets agents create, update, retrieve, and search tickets or issues in external task-tracking systems. Results are returned as `ExternalArtifact` objects with `resource_type="ticket"`.

## Supported Providers

| Provider | `provider_id`      | Auth Method               |
|----------|--------------------|---------------------------|
| Jira     | `ticketing.jira`   | Basic (email + API token) or Bearer (PAT) |
| Linear   | `ticketing.linear` | API key (Authorization header) |

---

## Operations

| Operation        | read_only | Required Parameters           | Optional Parameters                                          |
|------------------|-----------|-------------------------------|--------------------------------------------------------------|
| `create_ticket`  | `False`   | `summary`                     | `project`, `description`, `issue_type`, `priority`, `assignee` |
| `update_ticket`  | `False`   | `ticket_id`, `changes`        |                                                              |
| `get_ticket`     | `True`    | `ticket_id`                   |                                                              |
| `search_tickets` | `True`    | `query`                       | `limit` (default 25)                                         |

Write operations (`create_ticket`, `update_ticket`) are marked `read_only=False`. Attaching a `ConnectorPermissionPolicy` with `requires_approval=True` to the `TICKETING` capability type will route these operations through the `REQUIRES_APPROVAL` path in `ConnectorService`.

---

## Return Value: ExternalArtifact

All operations return a `ConnectorInvocationResult` whose `payload` is an `ExternalArtifact` dict.

**Single-ticket operations** (`create_ticket`, `update_ticket`, `get_ticket`):

```python
{
    "capability_type": "ticketing",
    "resource_type": "ticket",
    "provider": "ticketing.jira",
    "normalized_payload": {
        "ticket_id": "PROJ-42",
        "title": "Fix login bug",
        "description": "Users cannot log in via SSO",
        "status": "In Progress",
        "priority": "High",
        "assignee": "Alice Smith",
        "url": "https://myorg.atlassian.net/browse/PROJ-42",
        ...
    },
    "raw_payload": { ... },   # provider raw response
    "references": [
        {
            "provider": "ticketing.jira",
            "resource_type": "jira_issue",
            "external_id": "PROJ-42",
            "url": "https://myorg.atlassian.net/browse/PROJ-42"
        }
    ]
}
```

**Search operation** (`search_tickets`):

```python
{
    "capability_type": "ticketing",
    "resource_type": "ticket_list",
    "provider": "ticketing.jira",
    "normalized_payload": null,
    "raw_payload": {
        "query": "project = PROJ AND status = Open",
        "total": 10,
        "items": [
            {
                "ticket_id": "PROJ-1",
                "title": "...",
                "status": "Open",
                "priority": "High",
                "assignee": "Bob",
                "url": "..."
            },
            ...
        ]
    }
}
```

---

## Jira Provider

### Setup

```python
from agent_orchestrator.connectors.providers.ticketing import JiraTicketingProvider

# Jira Cloud (Basic auth: email + API token)
provider = JiraTicketingProvider(
    base_url="https://myorg.atlassian.net",
    api_token="ATATT3xFfGF0...",
    email="user@example.com",
    default_project="PROJ",        # optional fallback project key
)

# Jira Data Center (Bearer / PAT auth)
provider = JiraTicketingProvider(
    base_url="https://jira.internal.example.com",
    api_token="personal-access-token",
)
```

### create_ticket

```python
result = await service.execute(
    capability_type="ticketing",
    operation="create_ticket",
    parameters={
        "summary": "Fix login bug",
        "project": "PROJ",          # or rely on default_project
        "description": "Users cannot log in via SSO",
        "issue_type": "Bug",        # default: "Task"
        "priority": "High",
        "assignee": "5b109f2e9729b51b...",  # Jira accountId
    },
    preferred_provider="ticketing.jira",
)
```

### update_ticket

`changes` maps directly to Jira field names in the `PUT /rest/api/3/issue/{key}` body.

```python
result = await service.execute(
    capability_type="ticketing",
    operation="update_ticket",
    parameters={
        "ticket_id": "PROJ-42",
        "changes": {
            "summary": "Updated title",
            "priority": {"name": "Medium"},
            "status": {"name": "In Progress"},
        },
    },
    preferred_provider="ticketing.jira",
)
```

### get_ticket

```python
result = await service.execute(
    capability_type="ticketing",
    operation="get_ticket",
    parameters={"ticket_id": "PROJ-42"},
    preferred_provider="ticketing.jira",
)
```

### search_tickets

The `query` parameter accepts a **JQL** string.

```python
result = await service.execute(
    capability_type="ticketing",
    operation="search_tickets",
    parameters={
        "query": "project = PROJ AND status = Open AND priority = High",
        "limit": "50",
    },
    preferred_provider="ticketing.jira",
)
```

---

## Linear Provider

### Setup

```python
from agent_orchestrator.connectors.providers.ticketing import LinearTicketingProvider

provider = LinearTicketingProvider(
    api_key="lin_api_xxxxxxxxxxxx",
    default_team_id="abc123-team-uuid",  # optional fallback team UUID
)
```

### create_ticket

The `project` parameter is the Linear **team UUID**. Priority is a label string: `"urgent"`, `"high"`, `"medium"`, `"low"`.

```python
result = await service.execute(
    capability_type="ticketing",
    operation="create_ticket",
    parameters={
        "summary": "Implement dark mode",
        "project": "team-uuid-1234",     # or rely on default_team_id
        "description": "Add dark mode toggle to settings page",
        "priority": "medium",
        "assignee": "user-uuid-5678",    # Linear user UUID
    },
    preferred_provider="ticketing.linear",
)
```

### update_ticket

The `ticket_id` for Linear `update_ticket` must be the issue **UUID** (the `id` field from `get_ticket`'s `raw_payload`). The `changes` dict supports: `title` (or `summary`), `description`, `priority` (label string), `assignee` (user UUID).

```python
result = await service.execute(
    capability_type="ticketing",
    operation="update_ticket",
    parameters={
        "ticket_id": "uuid-of-issue",
        "changes": {"title": "Updated title", "priority": "high"},
    },
    preferred_provider="ticketing.linear",
)
```

### get_ticket

Accepts both the human-readable identifier (e.g. `"ENG-42"`) and the UUID.

```python
result = await service.execute(
    capability_type="ticketing",
    operation="get_ticket",
    parameters={"ticket_id": "ENG-42"},
    preferred_provider="ticketing.linear",
)
```

### search_tickets

Performs a **case-insensitive title substring search** via Linear's GraphQL `containsIgnoreCase` filter.

```python
result = await service.execute(
    capability_type="ticketing",
    operation="search_tickets",
    parameters={"query": "dark mode", "limit": "10"},
    preferred_provider="ticketing.linear",
)
```

---

## Permission Policies

Write operations on tickets require explicit approval when a `ConnectorPermissionPolicy` with `requires_approval=True` covers the `TICKETING` capability type:

```python
from agent_orchestrator.connectors.models import (
    ConnectorConfig,
    ConnectorPermissionPolicy,
    CapabilityType,
)

policy = ConnectorPermissionPolicy(
    description="Require human approval before creating or modifying tickets",
    allowed_capability_types=[CapabilityType.TICKETING],
    requires_approval=True,
)

config = ConnectorConfig(
    connector_id="ticketing.jira",
    provider_id="ticketing.jira",
    permission_policies=[policy],
)
registry.register_config(config)
```

When `create_ticket` or `update_ticket` is invoked, `ConnectorService` will return a result with `status=REQUIRES_APPROVAL` instead of executing the operation. Read operations (`get_ticket`, `search_tickets`) are never subject to approval because they start with `get` or `search`.

---

## Registering Providers

```python
from agent_orchestrator.connectors.registry import ConnectorRegistry
from agent_orchestrator.connectors.providers.ticketing import (
    JiraTicketingProvider,
    LinearTicketingProvider,
)

registry = ConnectorRegistry()

registry.register_provider(
    JiraTicketingProvider(
        base_url="https://myorg.atlassian.net",
        api_token="ATATT3x...",
        email="agent@example.com",
        default_project="PROJ",
    )
)

registry.register_provider(
    LinearTicketingProvider(
        api_key="lin_api_xxx",
        default_team_id="team-uuid",
    )
)
```
