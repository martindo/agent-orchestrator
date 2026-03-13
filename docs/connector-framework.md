# Connector Framework Guide

The Connector Capability Framework provides a domain-agnostic, policy-governed layer for invoking external systems from within orchestrated workflows. All connector concepts are generic — no domain-specific logic is embedded in the framework itself.

---

## Capability-Based Connector Model

Connectors are organized by **capability type** — a coarse-grained taxonomy of external system categories. Domain modules request a capability type, not a specific provider, so the underlying provider can be swapped without changing calling code.

| Capability Type | Description |
|-----------------|-------------|
| `search` | Full-text or semantic search |
| `documents` | Document retrieval and management |
| `messaging` | Send/receive messages (Slack, Teams, email) |
| `ticketing` | Issue/ticket CRUD (Jira, GitHub Issues, ServiceNow) |
| `repository` | Source code repositories (GitHub, GitLab, Bitbucket) |
| `telemetry` | Metrics, logs, traces (Datadog, Splunk, Grafana) |
| `identity` | User and group lookup (LDAP, Okta, Azure AD) |
| `external_api` | Generic HTTP/REST endpoints |
| `file_storage` | Object and blob storage (S3, GCS, Azure Blob) |
| `workflow_action` | Trigger external workflow steps (CI/CD, webhooks) |

---

## Provider Abstraction — ConnectorProviderProtocol

Providers use **structural typing** (Protocol) — no inheritance is required. Any class that implements the two required methods is a valid provider:

```python
class MySearchProvider:
    def get_descriptor(self) -> ConnectorProviderDescriptor:
        return ConnectorProviderDescriptor(
            provider_id="my-search",
            display_name="My Search Engine",
            capability_types=[CapabilityType.SEARCH],
            version="1.0.0",
            operations=[
                ConnectorOperationDescriptor(
                    operation="query",
                    description="Full-text search query",
                    capability_type=CapabilityType.SEARCH,
                    required_parameters=["q"],
                )
            ],
        )

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        # call external API
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id="my-search",
            provider="my-search",
            capability_type=request.capability_type,
            operation=request.operation,
            status=ConnectorStatus.SUCCESS,
            payload={"results": [...]},
            cost_info=ConnectorCostInfo(request_cost=0.001, usage_units=50),
        )
```

### ConnectorProviderDescriptor Fields

| Field | Type | Description |
|-------|------|-------------|
| `provider_id` | `str` | Unique provider identifier |
| `display_name` | `str` | Human-readable name |
| `capability_types` | `list[CapabilityType]` | Supported capability categories |
| `operations` | `list[ConnectorOperationDescriptor]` | Declared operations (optional) |
| `enabled` | `bool` | Whether provider is active |
| `version` | `str \| None` | Provider version string |
| `auth_required` | `bool` | Whether authentication is needed |
| `parameter_schemas` | `dict` | Operation → schema hint mapping |
| `result_schema_hint` | `dict` | Result shape hints |
| `metadata` | `dict` | Additional metadata |

---

## Invocation Flow

```
ConnectorService.execute()
  │
  ├── 1. Resolve capability_type (string → enum)
  ├── 2. Build ConnectorInvocationRequest
  ├── 3. Collect ConnectorPermissionPolicy objects from matching ConnectorConfig
  ├── 4. evaluate_permission(request, policies)
  │       └── DENIED → return ConnectorStatus.PERMISSION_DENIED
  ├── 5. find_provider_for_operation(capability_type, operation, preferred)
  │       └── NONE → return ConnectorStatus.UNAVAILABLE
  ├── 6. _get_retry_policy(capability_type) from ConnectorConfig
  ├── 7. ConnectorExecutor.execute(provider, request, retry_policy)
  │       ├── Attempt 1 → provider.execute(request) [with asyncio timeout]
  │       │     ├── SUCCESS → return result
  │       │     ├── TIMEOUT/FAILURE → record trace, check retryable
  │       │     └── Exception → normalize to FAILURE result
  │       ├── Retry with exponential backoff (if retryable + attempts remaining)
  │       └── Return final ConnectorInvocationResult
  ├── 8. _record_trace() → ConnectorTraceStore
  ├── 9. _record_cost() → MetricsCollector
  └── 10. _maybe_audit() → AuditLogger
```

