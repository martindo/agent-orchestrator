# Connector Capability Framework

The Connector Capability Framework provides a domain-agnostic layer for invoking external systems (search engines, document stores, ticketing systems, repositories, etc.) from within orchestrated workflows. All connector concepts are generic — no domain-specific logic is embedded in the framework itself.

---

## Overview

```
OrchestrationEngine
  └── ConnectorService
        ├── ConnectorRegistry  (providers + configs)
        │     ├── ConnectorProviderProtocol  (interface)
        │     └── ConnectorConfig            (per-connector settings + policies)
        ├── Permission evaluation  (evaluate_permission)
        └── Audit integration      (log_connector_invocation → AuditLogger)
```

Domain modules call `ConnectorService.execute(capability_type, operation, parameters, context)` and receive a `ConnectorInvocationResult`. They may optionally wrap the result in an `ExternalArtifact` for uniform provenance tracking.

---

## Capability Types

| Value | Description |
|-------|-------------|
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

## Core Models

### ConnectorInvocationRequest

Input to `ConnectorService.execute`. Carries:
- `capability_type` — the category of external system
- `operation` — specific action (e.g. `"query"`, `"create_issue"`)
- `parameters` — operation-specific key/value pairs
- `context` — platform context: `run_id`, `workflow_id`, `agent_role`, `module_name`, `work_id`
- `preferred_provider` — optional provider override
- `timeout_seconds` — optional per-call timeout

### ConnectorInvocationResult

Output from provider execution. Carries:
- `status` — `ConnectorStatus` enum (success, failure, partial, timeout, permission_denied, not_found, unavailable)
- `payload` — arbitrary result dict (provider-specific shape)
- `cost_info` — optional `ConnectorCostInfo` (request_cost, usage_units, currency)
- `duration_ms` — wall-clock execution time
- `error_message` — set on non-success statuses

### ExternalArtifact

Domain-agnostic envelope for wrapping a connector result. Contains:
- `source_connector`, `provider`, `capability_type`, `resource_type`
- `raw_payload` — unmodified provider response
- `normalized_payload` — optional normalized form (domain module responsibility)
- `references` — list of `ExternalReference` (typed pointers to external objects)
- `provenance` — `request_id`, `operation`, `status`, plus any caller-supplied metadata

---

## ConnectorRegistry

Thread-safe store for:
- **Provider instances** (`ConnectorProviderProtocol`) — indexed by `provider_id`
- **Connector configs** (`ConnectorConfig`) — indexed by `connector_id`

```python
registry = ConnectorRegistry()
registry.register_provider(my_provider)
registry.register_config(ConnectorConfig(...))
providers = registry.find_providers_for_capability(CapabilityType.SEARCH)
```

---

## Implementing a Provider

Providers use structural typing via `ConnectorProviderProtocol` — no inheritance required:

```python
class MySearchProvider:
    def get_descriptor(self) -> ConnectorProviderDescriptor:
        return ConnectorProviderDescriptor(
            provider_id="my-search",
            display_name="My Search Engine",
            capability_types=[CapabilityType.SEARCH],
        )

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        # ... call external API ...
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id="my-search",
            provider="my-search",
            capability_type=request.capability_type,
            operation=request.operation,
            status=ConnectorStatus.SUCCESS,
            payload={"results": [...]},
        )
```

---

## Permission Policies

`ConnectorPermissionPolicy` objects are attached to `ConnectorConfig` and evaluated before each invocation.

**Evaluation order:**
1. If the policy is disabled, skip it.
2. If the policy scope (`allowed_modules`, `allowed_agent_roles`) does not match the request context, skip it.
3. Check `denied_capability_types` and `denied_operations` — if matched, deny immediately.
4. Check `allowed_capability_types` and `allowed_operations` — if set and not matched, deny.
5. If all checks pass, permit.
6. If no policy applies, permit by default.

```python
policy = ConnectorPermissionPolicy(
    description="Read-only search for all modules",
    allowed_capability_types=[CapabilityType.SEARCH],
    allowed_operations=["query"],
    read_only=True,
)
```

---

## Audit Integration

Every `ConnectorService.execute` call — successful or not — writes a `SYSTEM_EVENT` record to the platform `AuditLogger` when one is configured. The record includes:
- `capability_type`, `connector_id`, `provider`, `operation`
- `parameter_keys` (not values — avoids logging sensitive data)
- `status`, `duration_ms`, `cost_info`
- Platform context: `run_id`, `workflow_id`, `module_name`, `agent_role`

---

## Engine Integration

`ConnectorService` is created by `OrchestrationEngine._initialize_components()` and is accessible via:

```python
engine.connector_service  # ConnectorService | None
engine._connector_registry  # ConnectorRegistry (register providers here)
```

Register providers before or after engine start:

```python
engine._connector_registry.register_provider(MySearchProvider())
result = await engine.connector_service.execute(
    capability_type=CapabilityType.SEARCH,
    operation="query",
    parameters={"q": "example"},
    context={"run_id": "r1"},
)
```

---

## REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/connectors/capabilities` | `GET` | List all registered capability types |
| `/api/v1/connectors/providers` | `GET` | List registered provider descriptors |

---

## ConnectorExecutor — Retry, Timeout, and Cost Tracking

`ConnectorExecutor` is the reusable execution layer that `ConnectorService` uses internally. It is responsible for:

- **Asyncio timeout** — wraps provider calls with `asyncio.wait_for` when `timeout_seconds` is set on the request
- **Retry with exponential backoff** — driven by `ConnectorRetryPolicy` (max retries, delay, backoff multiplier, retryable status set)
- **Error normalization** — all uncaught provider exceptions are captured and returned as `ConnectorStatus.FAILURE` results; the executor never raises
- **Cost metric emission** — when a `MetricsCollector` is provided, emits `connector.request_cost`, `connector.usage_units`, `connector.provider_cost`, `connector.estimated_cost`, and `connector.invocations` counters
- **Trace recording** — emits a `ConnectorExecutionTrace` to `ConnectorTraceStore` after each attempt

### ConnectorRetryPolicy

Attached to `ConnectorConfig` and retrieved by `ConnectorService` before each invocation:

```python
ConnectorRetryPolicy(
    max_retries=3,           # 0 = no retries (default)
    delay_seconds=1.0,       # initial delay
    backoff_multiplier=2.0,  # exponential factor
    retryable_statuses=[ConnectorStatus.TIMEOUT, ConnectorStatus.UNAVAILABLE],
)
```

### ConnectorRateLimit

Available as metadata on `ConnectorConfig` for upstream enforcement:

```python
ConnectorRateLimit(
    max_requests_per_minute=60,
    max_cost_per_hour=10.0,
    currency="USD",
)
```

---

## ConnectorTraceStore — Execution Tracing

`ConnectorTraceStore` is a thread-safe, in-memory ring-buffer (default 1000 entries). It stores `ConnectorExecutionTrace` records — one per provider attempt.

```
ConnectorService.execute()
  └── ConnectorExecutor._attempt()
        └── ConnectorExecutor._record_trace()
              └── ConnectorTraceStore.record(trace)
```

`ConnectorExecutionTrace` captures the full context of each invocation attempt:

| Field | Description |
|-------|-------------|
| `trace_id` | Auto-generated UUID |
| `request_id` | Links to `ConnectorInvocationRequest` |
| `run_id`, `workflow_id` | Platform context from request |
| `module_name`, `agent_role` | Caller context from request |
| `connector_id`, `provider` | Which provider handled the call |
| `capability_type`, `operation` | What was requested |
| `parameter_keys` | Keys only — no values, to avoid logging secrets |
| `status`, `duration_ms` | Outcome and timing |
| `cost_info` | Cost and usage if reported by provider |
| `error_message` | Set on non-success statuses |
| `attempt_number` | Retry attempt index (1 = first attempt) |

Query API:

```python
service.get_traces(run_id="r1", connector_id="my-search", limit=50)
service.get_trace_summary()  # {"total_traces": N, "by_status": {...}, "by_capability": {...}}
```

---

## Provider Selection — find_provider_for_operation

`ConnectorRegistry.find_provider_for_operation()` implements a three-level selection strategy:

1. **Preferred provider** — if `preferred_provider` is specified and that provider supports the capability, use it
2. **Operation declaration match** — prefer providers that explicitly declare the operation in their `operations` list
3. **Fallback** — use the first enabled provider for the capability type

---

## Extension Boundaries

The connector framework defines clear boundaries between platform infrastructure and provider implementations:

| Concern | Location |
|---------|----------|
| Capability taxonomy | `CapabilityType` enum in `models.py` |
| Provider interface | `ConnectorProviderProtocol` (structural typing) |
| Execution lifecycle | `ConnectorExecutor` (retry, timeout, error normalization) |
| Permission enforcement | `evaluate_permission()` in `permissions.py` |
| Trace recording | `ConnectorTraceStore` in `trace.py` |
| Cost metrics | `ConnectorExecutor._record_cost()` → `MetricsCollector` |
| Audit trail | `log_connector_invocation()` in `audit.py` → `AuditLogger` |
| Provider implementation | External to the framework (domain or infrastructure code) |
| Domain artifact transformation | External to the framework (domain modules) |

**Platform code** (this framework) handles: routing, retries, timeouts, permissions, tracing, auditing, metrics.

**Provider code** handles: authentication, API calls, response mapping, cost reporting.

**Domain code** handles: interpreting payloads, transforming `ExternalArtifact` into domain-specific types.

---

## REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/connectors/capabilities` | `GET` | List all registered capability types |
| `/api/v1/connectors/providers` | `GET` | List registered provider descriptors |
| `/api/v1/connectors/providers/{provider_id}` | `GET` | Get a specific provider descriptor |
| `/api/v1/connectors/capabilities/{capability_type}/providers` | `GET` | Providers for a capability |
| `/api/v1/connectors/configs` | `GET` | List connector configurations |
| `/api/v1/connectors/traces` | `GET` | Query execution traces |
| `/api/v1/connectors/traces/summary` | `GET` | Aggregated trace summary |

---

## Design Principles

- **Domain-agnostic** — no domain-specific fields or logic anywhere in the framework
- **Protocol-based** — providers implement `ConnectorProviderProtocol` via structural typing
- **Thread-safe** — registry and trace store protected by `threading.Lock()`
- **Fail-safe** — all invocation errors are captured in `ConnectorInvocationResult`; no uncaught exceptions propagate to callers
- **Auditable** — every invocation recorded in the platform audit trail
- **Observable** — execution traces stored in ring buffer, queryable by run/connector/capability
- **Cost-aware** — optional `ConnectorCostInfo` on every result for budget tracking
- **Policy-governed** — permission policies evaluated before every invocation
- **Retryable** — configurable retry policy with exponential backoff per capability type
