# Connector Provider Development Guide

This guide explains how to build a new connector provider and have it discovered and registered automatically by Agent-Orchestrator without modifying any core platform code.

---

## Overview

The connector framework uses a **plugin-style architecture**:

1. You write a provider class that implements `ConnectorProviderProtocol`.
2. You add a `from_env()` classmethod so the discovery system can instantiate it.
3. You place the file in the built-in providers package or an external plugin directory.
4. The platform discovers, validates, and registers the provider at startup automatically.

---

## Provider Interface

Every provider must implement two methods:

```python
from agent_orchestrator.connectors.registry import ConnectorProviderProtocol
from agent_orchestrator.connectors.models import (
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorProviderDescriptor,
)

class MyProvider:
    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return static metadata about this provider."""
        ...

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        """Execute one operation and return the result."""
        ...
```

The protocol is structural (duck-typed) — no inheritance is required.

---

## Minimal Provider Example

```python
"""my_search_provider.py — minimal custom provider example."""
from __future__ import annotations

import os

from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorStatus,
)


class MySearchProvider:
    """Custom search provider backed by MySearch API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("MySearchProvider requires a non-empty api_key")
        self._api_key = api_key

    # ----------------------------------------------------------------
    # Auto-discovery support
    # ----------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "MySearchProvider | None":
        """Return an instance configured from env vars, or None if not set.

        Required env var: MY_SEARCH_API_KEY
        """
        api_key = os.environ.get("MY_SEARCH_API_KEY", "")
        if not api_key:
            return None  # missing credentials → skip, don't crash
        return cls(api_key=api_key)

    # ----------------------------------------------------------------
    # ConnectorProviderProtocol
    # ----------------------------------------------------------------

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        return ConnectorProviderDescriptor(
            provider_id="search.my_search",
            display_name="MySearch",
            capability_types=[CapabilityType.SEARCH],
            version="1.0",
            auth_required=True,
            auth_type="api_key",
            configuration_schema={
                "MY_SEARCH_API_KEY": {
                    "type": "string",
                    "required": True,
                    "description": "API key for the MySearch service",
                }
            },
            operations=[
                ConnectorOperationDescriptor(
                    operation="search",
                    description="Execute a web search",
                    capability_type=CapabilityType.SEARCH,
                    read_only=True,
                    required_parameters=["query"],
                    optional_parameters=["limit"],
                )
            ],
        )

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        if request.operation == "search":
            return await self._search(request)
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id="search.my_search",
            provider="search.my_search",
            capability_type=request.capability_type,
            operation=request.operation,
            status=ConnectorStatus.NOT_FOUND,
            error_message=f"Unknown operation: {request.operation!r}",
        )

    async def _search(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        query = request.parameters.get("query", "")
        # ... call the API here ...
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id="search.my_search",
            provider="search.my_search",
            capability_type=request.capability_type,
            operation=request.operation,
            status=ConnectorStatus.SUCCESS,
            payload={"query": query, "results": []},
        )
```

---

## Provider Descriptor Fields

| Field | Required | Description |
|---|---|---|
| `provider_id` | Yes | Unique dot-notation ID (e.g. `"search.my_search"`) |
| `display_name` | Yes | Human-readable label |
| `capability_types` | Yes | List of `CapabilityType` values this provider supports |
| `operations` | Yes | List of `ConnectorOperationDescriptor` entries |
| `version` | No | Semantic version string (e.g. `"1.0"`) |
| `auth_required` | No | Whether credentials are needed |
| `auth_type` | No | `"api_key"`, `"bearer"`, `"basic"`, `"oauth2"`, `"none"` |
| `configuration_schema` | No | Dict describing required env vars / config keys |
| `metadata` | No | Additional key-value metadata |

---

## Operation Descriptor Fields

| Field | Required | Description |
|---|---|---|
| `operation` | Yes | Operation name (e.g. `"search"`) |
| `description` | Yes | Short description |
| `capability_type` | Yes | `CapabilityType` this operation belongs to |
| `read_only` | No | `True` for safe read operations (default: `True`) |
| `required_parameters` | No | Parameter names that must be present |
| `optional_parameters` | No | Parameter names that may be present |

Read-only operations (`read_only=True`) bypass approval-gated policies. Write operations (`read_only=False`) are subject to `requires_approval` policies.

---

## from_env() Contract

`from_env()` is the hook the discovery system uses to auto-instantiate providers.