### ConnectorInvocationRequest

| Field | Type | Description |
|-------|------|-------------|
| `capability_type` | `CapabilityType` | Category of external system |
| `operation` | `str` | Specific action (e.g. `"query"`, `"create_issue"`) |
| `parameters` | `dict` | Operation-specific key/value pairs |
| `context` | `dict` | Platform context: `run_id`, `workflow_id`, `agent_role`, `module_name` |
| `preferred_provider` | `str \| None` | Optional provider override |
| `timeout_seconds` | `float \| None` | Per-call timeout |

### ConnectorInvocationResult

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ConnectorStatus` | Outcome enum |
| `payload` | `dict \| None` | Provider response payload |
| `cost_info` | `ConnectorCostInfo \| None` | Cost and usage accounting |
| `duration_ms` | `float \| None` | Wall-clock execution time |
| `error_message` | `str \| None` | Error description on non-success |

---

## Artifact Envelope Structure

`ConnectorService.wrap_result_as_artifact()` wraps a result in a domain-agnostic `ExternalArtifact`:

```python
artifact = service.wrap_result_as_artifact(
    result,
    resource_type="document",
    provenance={"run_id": "r1", "agent_role": "researcher"},
)
```

`ExternalArtifact` fields:

| Field | Description |
|-------|-------------|
| `artifact_id` | Auto-generated UUID |
| `source_connector` | Connector that produced the result |
| `provider` | Provider ID |
| `capability_type` | Capability category |
| `resource_type` | Logical type label (caller-supplied) |
| `raw_payload` | Unmodified provider response |
| `normalized_payload` | Optional normalized form (domain module responsibility) |
| `references` | List of `ExternalReference` typed pointers |
| `provenance` | `request_id`, `operation`, `status`, plus caller-supplied metadata |

---

## Cost Tracking Integration

Include a `ConnectorCostInfo` in the provider result to enable cost tracking:

```python
from agent_orchestrator.connectors import ConnectorCostInfo

cost_info = ConnectorCostInfo(
    request_cost=0.002,        # monetary cost of this call
    usage_units=150.0,         # provider-specific units (tokens, API credits, etc.)
    provider_reported_cost=0.002,
    estimated_cost=0.0025,
    currency="USD",
    unit_label="tokens",
)
```

When `ConnectorService` is initialized with a `MetricsCollector`, the executor automatically emits:
- `connector.request_cost`
- `connector.usage_units`
- `connector.provider_cost`
- `connector.estimated_cost`
- `connector.invocations` (counter)

All metrics are tagged with `capability_type`, `provider`, `connector_id`, `operation`.

---

## Retry and Rate Limit Configuration

Attach a `ConnectorRetryPolicy` and/or `ConnectorRateLimit` to a `ConnectorConfig`:

```python
from agent_orchestrator.connectors import (
    ConnectorConfig, ConnectorRetryPolicy, ConnectorRateLimit, CapabilityType
)

config = ConnectorConfig(
    connector_id="search-v1",
    display_name="Search Connector",
    capability_type=CapabilityType.SEARCH,
    provider_id="my-search",
    retry_policy=ConnectorRetryPolicy(
        max_retries=3,
        delay_seconds=1.0,
        backoff_multiplier=2.0,
        retryable_statuses=[ConnectorStatus.TIMEOUT, ConnectorStatus.UNAVAILABLE],
    ),
    rate_limit=ConnectorRateLimit(
        max_requests_per_minute=60,
        max_cost_per_hour=10.0,
        currency="USD",
    ),
)
registry.register_config(config)
```

The `ConnectorExecutor` uses the retry policy for exponential backoff. Rate limiting enforcement is the caller's responsibility (the `ConnectorRateLimit` model is available for inspection).

---

## Execution Tracing

Every connector invocation is recorded in the `ConnectorTraceStore` (in-memory ring buffer, default 1000 entries):

```python
# Query traces for a specific run
traces = service.get_traces(run_id="r1", limit=50)

