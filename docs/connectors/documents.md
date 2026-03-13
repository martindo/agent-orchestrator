# Documents Connector Providers

The Agent Orchestrator ships a Confluence documents connector provider out of the box. It follows the same `BaseDocumentsProvider` architecture as the web search providers and is registered with `ConnectorRegistry` like any other provider.

Future providers (SharePoint, Google Drive, Notion) can be added by implementing `BaseDocumentsProvider` — see [Adding Future Providers](#adding-future-providers).

---

## Provider Overview

| Provider | Class | Auth Mode | Backend |
|----------|-------|-----------|---------|
| Confluence | `ConfluenceDocumentsProvider` | Basic (Cloud) or Bearer (Server/DC) | Confluence REST API v1 |

---

## Architecture: ExternalArtifact Envelope Pattern

All documents operations return results wrapped in an `ExternalArtifact` envelope. This is consistent with the connector framework's design — the envelope provides provenance, references, and a normalized payload without any domain-specific fields.

### resource_type values

| Operation | `resource_type` |
|-----------|-----------------|
| `search_documents` | `"document"` (one per result item) |
| `get_document` | `"document"` |
| `extract_section` | `"document_section"` |

### ExternalArtifact structure

```
ExternalArtifact
  artifact_id         — unique UUID for this envelope
  source_connector    — provider ID (e.g. "documents.confluence")
  provider            — provider ID
  capability_type     — "documents"
  resource_type       — "document" or "document_section"
  raw_payload         — provider's original API response dict
  normalized_payload  — DocumentArtifact fields (document_id, title, content, url, etc.)
  references          — list of ExternalReference (Confluence page URLs)
  provenance          — contextual metadata (space_key, query, selector, etc.)
  created_at          — UTC timestamp
```

---

## Provider Configuration

### Constructor Parameters

#### `ConfluenceDocumentsProvider`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `base_url` | `str` | Yes | Base URL of your Confluence instance (e.g. `https://myorg.atlassian.net`) |
| `api_token` | `str` | Yes | API token (Cloud) or Personal Access Token (Server/DC) |
| `email` | `str | None` | No | User email — required for Cloud (Basic auth). Omit for Server/DC (Bearer auth). |
| `default_space` | `str | None` | No | Default Confluence space key to scope searches when no `scope` parameter is provided. |

### Environment Variables

The recommended pattern is to read credentials from environment variables:

| Variable | Purpose |
|----------|---------|
| `CONFLUENCE_BASE_URL` | Confluence instance base URL |
| `CONFLUENCE_API_TOKEN` | API token or PAT |
| `CONFLUENCE_EMAIL` | User email (Cloud only) |

---

## Authentication

### Basic Auth — Confluence Cloud

Confluence Cloud requires email + API token combined as HTTP Basic auth:

```python
import os
from agent_orchestrator.connectors.providers import ConfluenceDocumentsProvider

provider = ConfluenceDocumentsProvider(
    base_url=os.environ["CONFLUENCE_BASE_URL"],
    api_token=os.environ["CONFLUENCE_API_TOKEN"],
    email=os.environ["CONFLUENCE_EMAIL"],
)
```

The provider encodes `{email}:{api_token}` as Base64 and sets `Authorization: Basic <encoded>`.

### Bearer Auth — Confluence Server / Data Center

For self-hosted Confluence using Personal Access Tokens (PATs), omit `email`:

```python
provider = ConfluenceDocumentsProvider(
    base_url=os.environ["CONFLUENCE_BASE_URL"],
    api_token=os.environ["CONFLUENCE_API_TOKEN"],
)
```

The provider sets `Authorization: Bearer <api_token>`.

---

## Registry Registration and ConnectorService Usage

### Registering the provider

```python
from agent_orchestrator.connectors import ConnectorRegistry
from agent_orchestrator.connectors.providers import ConfluenceDocumentsProvider
import os

provider = ConfluenceDocumentsProvider(
    base_url=os.environ["CONFLUENCE_BASE_URL"],
    api_token=os.environ["CONFLUENCE_API_TOKEN"],
    email=os.environ.get("CONFLUENCE_EMAIL"),
)

registry = ConnectorRegistry()
registry.register_provider(provider)
```

Provider ID after registration: `documents.confluence`

### Using ConnectorService

```python
from agent_orchestrator.connectors import (
    ConnectorService,
    ConnectorInvocationRequest,
    CapabilityType,
)

service = ConnectorService(registry=registry)

request = ConnectorInvocationRequest(
    capability_type=CapabilityType.DOCUMENTS,
    operation="search_documents",
    parameters={"query": "authentication flow", "scope": "ENG", "limit": 10},
    preferred_provider="documents.confluence",
)
result = await service.execute(request, module="research-team", agent_role="researcher")
```

---

## Operations

### `search_documents`

Search Confluence using CQL (Confluence Query Language).

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | `str` | Yes | Search text (e.g. `"authentication flow"`) |
| `scope` | `str` | No | Confluence space key to restrict results (e.g. `"ENG"`) |
| `limit` | `int` | No | Maximum results to return (default: 10) |

#### Output Shape

`ConnectorInvocationResult.payload` is a wrapper dict:

```json
{
  "query": "authentication flow",
  "scope": "ENG",
  "total_count": 2,
  "items": [
    {
      "artifact_id": "uuid",
      "source_connector": "documents.confluence",
      "provider": "documents.confluence",
      "capability_type": "documents",
      "resource_type": "document",
      "raw_payload": { ... },
      "normalized_payload": {
        "artifact_id": "uuid",
        "source_connector": "documents.confluence",
        "provider": "documents.confluence",
        "capability_type": "documents",
        "document_id": "111",
        "title": "Auth Flow",
        "content": "This page describes the auth flow...",
        "content_type": "text/plain",
        "url": "https://myorg.atlassian.net/wiki/spaces/ENG/pages/111",
        "size_bytes": 42,
        "timestamp": "2026-03-11T00:00:00Z",
        "metadata": {}
      },
      "references": [
        {
          "ref_id": "uuid",
          "provider": "documents.confluence",
          "resource_type": "confluence_page",
          "external_id": "111",
          "url": "https://myorg.atlassian.net/wiki/spaces/ENG/pages/111",
          "metadata": {"space_key": "ENG"}
        }
      ],
      "provenance": {"query": "authentication flow", "scope": "ENG", "provider": "confluence"},
      "created_at": "2026-03-11T00:00:00Z"
    }
  ]
}
```

---

### `get_document`

Retrieve a full Confluence page by its content ID, including the complete `body.storage` HTML.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `document_id` | `str` | Yes | Confluence content ID (numeric string, e.g. `"123456"`) |

#### Output Shape

`ConnectorInvocationResult.payload` is a single `ExternalArtifact` dict:

```json
{
  "artifact_id": "uuid",
  "source_connector": "documents.confluence",
  "provider": "documents.confluence",
  "capability_type": "documents",
  "resource_type": "document",
  "raw_payload": { "id": "123456", "title": "Architecture Guide", ... },
  "normalized_payload": {
    "document_id": "123456",
    "title": "Architecture Guide",
    "content": "<p>Full HTML body from body.storage</p>",
    "content_type": "text/html",
    "url": "https://myorg.atlassian.net/wiki/spaces/ARCH/pages/123456",
    ...
  },
  "references": [
    {
      "provider": "documents.confluence",
      "resource_type": "confluence_page",
      "external_id": "123456",
      "url": "https://myorg.atlassian.net/wiki/spaces/ARCH/pages/123456",
      "metadata": {"space_key": "ARCH"}
    }
  ],
  "provenance": {"space_key": "ARCH", "provider": "confluence"}
}
```

---

### `extract_section`

Extract a named section from a Confluence page. The selector is matched against heading text (h1-h6) case-insensitively. Returns the HTML content between that heading and the next heading at the same or higher level.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `document_id` | `str` | Yes | Confluence content ID |
| `selector` | `str` | Yes | Heading text to locate (case-insensitive, partial match) |

#### Output Shape

`ConnectorInvocationResult.payload` is a single `ExternalArtifact` dict with `resource_type: "document_section"`:

```json
{
  "artifact_id": "uuid",
  "resource_type": "document_section",
  "normalized_payload": {
    "title": "Architecture Guide § Deployment",
    "content": "<p>Deploy steps HTML...</p>",
    "content_type": "text/html",
    ...
  },
  "provenance": {
    "document_id": "123456",
    "selector": "Deployment",
    "space_key": "ARCH",
    "provider": "confluence"
  }
}
```

If the selector is not found in the document, `normalized_payload.content` will be `null`.

---

## ExternalReference

Each result includes `ExternalReference` entries pointing to the Confluence page. These allow agent modules to follow references to source pages without re-issuing connector calls.

```python
ref = result.payload["references"][0]
# ref["url"]         → full Confluence page URL
# ref["external_id"] → Confluence content ID
# ref["metadata"]["space_key"] → Confluence space key
```

---

## Module Integration Notes

### Research Team

Use `search_documents` to retrieve background reading before synthesizing a report:

```python
request = ConnectorInvocationRequest(
    capability_type=CapabilityType.DOCUMENTS,
    operation="search_documents",
    parameters={"query": "competitive landscape Q1 2026", "scope": "RESEARCH", "limit": 5},
)
```

### Security Investigation

Use `get_document` to pull the full incident response runbook, then `extract_section` to focus on the relevant remediation steps:

```python
get_req = ConnectorInvocationRequest(
    capability_type=CapabilityType.DOCUMENTS,
    operation="extract_section",
    parameters={"document_id": "incident-runbook-id", "selector": "Remediation Steps"},
)
```

### Software Development Team

Use `search_documents` scoped to the engineering space to find architecture decision records (ADRs) relevant to a feature branch:

```python
request = ConnectorInvocationRequest(
    capability_type=CapabilityType.DOCUMENTS,
    operation="search_documents",
    parameters={"query": "database migration strategy", "scope": "ENG"},
)
```

---

## Adding Future Providers

To add a new documents provider (e.g. SharePoint, Google Drive, Notion), implement `BaseDocumentsProvider`:

```python
from agent_orchestrator.connectors.providers.documents._base import (
    BaseDocumentsProvider,
    DocumentsProviderError,
)
from agent_orchestrator.connectors.models import ConnectorCostInfo

class SharePointDocumentsProvider(BaseDocumentsProvider):

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        if not client_secret:
            raise ValueError("SharePointDocumentsProvider requires client_secret")
        self._api_token = client_secret  # used by is_available()
        ...

    @property
    def provider_id(self) -> str:
        return "documents.sharepoint"

    @property
    def display_name(self) -> str:
        return "SharePoint Documents"

    async def _search_documents(
        self, query: str, scope: str | None, limit: int
    ) -> tuple[dict, ConnectorCostInfo | None]:
        # call Microsoft Graph API, build ExternalArtifact via _make_document_artifact()
        ...

    async def _get_document(
        self, document_id: str
    ) -> tuple[dict, ConnectorCostInfo | None]:
        ...

    async def _extract_section(
        self, document_id: str, selector: str
    ) -> tuple[dict, ConnectorCostInfo | None]:
        ...
```

All three abstract methods must return `(payload_dict, cost_info_or_none)`. Use `_make_document_artifact()` to build the `ExternalArtifact` envelope so that the output shape is consistent with the platform contract.

Register the new provider in `connectors/providers/documents/__init__.py` and `connectors/providers/__init__.py`.