| Return value | Meaning |
|---|---|
| A provider instance | Credentials are available; register the provider |
| `None` | Credentials are not set; skip silently (not an error) |
| Raises `ValueError` | Treated as a credential error; skip silently |
| Raises any other exception | Treated as an unexpected failure; logged as an error |

**Never raise** from `from_env()` if the issue is simply missing credentials — return `None` instead. This ensures the platform starts cleanly even when a provider is not configured.

---

## Discovery System

### How it works

At startup, `ConnectorProviderDiscovery.discover_builtin_providers()` is called automatically:

1. The discovery system walks the `agent_orchestrator.connectors.providers` package recursively.
2. Every module whose name does not start with `_` is imported.
3. Classes defined in that module (not imported from elsewhere) are inspected.
4. Classes with both `execute()` and `get_descriptor()` methods and no abstract methods are candidates.
5. `from_env()` is called on each candidate.
6. Successfully instantiated providers are registered with `ConnectorRegistry`.
7. All failures are logged and skipped — they never crash the platform.

### Discovery sources

| Source | API | When used |
|---|---|---|
| Built-in package | `discover_builtin_providers()` | Automatic at startup |
| External directory | `discover_directory(path)` | Manual or via refresh endpoint |
| Entry points | `discover_entry_points(group)` | setuptools plugins |

### Runtime refresh

Discovery can be re-triggered at runtime via the REST API:

```
POST /api/v1/connectors/discovery/refresh
POST /api/v1/connectors/discovery/refresh?plugin_directory=/opt/connectors
```

Or programmatically:

```python
engine.rediscover_providers(plugin_directory=Path("/opt/connectors"))
```

### Discovery status

```
GET /api/v1/connectors/discovery/status
```

Returns:

```json
{
  "registered": ["web_search.tavily", "repository.github"],
  "skipped": ["web_search.serpapi", "web_search.brave"],
  "errors": [],
  "summary": "registered=2 skipped=2 errors=0"
}
```

---

## Built-in Provider Directory Structure

```
src/agent_orchestrator/connectors/providers/
├── __init__.py
├── web_search/
│   ├── __init__.py
│   ├── _base.py              ← abstract base (skipped by discovery)
│   ├── tavily.py             ← TavilySearchProvider
│   ├── serpapi.py            ← SerpAPISearchProvider
│   └── brave.py              ← BraveSearchProvider
├── documents/
│   ├── _base.py
│   └── confluence.py         ← ConfluenceDocumentsProvider
├── messaging/
│   ├── _base.py
│   ├── slack.py              ← SlackMessagingProvider
│   ├── teams.py              ← TeamsMessagingProvider
│   └── email.py              ← EmailMessagingProvider
├── ticketing/
│   ├── _base.py
│   ├── jira.py               ← JiraTicketingProvider
│   └── linear.py             ← LinearTicketingProvider
└── repository/
    ├── _base.py
    ├── github.py             ← GitHubRepositoryProvider
    └── gitlab.py             ← GitLabRepositoryProvider
```

To add a built-in provider: create a new `.py` file (not starting with `_`) in the appropriate subdirectory. Add `from_env()` and it will be discovered automatically.

---

## External Plugin Providers

You can add providers outside the main package by placing them in any directory and pointing the discovery system at it:

```python
# In application startup code
from pathlib import Path
from agent_orchestrator.connectors.discovery import ConnectorProviderDiscovery

discovery = ConnectorProviderDiscovery(registry)
result = discovery.discover_directory(Path("/opt/my-connectors"))
```

Or configure it via the REST API refresh endpoint.

Plugin files must:
- Be valid Python files not starting with `_`
- Define at least one concrete class with `execute()` and `get_descriptor()`
- Implement `from_env()` for auto-instantiation

---

## Setuptools Entry Points

For installable plugins, register your provider via a Python package entry point:

```toml
# pyproject.toml
[project.entry-points."agent_orchestrator.connectors"]
my_search = "my_package.providers:MySearchProvider"
```

Then trigger entry-point discovery:

```python
result = discovery.discover_entry_points(group="agent_orchestrator.connectors")
```

---

## Lazy Initialization

If provider construction is expensive (e.g., connecting to a secrets manager), use `LazyConnectorProvider` to defer initialization until the first `execute()` call:

