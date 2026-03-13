"""GitLab repository connector provider.

Implements search_repo, get_file, list_commits, and get_pull_request (merge
requests) against the GitLab REST API v4. Supports both GitLab.com and
self-hosted GitLab instances.
"""
from __future__ import annotations

import base64
import logging
import urllib.parse

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import BaseRepositoryProvider, RepositoryProviderError

logger = logging.getLogger(__name__)

_GITLAB_COM_BASE = "https://gitlab.com"


class GitLabRepositoryProvider(BaseRepositoryProvider):
    """GitLab-backed repository connector provider.

    Uses the GitLab REST API v4. Authentication accepts either a personal
    access token (``PRIVATE-TOKEN`` header) or an OAuth bearer token.

    The ``repo_id`` parameter across all operations is the numeric project
    ID or the URL-encoded namespace/project path
    (e.g. ``"42"`` or ``"gitlab-org/gitlab"``). Slashes in namespace paths
    are automatically URL-encoded when building API URLs.

    Example::

        # GitLab.com
        provider = GitLabRepositoryProvider(api_token="glpat-...")

        # Self-hosted
        provider = GitLabRepositoryProvider(
            api_token="glpat-...",
            base_url="https://gitlab.example.com",
        )
    """

    def __init__(
        self,
        api_token: str,
        base_url: str = _GITLAB_COM_BASE,
        use_bearer: bool = False,
    ) -> None:
        if not api_token:
            raise ValueError("GitLabRepositoryProvider requires a non-empty api_token")
        self._api_token = api_token
        self._base_url = base_url.rstrip("/")
        self._use_bearer = use_bearer

    @classmethod
    def from_env(cls) -> "GitLabRepositoryProvider | None":
        """Create an instance from environment variables.

        Required env var: ``GITLAB_API_TOKEN``
        Optional env vars: ``GITLAB_BASE_URL`` (default: ``https://gitlab.com``),
        ``GITLAB_USE_BEARER`` (default: ``false``)

        Returns None if ``GITLAB_API_TOKEN`` is not set.
        """
        import os
        token = os.environ.get("GITLAB_API_TOKEN", "")
        if not token:
            return None
        base_url = os.environ.get("GITLAB_BASE_URL", _GITLAB_COM_BASE)
        use_bearer_str = os.environ.get("GITLAB_USE_BEARER", "false").lower()
        return cls(
            api_token=token,
            base_url=base_url,
            use_bearer=use_bearer_str not in ("false", "0", "no"),
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "repository.gitlab"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "GitLab"

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the GitLab REST API."""
        if self._use_bearer:
            return {
                "Authorization": f"Bearer {self._api_token}",
                "Content-Type": "application/json",
            }
        return {
            "PRIVATE-TOKEN": self._api_token,
            "Content-Type": "application/json",
        }

    def _api_url(self, path: str) -> str:
        """Build a full GitLab API v4 URL."""
        return f"{self._base_url}/api/v4/{path}"

    def _encode_project_id(self, repo_id: str) -> str:
        """URL-encode a project namespace path; numeric IDs are returned as-is."""
        if repo_id.isdigit():
            return repo_id
        return urllib.parse.quote(repo_id, safe="")

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        """Perform an authenticated GET and return the parsed JSON body.

        Args:
            path: API path relative to the GitLab API v4 base.
            params: Optional query parameters.

        Returns:
            Parsed JSON body as dict or list.

        Raises:
            RepositoryProviderError: On HTTP errors, including 404.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    self._api_url(path),
                    headers=self._auth_headers(),
                    params=params or {},
                )
                if response.status_code == 404:
                    raise RepositoryProviderError(
                        f"GitLab resource not found: {path}"
                    )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise RepositoryProviderError(f"GitLab HTTP error: {exc}") from exc

    async def _search_repo(
        self,
        query: str,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Search GitLab projects by name or keyword.

        Args:
            query: Search string matched against project name and description.
            limit: Maximum number of results (capped at 100 per GitLab pagination).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            RepositoryProviderError: On HTTP or API errors.
        """
        data = await self._get(
            "projects",
            params={"search": query, "per_page": min(limit, 100)},
        )
        items = _parse_gitlab_project_list(data)  # type: ignore[arg-type]

        artifact = self._make_repo_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            query=query,
            items=items,
            total=len(items),
            provenance={"provider": "gitlab", "query": query},
        )
        logger.info("GitLab search_repo: query=%r count=%d", query, len(items))
        return artifact.model_dump(mode="json"), None

    async def _get_file(
        self,
        repo_id: str,
        path: str,
        ref: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Fetch a file's contents from a GitLab project.

        Args:
            repo_id: Numeric project ID or namespace/project path.
            path: File path within the repository.
            ref: Branch, tag, or commit SHA (default: project's default branch).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            RepositoryProviderError: When the file or project is not found.
        """
        pid = self._encode_project_id(repo_id)
        encoded_path = urllib.parse.quote(path, safe="")
        params: dict = {}
        if ref:
            params["ref"] = ref

        data = await self._get(
            f"projects/{pid}/repository/files/{encoded_path}",
            params=params,
        )

        content, encoding = _decode_gitlab_content(data)  # type: ignore[arg-type]
        url = _gitlab_file_url(self._base_url, repo_id, path, ref)

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="gitlab_file",
                external_id=data.get("blob_id", ""),  # type: ignore[union-attr]
                url=url,
                metadata={"project": repo_id, "path": path},
            )
        ]

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            repo_id=repo_id,
            path=path,
            ref=ref,
            content=content,
            encoding=encoding,
            size=data.get("size"),  # type: ignore[union-attr]
            url=url,
            raw_payload=data,  # type: ignore[arg-type]
            provenance={"provider": "gitlab", "project": repo_id},
            references=refs,
        )
        logger.info("GitLab get_file: project=%r path=%r ref=%r", repo_id, path, ref)
        return artifact.model_dump(mode="json"), None

    async def _list_commits(
        self,
        repo_id: str,
        ref: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List recent commits in a GitLab project.

        Args:
            repo_id: Numeric project ID or namespace/project path.
            ref: Branch, tag, or SHA to list commits from (default: HEAD).
            limit: Maximum number of commits to return.

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            RepositoryProviderError: On HTTP or API errors.
        """
        pid = self._encode_project_id(repo_id)
        params: dict = {"per_page": min(limit, 100)}
        if ref:
            params["ref_name"] = ref

        data = await self._get(
            f"projects/{pid}/repository/commits",
            params=params,
        )
        commits = _parse_gitlab_commits(data)  # type: ignore[arg-type]

        artifact = self._make_commit_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            repo_id=repo_id,
            ref=ref,
            commits=commits,
            total=len(commits),
            provenance={"provider": "gitlab", "project": repo_id, "ref": ref},
        )
        logger.info(
            "GitLab list_commits: project=%r ref=%r count=%d",
            repo_id, ref, len(commits),
        )
        return artifact.model_dump(mode="json"), None

    async def _get_pull_request(
        self,
        repo_id: str,
        pr_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve a GitLab merge request.

        Args:
            repo_id: Numeric project ID or namespace/project path.
            pr_id: Merge request IID (internal ID within the project).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            RepositoryProviderError: When the MR is not found, or on errors.
        """
        pid = self._encode_project_id(repo_id)
        data = await self._get(f"projects/{pid}/merge_requests/{pr_id}")

        url: str | None = data.get("web_url")  # type: ignore[union-attr]
        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="gitlab_merge_request",
                external_id=str(data.get("iid", pr_id)),  # type: ignore[union-attr]
                url=url,
                metadata={"project": repo_id},
            )
        ]

        author_obj = data.get("author")  # type: ignore[union-attr]
        artifact = self._make_pr_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            repo_id=repo_id,
            pr_id=str(data.get("iid", pr_id)),  # type: ignore[union-attr]
            title=data.get("title", ""),  # type: ignore[union-attr]
            description=data.get("description"),  # type: ignore[union-attr]
            state=data.get("state"),  # type: ignore[union-attr]
            author=author_obj.get("name") if isinstance(author_obj, dict) else None,
            source_branch=data.get("source_branch"),  # type: ignore[union-attr]
            target_branch=data.get("target_branch"),  # type: ignore[union-attr]
            url=url,
            raw_payload=data,  # type: ignore[arg-type]
            provenance={"provider": "gitlab", "project": repo_id},
            references=refs,
        )
        logger.info("GitLab get_pull_request: project=%r pr=%r", repo_id, pr_id)
        return artifact.model_dump(mode="json"), None


