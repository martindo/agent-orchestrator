# Web Search Connector Providers

The Agent Orchestrator ships three web search connector providers out of the box. They share a common interface (`BaseWebSearchProvider`) and are registered with the `ConnectorRegistry` like any other provider.

---

## Provider Priority Order

| Priority | Provider | Class | Index | Cost / search |
|----------|----------|-------|-------|---------------|
| 1 (Primary) | Tavily | `TavilySearchProvider` | AI-optimized | $0.004 (basic) / $0.008 (advanced) |
| 2 (Secondary) | SerpAPI | `SerpAPISearchProvider` | Google / Bing | $0.005 |
| 3 (Tertiary) | Brave | `BraveSearchProvider` | Independent | $0.003 |

Choose Tavily as the default for AI agent workflows — it returns pre-cleaned, relevance-scored results. Fall back to SerpAPI for Google coverage or Brave for privacy-preserving use cases.

---

## Environment Variables

| Variable | Provider |
|----------|----------|
| `TAVILY_API_KEY` | Tavily |
| `SERPAPI_API_KEY` | SerpAPI |
| `BRAVE_API_KEY` | Brave |

---

## Configuration and Registration

### Instantiating providers

```python
import os
from agent_orchestrator.connectors.providers import (
    TavilySearchProvider,
    SerpAPISearchProvider,
    BraveSearchProvider,
)

tavily  = TavilySearchProvider(api_key=os.environ["TAVILY_API_KEY"])
serpapi = SerpAPISearchProvider(api_key=os.environ["SERPAPI_API_KEY"])
brave   = BraveSearchProvider(api_key=os.environ["BRAVE_API_KEY"])
```

The `TavilySearchProvider` constructor accepts an optional `search_depth` argument (`"basic"` or `"advanced"`, default `"basic"`). `SerpAPISearchProvider` accepts an optional `engine` argument (`"google"`, `"bing"`, etc., default `"google"`).

### Registering with ConnectorRegistry

```python
from agent_orchestrator.connectors import ConnectorRegistry

registry = ConnectorRegistry()
registry.register_provider(tavily)
registry.register_provider(serpapi)
registry.register_provider(brave)
```

Provider IDs after registration:

- `web_search.tavily`
- `web_search.serpapi`
- `web_search.brave`

### Using ConnectorService

```python
from agent_orchestrator.connectors import ConnectorService, ConnectorInvocationRequest, CapabilityType

service = ConnectorService(registry=registry)

request = ConnectorInvocationRequest(
    capability_type=CapabilityType.SEARCH,
    operation="search",
    parameters={"query": "open source LLM frameworks", "limit": 10},
    preferred_provider="web_search.tavily",
)
result = await service.execute(request, module="research-team", agent_role="researcher")
```

---

## Supported Operations

All three providers implement the same three operations.

### `search`

Execute a web search query and return a `SearchResultArtifact`.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `query` | Yes | string | Search query text |
| `limit` | No | int | Max number of results (default: 10) |
| `filters` | No | dict | Provider-specific filter options (see below) |

#### Tavily filters

| Filter key | Type | Description |
|------------|------|-------------|
| `search_depth` | `"basic"` \| `"advanced"` | Overrides the instance-level default depth |
| `include_domains` | list[str] | Restrict results to these domains |
| `exclude_domains` | list[str] | Exclude results from these domains |

#### SerpAPI filters

| Filter key | Type | Description |
|------------|------|-------------|
| `engine` | string | Search engine: `"google"`, `"bing"`, etc. |
| `gl` | string | Country code for Google results (e.g. `"us"`) |
| `hl` | string | Language code (e.g. `"en"`) |

#### Brave filters

| Filter key | Type | Description |
|------------|------|-------------|
| `offset` | int | Pagination offset |
| `country` | string | Country code (e.g. `"US"`) |
| `search_lang` | string | Language code (e.g. `"en"`) |
| `safesearch` | `"off"` \| `"moderate"` \| `"strict"` | Safe search level |

---

### `fetch_page`

Fetch the raw HTML/text content of a URL via httpx.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `url` | Yes | string | URL to retrieve |

Returns a `DocumentArtifact`. No API cost is charged.

---

### `extract_content`

Identical to `fetch_page` — returns the raw page content as a `DocumentArtifact`. Future implementations may add structured extraction (e.g. Readability parsing) behind this operation without changing the interface.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `url` | Yes | string | URL to retrieve |

---

## Output Shapes

### SearchResultArtifact

Returned by the `search` operation.