```python
from agent_orchestrator.connectors.discovery import make_lazy_provider
from agent_orchestrator.connectors.models import CapabilityType

provider = make_lazy_provider(
    factory=lambda: MySearchProvider(api_key=fetch_from_vault("MY_SEARCH_API_KEY")),
    provider_id="search.my_search",
    display_name="MySearch",
    capability_types=[CapabilityType.SEARCH],
    operations=_MY_SEARCH_OPS,
)
registry.register_provider(provider)
```

The `get_descriptor()` method returns a pre-built hint before initialization. The factory is called exactly once on the first `execute()` call. If the factory raises, subsequent calls return `ConnectorStatus.UNAVAILABLE`.

---

## Configuration via Environment Variables

The recommended approach for provider configuration is environment variables. The `from_env()` classmethod reads them. In `docker-compose.yml`:

```yaml
services:
  api:
    environment:
      TAVILY_API_KEY: "${TAVILY_API_KEY}"
      GITHUB_API_TOKEN: "${GITHUB_API_TOKEN}"
      JIRA_BASE_URL: "${JIRA_BASE_URL}"
      JIRA_API_TOKEN: "${JIRA_API_TOKEN}"
```

### Built-in provider environment variables

| Provider | Required | Optional |
|---|---|---|
| `TavilySearchProvider` | `TAVILY_API_KEY` | `TAVILY_SEARCH_DEPTH` |
| `SerpAPISearchProvider` | `SERPAPI_API_KEY` | `SERPAPI_ENGINE` |
| `BraveSearchProvider` | `BRAVE_API_KEY` | — |
| `ConfluenceDocumentsProvider` | `CONFLUENCE_BASE_URL`, `CONFLUENCE_API_TOKEN` | `CONFLUENCE_EMAIL`, `CONFLUENCE_DEFAULT_SPACE` |
| `SlackMessagingProvider` | `SLACK_BOT_TOKEN` | `SLACK_DEFAULT_CHANNEL` |
| `TeamsMessagingProvider` | `TEAMS_WEBHOOK_URL` | `TEAMS_SENDER_NAME` |
| `EmailMessagingProvider` | `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS` | `SMTP_PORT`, `SMTP_USE_TLS` |
| `JiraTicketingProvider` | `JIRA_BASE_URL`, `JIRA_API_TOKEN` | `JIRA_EMAIL`, `JIRA_DEFAULT_PROJECT` |
| `LinearTicketingProvider` | `LINEAR_API_KEY` | `LINEAR_DEFAULT_TEAM_ID` |
| `GitHubRepositoryProvider` | `GITHUB_API_TOKEN` | — |
| `GitLabRepositoryProvider` | `GITLAB_API_TOKEN` | `GITLAB_BASE_URL`, `GITLAB_USE_BEARER` |

---

## Error Isolation

Provider failures never crash the platform. The discovery system:

1. Catches all exceptions during module import, instantiation, and registration.
2. Logs a warning for unexpected failures.
3. Treats `ValueError` (missing credentials) as an expected skip — no log noise.
4. Adds failures to `DiscoveryResult.errors` for observability.
5. Continues processing remaining providers.

A provider registered in the registry that later fails at execution returns a `ConnectorInvocationResult` with `status=ConnectorStatus.FAILURE` — it does not propagate exceptions to callers.

---

## Testing Your Provider

```python
import pytest
from agent_orchestrator.connectors.models import (
    CapabilityType, ConnectorInvocationRequest,
)

class TestMySearchProvider:
    def test_from_env_returns_none_without_key(self, monkeypatch) -> None:
        monkeypatch.delenv("MY_SEARCH_API_KEY", raising=False)
        assert MySearchProvider.from_env() is None

    def test_from_env_returns_instance_with_key(self, monkeypatch) -> None:
        monkeypatch.setenv("MY_SEARCH_API_KEY", "test_key")
        provider = MySearchProvider.from_env()
        assert provider is not None

    def test_descriptor_shape(self) -> None:
        provider = MySearchProvider(api_key="test")
        d = provider.get_descriptor()
        assert d.provider_id == "search.my_search"
        assert CapabilityType.SEARCH in d.capability_types

    @pytest.mark.asyncio
    async def test_search_operation(self) -> None:
        provider = MySearchProvider(api_key="test")
        request = ConnectorInvocationRequest(
            capability_type=CapabilityType.SEARCH,
            operation="search",
            parameters={"query": "python"},
        )
        result = await provider.execute(request)
        assert result.status != ConnectorStatus.NOT_FOUND
```