# Filter by connector or capability
traces = service.get_traces(
    connector_id="my-search",
    capability_type=CapabilityType.SEARCH,
)

# Get aggregated summary
summary = service.get_trace_summary()
# {"total_traces": 42, "by_status": {"success": 40, "failure": 2}, "by_capability": {...}}
```

`ConnectorExecutionTrace` captures:
- `request_id`, `run_id`, `workflow_id`, `module_name`, `agent_role`
- `connector_id`, `provider`, `capability_type`, `operation`
- `parameter_keys` (not values — avoids logging sensitive data)
- `status`, `duration_ms`, `cost_info`, `error_message`
- `attempt_number` — which retry attempt produced this trace

---

## Extension Guidelines for New Providers

### 1. Implement the Protocol

```python
class MyTicketingProvider:
    def get_descriptor(self) -> ConnectorProviderDescriptor:
        return ConnectorProviderDescriptor(
            provider_id="my-ticketing",
            display_name="My Ticketing System",
            capability_types=[CapabilityType.TICKETING],
            version="2.1.0",
            auth_required=True,
            operations=[
                ConnectorOperationDescriptor(
                    operation="create_ticket",
                    description="Create a new ticket",
                    capability_type=CapabilityType.TICKETING,
                    read_only=False,
                    required_parameters=["title", "description"],
                    optional_parameters=["priority", "assignee"],
                ),
                ConnectorOperationDescriptor(
                    operation="get_ticket",
                    description="Retrieve ticket by ID",
                    capability_type=CapabilityType.TICKETING,
                    read_only=True,
                    required_parameters=["ticket_id"],
                ),
            ],
        )

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        if request.operation == "create_ticket":
            return await self._create_ticket(request)
        if request.operation == "get_ticket":
            return await self._get_ticket(request)
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id="my-ticketing",
            provider="my-ticketing",
            capability_type=request.capability_type,
            operation=request.operation,
            status=ConnectorStatus.NOT_FOUND,
            error_message=f"Unknown operation: {request.operation}",
        )
```

### 2. Register with the Registry

```python
engine._connector_registry.register_provider(MyTicketingProvider())
engine._connector_registry.register_config(ConnectorConfig(
    connector_id="ticketing-v1",
    display_name="My Ticketing System",
    capability_type=CapabilityType.TICKETING,
    provider_id="my-ticketing",
    retry_policy=ConnectorRetryPolicy(max_retries=2),
))
```

### 3. Invoke from Domain Code

```python
result = await engine.connector_service.execute(
    capability_type=CapabilityType.TICKETING,
    operation="create_ticket",
    parameters={"title": "Issue found", "description": "..."},
    context={"run_id": run_id, "agent_role": "analyst"},
)
if result.status == ConnectorStatus.SUCCESS:
    ticket_id = result.payload["ticket_id"]
```

### 4. Design Invariants

- **No domain logic in the framework** — providers are domain code; the framework is generic infrastructure
- **All errors normalized** — providers should return error statuses rather than raising exceptions; the executor normalizes uncaught exceptions to `FAILURE` status
- **No secrets in traces or audit records** — use `parameter_keys` (not values) and mask sensitive fields in provider implementations
- **Idempotency** — design operations to be safely retried when used with `ConnectorRetryPolicy`
- **Cost reporting** — always populate `ConnectorCostInfo` when cost data is available from the provider

---

## Authentication Abstraction

Connectors may require authentication to reach external systems. The platform provides a **credential-reference** model: it never stores or logs actual credentials. Only environment variable names and auth metadata are tracked.

### AuthType

```python
from agent_orchestrator.connectors import AuthType