# ---------------------------------------------------------------------------
# Module-level helpers — keep provider methods short
# ---------------------------------------------------------------------------


def _decode_gitlab_content(data: dict) -> tuple[str | None, str]:
    """Decode a GitLab file response.

    GitLab returns base64-encoded content. We attempt UTF-8 decoding; if
    that fails the raw base64 string is returned with encoding label "base64".

    Returns:
        (decoded_content_or_none, encoding_label)
    """
    raw: str = data.get("content", "")
    enc: str = data.get("encoding", "")
    if enc != "base64" or not raw:
        return raw or None, enc or "unknown"
    try:
        decoded_bytes = base64.b64decode(raw.replace("\n", ""))
        return decoded_bytes.decode("utf-8"), "utf-8"
    except (ValueError, UnicodeDecodeError):
        return raw, "base64"


def _gitlab_file_url(base_url: str, repo_id: str, path: str, ref: str | None) -> str:
    """Build a browser URL for a GitLab file."""
    ref_part = f"/-/blob/{ref}/{path}" if ref else f"/-/blob/HEAD/{path}"
    return f"{base_url}/{repo_id}{ref_part}"


def _parse_gitlab_project_list(data: list) -> list[dict]:
    """Normalise a GitLab /projects response to a list of repo summary dicts."""
    items: list[dict] = []
    for project in data:
        items.append({
            "repo_id": str(project.get("id", "")),
            "name": project.get("path_with_namespace", project.get("name", "")),
            "description": project.get("description"),
            "url": project.get("web_url"),
            "default_branch": project.get("default_branch"),
        })
    return items


def _parse_gitlab_commits(data: list) -> list[dict]:
    """Normalise a GitLab /repository/commits response to a list of commit dicts."""
    commits: list[dict] = []
    for entry in data:
        commits.append({
            "sha": entry.get("id", ""),
            "message": entry.get("title", entry.get("message", "")),
            "author": entry.get("author_name"),
            "authored_at": entry.get("authored_date"),
            "url": entry.get("web_url"),
        })
    return commits
