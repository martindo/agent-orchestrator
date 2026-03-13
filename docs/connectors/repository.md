# Repository Connector Capability

The **repository** capability lets agents read source code, browse commit history, and inspect pull requests across hosted Git services through a single standardised interface. All operations are read-only — no repository state is ever mutated.

## Supported Providers

| Provider | `provider_id`        | Auth Method                          |
|----------|----------------------|--------------------------------------|
| GitHub   | `repository.github`  | Bearer token (PAT or fine-grained)   |
| GitLab   | `repository.gitlab`  | PRIVATE-TOKEN header or Bearer (OAuth) |

---

## Operations

| Operation          | read_only | Required Parameters       | Optional Parameters |
|--------------------|-----------|---------------------------|---------------------|
| `search_repo`      | `True`    | `query`                   | `limit` (default 25) |
| `get_file`         | `True`    | `repo_id`, `path`         | `ref`               |
| `list_commits`     | `True`    | `repo_id`                 | `ref`, `limit` (default 25) |
| `get_pull_request` | `True`    | `repo_id`, `pr_id`        |                     |

All operations are `read_only=True`. Even under a `ConnectorPermissionPolicy` with `requires_approval=True`, every repository operation is allowed without approval because each operation name begins with a read-like prefix (`search`, `get`, `list`).

---

## Return Value: ExternalArtifact

All operations return a `ConnectorInvocationResult` whose `payload` is an `ExternalArtifact` dict.

### search_repo → resource_type `"repository"`

```python
{
    "capability_type": "repository",
    "resource_type": "repository",
    "provider": "repository.github",
    "normalized_payload": null,
    "raw_payload": {
        "query": "python cli",
        "total": 120,
        "items": [
            {
                "repo_id": "pallets/click",
                "name": "pallets/click",
                "description": "Python composable command line interface toolkit",
                "url": "https://github.com/pallets/click",
                "default_branch": "main"
            },
            ...
        ]
    }
}
```

### get_file → resource_type `"repo_file"`

```python
{
    "capability_type": "repository",
    "resource_type": "repo_file",
    "provider": "repository.github",
    "normalized_payload": {
        "repo_id": "octocat/hello-world",
        "path": "README.md",
        "ref": "main",
        "content": "# Hello World\nWelcome...",
        "encoding": "utf-8",         # or "base64" for binary files
        "size": 1024,
        "url": "https://github.com/octocat/hello-world/blob/main/README.md"
    },
    "raw_payload": { ... },           # provider raw response
    "references": [
        {
            "provider": "repository.github",
            "resource_type": "github_file",
            "external_id": "<git blob sha>",
            "url": "..."
        }
    ]
}
```

### list_commits → resource_type `"commit_list"`

```python
{
    "capability_type": "repository",
    "resource_type": "commit_list",
    "provider": "repository.github",
    "normalized_payload": null,
    "raw_payload": {
        "repo_id": "octocat/hello-world",
        "ref": "main",
        "total": 10,
        "commits": [
            {
                "sha": "abc123",
                "message": "Fix login bug",
                "author": "Alice",
                "authored_at": "2024-01-01T00:00:00Z",
                "url": "https://github.com/octocat/hello-world/commit/abc123"
            },
            ...
        ]
    }
}
```

### get_pull_request → resource_type `"pull_request"`

```python
{
    "capability_type": "repository",
    "resource_type": "pull_request",
    "provider": "repository.github",
    "normalized_payload": {
        "repo_id": "octocat/hello-world",
        "pr_id": "42",
        "title": "Add dark mode",
        "description": "Closes #100",
        "state": "open",
        "author": "alice",
        "source_branch": "feature/dark-mode",
        "target_branch": "main",
        "url": "https://github.com/octocat/hello-world/pull/42"
    },
    "raw_payload": { ... },
    "references": [
        {
            "provider": "repository.github",
            "resource_type": "github_pull_request",
            "external_id": "42",
            "url": "..."
        }
    ]
}
```

---

## GitHub Provider

### Setup

```python
from agent_orchestrator.connectors.providers.repository import GitHubRepositoryProvider

provider = GitHubRepositoryProvider(api_token="ghp_...")
```

Minimum token scopes:
- Classic PAT: `public_repo` (or `repo` for private repos)
- Fine-grained: **Contents** (read), **Pull requests** (read)