```json
{
  "artifact_id": "<uuid>",
  "source_connector": "web_search.tavily",
  "provider": "web_search.tavily",
  "capability_type": "search",
  "query": "open source LLM frameworks",
  "results": [
    {
      "rank": 0,
      "title": "LangChain — Build LLM applications",
      "snippet": "LangChain is a framework for developing ...",
      "url": "https://www.langchain.com",
      "score": 0.95,
      "metadata": { "published_date": "2024-01-15" }
    }
  ],
  "total_count": 1,
  "timestamp": "2026-03-11T10:00:00Z",
  "metadata": {}
}
```

### DocumentArtifact

Returned by `fetch_page` and `extract_content`.

```json
{
  "artifact_id": "<uuid>",
  "source_connector": "web_search.tavily",
  "provider": "web_search.tavily",
  "capability_type": "search",
  "url": "https://www.langchain.com",
  "content": "<!DOCTYPE html>...",
  "content_type": "text/html",
  "size_bytes": 48200,
  "timestamp": "2026-03-11T10:00:00Z",
  "metadata": {}
}
```

---

## Cost Tracking

Every `search` invocation populates `ConnectorInvocationResult.cost_info`:

```python
result.cost_info.estimated_cost  # float, USD
result.cost_info.currency         # "USD"
result.cost_info.usage_units      # float — number of results returned
result.cost_info.unit_label       # "results"
```

`fetch_page` and `extract_content` do not call a billed API endpoint, so `cost_info` is `None` for those operations.

Per-provider cost rates (estimated, not billing-authoritative):

| Provider | Rate |
|----------|------|
| Tavily basic | $0.004 / search |
| Tavily advanced | $0.008 / search |
| SerpAPI | $0.005 / search |
| Brave | $0.003 / search |

---

## Permissions

Use `ConnectorPermissionPolicy` to restrict which modules and agent roles may invoke the search connector.

```python
from agent_orchestrator.connectors.models import ConnectorPermissionPolicy, CapabilityType

read_only_search_policy = ConnectorPermissionPolicy(
    description="Allow read-only web search for research agents",
    allowed_capability_types=[CapabilityType.SEARCH],
    allowed_operations=["search", "fetch_page", "extract_content"],
    allowed_modules=["research-team", "security-investigation", "software-dev-team"],
    allowed_agent_roles=["researcher", "analyst", "developer"],
    read_only=True,
)
```

Register the policy on a `ConnectorConfig` to scope it to a specific connector instance:

```python
from agent_orchestrator.connectors.models import ConnectorConfig

config = ConnectorConfig(
    connector_id="web-search-primary",
    display_name="Primary Web Search",
    capability_type=CapabilityType.SEARCH,
    provider_id="web_search.tavily",
    permission_policies=[read_only_search_policy],
)
registry.register_config(config)
```

---

## Module Integration Examples

### Research Team

```python
async def research_topic(topic: str, service: ConnectorService) -> list[dict]:
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="search",
        parameters={"query": topic, "limit": 10},
        preferred_provider="web_search.tavily",
    )
    result = await service.execute(request, module="research-team", agent_role="researcher")
    if result.status == ConnectorStatus.SUCCESS:
        return result.payload["results"]
    return []
```

### Security Investigation

```python
async def investigate_domain(domain: str, service: ConnectorService) -> dict | None:
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="search",
        parameters={
            "query": f"site:{domain} vulnerability disclosure",
            "limit": 5,
            "filters": {"search_depth": "advanced"},
        },
        preferred_provider="web_search.tavily",
    )
    result = await service.execute(
        request, module="security-investigation", agent_role="analyst"
    )
    return result.payload if result.status == ConnectorStatus.SUCCESS else None
```

### Software Development Team

```python
async def fetch_docs_page(url: str, service: ConnectorService) -> str | None:
    request = ConnectorInvocationRequest(
        capability_type=CapabilityType.SEARCH,
        operation="fetch_page",
        parameters={"url": url},
    )
    result = await service.execute(
        request, module="software-dev-team", agent_role="developer"
    )
    if result.status == ConnectorStatus.SUCCESS:
        return result.payload.get("content")
    return None
```

---

## Registering via ConnectorService on Engine Startup

To make the providers available to all agents at engine startup, register them inside your workspace initialization:

```python
from agent_orchestrator.connectors import ConnectorRegistry
from agent_orchestrator.connectors.providers import (
    TavilySearchProvider,
    SerpAPISearchProvider,
    BraveSearchProvider,
)
import os

def build_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    if key := os.getenv("TAVILY_API_KEY"):
        registry.register_provider(TavilySearchProvider(api_key=key))
    if key := os.getenv("SERPAPI_API_KEY"):
        registry.register_provider(SerpAPISearchProvider(api_key=key))
    if key := os.getenv("BRAVE_API_KEY"):
        registry.register_provider(BraveSearchProvider(api_key=key))
    return registry
```

Pass the registry to `OrchestrationEngine` during initialization — the engine exposes it via `engine.connector_service` once started.