AuthType.NONE           # No authentication
AuthType.API_KEY        # API key injection via a header
AuthType.BEARER_TOKEN   # Bearer token (OAuth2 access token, JWT)
AuthType.OAUTH2         # Full OAuth2 flow with token_endpoint
AuthType.BASIC          # HTTP Basic auth
AuthType.CUSTOM         # Provider-defined authentication
```

### ConnectorAuthConfig

```python
from agent_orchestrator.connectors import ConnectorAuthConfig, AuthType

auth = ConnectorAuthConfig(
    auth_type=AuthType.API_KEY,
    credential_env_var="MY_SERVICE_API_KEY",   # name of env var, NOT the value
    credential_header="X-API-Key",
)
```

Attach to `ConnectorConfig`:

```python
config = ConnectorConfig(
    connector_id="my-search",
    display_name="My Search",
    capability_type=CapabilityType.SEARCH,
    provider_id="my-search-provider",
    auth_config=auth.model_dump(),   # stored as dict — avoids circular import
)
```

### ConnectorSessionContext

At runtime, build a `ConnectorSessionContext` from the auth config and pass it in the invocation request context:

```python
from agent_orchestrator.connectors import build_session_context

ctx = build_session_context(auth)
# ctx is None if auth_type is NONE — no authentication needed
```

`ConnectorSessionContext` contains only references, never raw credentials. Use `to_log_summary()` when logging:

```python
logger.info("Auth context: %s", ctx.to_log_summary())
# {"auth_type": "api_key", "has_credential_env_var": True, "scopes": []}
```

**Never log the full `ConnectorSessionContext` or `ConnectorAuthConfig` objects** — always use `to_log_summary()`.

### Why the platform never stores credentials

- Credentials are resolved at runtime from environment variables by the provider implementation
- `ConnectorAuthConfig.credential_env_var` holds the *name* of the env var, not its value
- Audit records, traces, and logs contain only the auth type and whether a credential reference is set — never the credential itself
- `ConnectorProviderDescriptor.auth_type` (string) signals to operators which auth mechanism is needed, without requiring the provider to import `AuthType`

---

## Normalized Capability Artifacts

The `normalized` module provides capability-specific, domain-agnostic schemas for common connector outputs. These are platform-level — not domain-specific. A `SearchResultArtifact` works for any search provider.

### Available Normalized Types

| Capability | Class | Required Fields |
|------------|-------|-----------------|
| `search` | `SearchResultArtifact` | `query` |
| `documents` | `DocumentArtifact` | *(none required beyond base)* |
| `messaging` | `MessageArtifact` | *(none required beyond base)* |
| `ticketing` | `TicketArtifact` | `ticket_id`, `title` |
| `repository` | `RepositoryArtifact` | `name` |
| `telemetry` | `TelemetryArtifact` | `metric_name`, `value` |
| `identity` | `IdentityArtifact` | `principal_id` |

All normalized artifact classes:
- Extend `NormalizedArtifactBase` (auto-generated `artifact_id`, `timestamp`, `source_connector`, `provider`, `capability_type`, `metadata`)
- Are `frozen=True` Pydantic models — immutable after construction
- Contain no domain-specific field names (enforced by test invariant)

### Using Normalized Artifacts

```python
from agent_orchestrator.connectors.normalized import SearchResultArtifact, SearchResultItem

artifact = SearchResultArtifact(
    source_connector="my-search",
    provider="my-search-provider",
    query="what is the capital of France",
    results=[
        SearchResultItem(rank=1, title="Paris", url="https://example.com/paris"),
    ],
    total_count=1,
)
```

### `get_normalized_type()`

Returns the artifact class for a capability type, or `None` if no schema is defined:

```python
from agent_orchestrator.connectors.normalized import get_normalized_type
from agent_orchestrator.connectors import CapabilityType

cls = get_normalized_type(CapabilityType.TICKETING)  # TicketArtifact
cls = get_normalized_type(CapabilityType.EXTERNAL_API)  # None
```

### `try_normalize()`

Best-effort normalization from a raw payload dict. Never raises — returns `None` on failure:

```python
from agent_orchestrator.connectors.normalized import try_normalize
from agent_orchestrator.connectors import CapabilityType