### search_repo

Uses GitHub's [Search API](https://docs.github.com/en/rest/search/search#search-repositories).
The `query` parameter supports all GitHub search qualifiers.

```python
result = await service.execute(
    capability_type="repository",
    operation="search_repo",
    parameters={"query": "language:python topic:cli stars:>100", "limit": "20"},
    preferred_provider="repository.github",
)
```

### get_file

The `repo_id` is the repository's `{owner}/{repo}` full name. File content is
automatically decoded from base64 to UTF-8 text; binary files are returned
with `encoding="base64"`.

```python
result = await service.execute(
    capability_type="repository",
    operation="get_file",
    parameters={
        "repo_id": "octocat/hello-world",
        "path": "src/main.py",
        "ref": "main",        # branch, tag, or commit SHA
    },
    preferred_provider="repository.github",
)
```

### list_commits

```python
result = await service.execute(
    capability_type="repository",
    operation="list_commits",
    parameters={
        "repo_id": "octocat/hello-world",
        "ref": "develop",     # optional branch/tag/SHA
        "limit": "50",
    },
    preferred_provider="repository.github",
)
```

### get_pull_request

```python
result = await service.execute(
    capability_type="repository",
    operation="get_pull_request",
    parameters={"repo_id": "octocat/hello-world", "pr_id": "42"},
    preferred_provider="repository.github",
)
```

---

## GitLab Provider

### Setup

```python
from agent_orchestrator.connectors.providers.repository import GitLabRepositoryProvider

# GitLab.com with PRIVATE-TOKEN (default)
provider = GitLabRepositoryProvider(api_token="glpat-...")

# Self-hosted GitLab
provider = GitLabRepositoryProvider(
    api_token="glpat-...",
    base_url="https://gitlab.example.com",
)

# OAuth bearer token
provider = GitLabRepositoryProvider(api_token="oauth-token", use_bearer=True)
```

### repo_id format

The `repo_id` parameter accepts either:
- A **numeric project ID**: `"42"` (recommended — stable even after renames)
- A **namespace/project path**: `"mygroup/myproject"` (automatically URL-encoded)

### search_repo

Uses GitLab's `/projects?search=` endpoint.

```python
result = await service.execute(
    capability_type="repository",
    operation="search_repo",
    parameters={"query": "analytics", "limit": "10"},
    preferred_provider="repository.gitlab",
)
```

### get_file

For GitLab, `pr_id` for `get_pull_request` is the merge request's **IID**
(the project-scoped integer shown in the URL), not the global ID.

```python
result = await service.execute(
    capability_type="repository",
    operation="get_file",
    parameters={
        "repo_id": "42",           # or "mygroup/myproject"
        "path": "src/app.py",
        "ref": "main",
    },
    preferred_provider="repository.gitlab",
)
```

### list_commits

```python
result = await service.execute(
    capability_type="repository",
    operation="list_commits",
    parameters={"repo_id": "42", "ref": "feature/x", "limit": "20"},
    preferred_provider="repository.gitlab",
)
```

### get_pull_request (merge requests)

```python
result = await service.execute(
    capability_type="repository",
    operation="get_pull_request",
    parameters={"repo_id": "42", "pr_id": "7"},  # pr_id = MR IID
    preferred_provider="repository.gitlab",
)
```

---

## Registering Providers

```python
from agent_orchestrator.connectors.registry import ConnectorRegistry
from agent_orchestrator.connectors.providers.repository import (
    GitHubRepositoryProvider,
    GitLabRepositoryProvider,
)

registry = ConnectorRegistry()

registry.register_provider(
    GitHubRepositoryProvider(api_token="ghp_...")
)

registry.register_provider(
    GitLabRepositoryProvider(
        api_token="glpat-...",
        base_url="https://gitlab.example.com",
    )
)
```

---

## Domain-agnosticism

No domain-specific fields are added to the platform core. The `ExternalArtifact`
envelope carries a plain `normalized_payload` dict for `repo_file` and
`pull_request` resource types (with well-known keys documented above). The
existing `RepositoryArtifact` normalized schema is used by `_make_repo_artifact`
for single-repository results. Domain modules may transform any of these
payloads into their own domain-specific structures without touching
platform-core models.