artifact = try_normalize(
    payload={"query": "example", "results": [{"rank": 1, "title": "A result"}]},
    capability_type=CapabilityType.SEARCH,
    source_connector="my-connector",
    provider="my-provider",
)
if artifact is not None:
    # artifact is a SearchResultArtifact
    pass
```

**Note:** Do not include `source_connector` or `provider` in the payload dict — they are passed as explicit arguments.

### Why `threat_intel` is NOT in the platform capability taxonomy

Threat intelligence is a **domain concept**, not a platform capability category. The platform capability taxonomy (`CapabilityType`) lists generic external system categories: `search`, `documents`, `messaging`, etc. A threat intelligence feed would be accessed via `CapabilityType.EXTERNAL_API` or `CapabilityType.SEARCH`. Domain modules (e.g. a security domain) define what constitutes a threat intelligence result and how to interpret it — that knowledge lives in domain code, not in the platform connector framework.

This separation ensures the framework remains domain-agnostic and reusable across any industry vertical.

---

## Approval-Gated Write Operations

The `requires_approval` flag on `ConnectorPermissionPolicy` gates write operations on explicit human approval, without permanently denying them.

### How it works

```python
from agent_orchestrator.connectors import ConnectorPermissionPolicy, CapabilityType

policy = ConnectorPermissionPolicy(
    description="Ticketing writes require approval",
    requires_approval=True,
    allowed_capability_types=[CapabilityType.TICKETING],
)
```

When `requires_approval=True`:
- Read operations (those starting with `get`, `list`, `read`, `fetch`, `query`, `search`) are **allowed** without approval
- All other operations return `ConnectorStatus.REQUIRES_APPROVAL`

### Policy evaluation outcomes

`evaluate_permission_detailed()` returns a `PermissionEvaluationResult` with three possible outcomes:

| Outcome | Meaning |
|---------|---------|
| `PermissionOutcome.ALLOW` | Invocation permitted |
| `PermissionOutcome.DENY` | Permanently blocked by policy |
| `PermissionOutcome.REQUIRES_APPROVAL` | Write gated — needs human approval before proceeding |

```python
from agent_orchestrator.connectors.permissions import (
    evaluate_permission_detailed, PermissionOutcome
)

result = evaluate_permission_detailed(request, policies)
if result.outcome == PermissionOutcome.REQUIRES_APPROVAL:
    # Queue for human review
    review_queue.enqueue(request, reason=result.reason)
```

The existing `evaluate_permission()` function is unchanged — it returns a plain `bool` and remains backward compatible.

### Service behavior

`ConnectorService.execute()` maps `REQUIRES_APPROVAL` to `ConnectorStatus.REQUIRES_APPROVAL` in the result. The caller inspects the status and decides whether to queue the request for review:

```python
result = await service.execute(
    capability_type=CapabilityType.TICKETING,
    operation="create_ticket",
    parameters={"title": "Deploy v2.0"},
)
if result.status == ConnectorStatus.REQUIRES_APPROVAL:
    # Surface to operator for approval
    pass
```

---

## Cost Metadata

`ConnectorCostMetadata` is a billing metadata model for platform-level accounting. It does not affect execution — it is an accounting reference for operators and FinOps tooling.

```python
from agent_orchestrator.connectors import ConnectorCostMetadata, ConnectorConfig

config = ConnectorConfig(
    connector_id="search-prod",
    display_name="Production Search",
    capability_type=CapabilityType.SEARCH,
    provider_id="my-search",
    cost_metadata=ConnectorCostMetadata(
        billing_label="search-prod",
        cost_center="engineering",
        unit_price=0.001,
        currency="USD",
        notes="Per-query cost at tier-2 pricing",
    ),
)
```

`ConnectorCostMetadata` fields:

| Field | Type | Description |
|-------|------|-------------|
| `billing_label` | `str \| None` | Label for billing dashboards |
| `cost_center` | `str \| None` | Organizational cost center |
| `unit_price` | `float \| None` | Price per invocation unit |
| `currency` | `str` | Currency code (default: `"USD"`) |
| `notes` | `str \| None` | Free-text billing notes |

Note: `ConnectorCostMetadata` is for *billing reference metadata*. Actual per-invocation cost tracking at runtime uses `ConnectorCostInfo` (returned by providers in `ConnectorInvocationResult`).

---

## Automatic Provider Discovery

Providers are discovered and registered automatically at startup — no core platform code changes are required to add a new provider.

### How discovery works

1. `ConnectorProviderDiscovery.discover_builtin_providers()` walks the `agent_orchestrator.connectors.providers` package.
2. Every module whose name does not start with `_` is imported.
3. Classes with `execute()` and `get_descriptor()` that are not abstract are candidates.
4. `from_env()` is called on each candidate to auto-instantiate it with credentials from environment variables.
5. Successfully instantiated providers are registered with the `ConnectorRegistry`.
6. Failures are logged and skipped — the platform always starts.

### from_env() contract

Every provider should implement `from_env()`:

```python
@classmethod
def from_env(cls) -> "MyProvider | None":
    api_key = os.environ.get("MY_API_KEY", "")
    if not api_key:
        return None  # missing credentials → skip silently
    return cls(api_key=api_key)
```

| Return | Meaning |
|---|---|
| Instance | Register this provider |
| `None` | Skip silently (missing credentials) |
| Raises `ValueError` | Skip silently |
| Raises other exception | Log as error, skip |

### Discovery sources

| Source | Usage |
|---|---|
| Built-in package | Automatic at startup |
| External directory | `discovery.discover_directory(path)` or `POST /connectors/discovery/refresh?plugin_directory=...` |
| Entry points | `discovery.discover_entry_points(group="agent_orchestrator.connectors")` |

### Lazy initialization

Use `make_lazy_provider()` to defer construction until first use:

```python
from agent_orchestrator.connectors.discovery import make_lazy_provider

provider = make_lazy_provider(
    factory=lambda: MyProvider(api_key=fetch_from_vault("MY_KEY")),
    provider_id="search.my",
    display_name="MySearch",
    capability_types=[CapabilityType.SEARCH],
    operations=_OPS,
)
registry.register_provider(provider)
```

See `docs/connector-provider-development.md` for a complete guide.

---

## REST API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/connectors/capabilities` | `GET` | List all registered capability types |
| `/api/v1/connectors/providers` | `GET` | List all registered provider descriptors |
| `/api/v1/connectors/providers/{provider_id}` | `GET` | Get a specific provider descriptor |
| `/api/v1/connectors/capabilities/{capability_type}/providers` | `GET` | Providers for a capability |
| `/api/v1/connectors/configs` | `GET` | List connector configurations |
| `/api/v1/connectors/configs/{id}` | `GET` | Get a specific connector config |
| `/api/v1/connectors/configs` | `POST` | Register a connector config |
| `/api/v1/connectors/configs/{id}/enable` | `POST` | Enable a connector |
| `/api/v1/connectors/configs/{id}/disable` | `POST` | Disable a connector |
| `/api/v1/connectors/configs/{id}/scoping` | `PUT` | Update module/role scoping |
| `/api/v1/connectors/configs/{id}/policies` | `POST` | Add a permission policy |
| `/api/v1/connectors/configs/{id}/policies/{policy_id}` | `DELETE` | Remove a permission policy |
| `/api/v1/connectors/configs/{id}/permissions` | `GET` | Get effective permissions |
| `/api/v1/connectors/discovery` | `GET` | Discover accessible connectors (by module/role) |
| `/api/v1/connectors/discovery/status` | `GET` | Last provider discovery result |
| `/api/v1/connectors/discovery/refresh` | `POST` | Re-run provider discovery |
| `/api/v1/connectors/traces` | `GET` | Query execution traces (filter by `run_id`, `connector_id`, `limit`) |
| `/api/v1/connectors/traces/summary` | `GET` | Aggregated trace summary |
