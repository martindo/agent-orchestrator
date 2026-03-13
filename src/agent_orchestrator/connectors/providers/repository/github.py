"""GitHub repository connector provider.

Implements search_repo, get_file, list_commits, and get_pull_request against
the GitHub REST API v3 using a personal access token (PAT) or fine-grained
token with at least Contents (read) and Pull Requests (read) permissions.
"""
from __future__ import annotations

import base64
import logging

import httpx

from ...models import ConnectorCostInfo, ExternalReference
from ._base import BaseRepositoryProvider, RepositoryProviderError

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"


class GitHubRepositoryProvider(BaseRepositoryProvider):
    """GitHub-backed repository connector provider.

    Uses the GitHub REST API v3. The api_token must have at minimum:
    - ``repo`` (or ``public_repo``) scope for classic tokens
    - Contents (read) + Pull Requests (read) for fine-grained tokens.

    The ``repo_id`` parameter across all operations is the repository's
    ``{owner}/{repo}`` full name (e.g. ``"octocat/hello-world"``).

    Example::

        provider = GitHubRepositoryProvider(api_token="ghp_...")
    """

    def __init__(self, api_token: str) -> None:
        if not api_token:
            raise ValueError("GitHubRepositoryProvider requires a non-empty api_token")
        self._api_token = api_token

    @classmethod
    def from_env(cls) -> "GitHubRepositoryProvider | None":
        """Create an instance from environment variables.

        Required env var: ``GITHUB_API_TOKEN``

        Returns None if ``GITHUB_API_TOKEN`` is not set.
        """
        import os
        token = os.environ.get("GITHUB_API_TOKEN", "")
        if not token:
            return None
        return cls(api_token=token)

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "repository.github"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "GitHub"

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers for the GitHub REST API."""
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _api_url(self, path: str) -> str:
        """Build a full GitHub API URL."""
        return f"{_GITHUB_API_BASE}/{path}"

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        """Perform an authenticated GET and return the parsed JSON body.

        Args:
            path: API path relative to the GitHub API base.
            params: Optional query parameters.

        Returns:
            Parsed JSON body as dict or list.

        Raises:
            RepositoryProviderError: On HTTP errors.
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
                        f"GitHub resource not found: {path}"
                    )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise RepositoryProviderError(f"GitHub HTTP error: {exc}") from exc

    async def _search_repo(
        self,
        query: str,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Search GitHub repositories using the Search API.

        Args:
            query: GitHub search query (supports qualifiers like ``language:python``).
            limit: Maximum number of results (capped at 100 by GitHub).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            RepositoryProviderError: On HTTP or API errors.
        """
        data = await self._get(
            "search/repositories",
            params={"q": query, "per_page": min(limit, 100)},
        )
        items = _parse_github_repo_list(data)
        total: int = data.get("total_count", len(items))  # type: ignore[union-attr]

        artifact = self._make_repo_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            query=query,
            items=items,
            total=total,
            provenance={"provider": "github", "query": query},
        )
        logger.info("GitHub search_repo: query=%r total=%d", query, total)
        return artifact.model_dump(mode="json"), None

    async def _get_file(
        self,
        repo_id: str,
        path: str,
        ref: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Fetch a file's contents from a GitHub repository.

        Args:
            repo_id: Repository full name, e.g. ``"owner/repo"``.
            path: File path within the repository.
            ref: Branch, tag, or commit SHA (default: repo's default branch).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            RepositoryProviderError: When the file or repo is not found, or on errors.
        """
        params: dict = {}
        if ref:
            params["ref"] = ref

        data = await self._get(f"repos/{repo_id}/contents/{path}", params=params)
        if isinstance(data, list):
            raise RepositoryProviderError(
                f"Path {path!r} is a directory, not a file"
            )

        content, encoding = _decode_github_content(data)
        url: str | None = data.get("html_url")

        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="github_file",
                external_id=data.get("sha", ""),
                url=url,
                metadata={"repo": repo_id, "path": path},
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
            size=data.get("size"),
            url=url,
            raw_payload=data,  # type: ignore[arg-type]
            provenance={"provider": "github", "repo": repo_id},
            references=refs,
        )
        logger.info("GitHub get_file: repo=%r path=%r ref=%r", repo_id, path, ref)
        return artifact.model_dump(mode="json"), None

    async def _list_commits(
        self,
        repo_id: str,
        ref: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List recent commits in a GitHub repository.

        Args:
            repo_id: Repository full name, e.g. ``"owner/repo"``.
            ref: Branch, tag, or SHA to list commits from (default: HEAD).
            limit: Maximum number of commits to return.

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            RepositoryProviderError: On HTTP or API errors.
        """
        params: dict = {"per_page": min(limit, 100)}
        if ref:
            params["sha"] = ref

        data = await self._get(f"repos/{repo_id}/commits", params=params)
        commits = _parse_github_commits(data)  # type: ignore[arg-type]

        artifact = self._make_commit_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            repo_id=repo_id,
            ref=ref,
            commits=commits,
            total=len(commits),
            provenance={"provider": "github", "repo": repo_id, "ref": ref},
        )
        logger.info(
            "GitHub list_commits: repo=%r ref=%r count=%d", repo_id, ref, len(commits)
        )
        return artifact.model_dump(mode="json"), None

    async def _get_pull_request(
        self,
        repo_id: str,
        pr_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Retrieve a GitHub pull request.

        Args:
            repo_id: Repository full name, e.g. ``"owner/repo"``.
            pr_id: Pull request number (as a string).

        Returns:
            Tuple of (ExternalArtifact dict, None — no tracked API cost).

        Raises:
            RepositoryProviderError: When the PR is not found, or on errors.
        """
        data = await self._get(f"repos/{repo_id}/pulls/{pr_id}")

        url: str | None = data.get("html_url")  # type: ignore[union-attr]
        refs: list[ExternalReference] = [
            ExternalReference(
                provider=self.provider_id,
                resource_type="github_pull_request",
                external_id=str(data.get("number", pr_id)),  # type: ignore[union-attr]
                url=url,
                metadata={"repo": repo_id},
            )
        ]

        artifact = self._make_pr_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            repo_id=repo_id,
            pr_id=str(data.get("number", pr_id)),  # type: ignore[union-attr]
            title=data.get("title", ""),  # type: ignore[union-attr]
            description=data.get("body"),  # type: ignore[union-attr]
            state=data.get("state"),  # type: ignore[union-attr]
            author=_nested_login(data.get("user")),  # type: ignore[union-attr]
            source_branch=_nested_ref(data.get("head")),  # type: ignore[union-attr]
            target_branch=_nested_ref(data.get("base")),  # type: ignore[union-attr]
            url=url,
            raw_payload=data,  # type: ignore[arg-type]
            provenance={"provider": "github", "repo": repo_id},
            references=refs,
        )
        logger.info("GitHub get_pull_request: repo=%r pr=%r", repo_id, pr_id)
        return artifact.model_dump(mode="json"), None


# ---------------------------------------------------------------------------
# Module-level helpers — keep provider methods short
# ---------------------------------------------------------------------------


def _decode_github_content(data: dict) -> tuple[str | None, str]:
    """Decode a GitHub file contents response.

    GitHub returns base64-encoded content with embedded newlines. We attempt
    UTF-8 decoding; if that fails the raw base64 string is returned with
    encoding label "base64".

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


def _parse_github_repo_list(data: dict) -> list[dict]:
    """Normalise a GitHub /search/repositories response to a list of repo dicts."""
    items: list[dict] = []
    for repo in data.get("items", []):
        items.append({
            "repo_id": repo.get("full_name", ""),
            "name": repo.get("full_name", ""),
            "description": repo.get("description"),
            "url": repo.get("html_url"),
            "default_branch": repo.get("default_branch"),
        })
    return items


def _parse_github_commits(data: list) -> list[dict]:
    """Normalise a GitHub /repos/{repo}/commits response to a list of commit dicts."""
    commits: list[dict] = []
    for entry in data:
        commit_obj = entry.get("commit", {})
        author_obj = commit_obj.get("author", {})
        commits.append({
            "sha": entry.get("sha", ""),
            "message": commit_obj.get("message", ""),
            "author": author_obj.get("name"),
            "authored_at": author_obj.get("date"),
            "url": entry.get("html_url"),
        })
    return commits


def _nested_login(value: object) -> str | None:
    """Return value["login"] when value is a dict, otherwise None."""
    if isinstance(value, dict):
        return value.get("login")
    return None


def _nested_ref(value: object) -> str | None:
    """Return value["ref"] when value is a dict, otherwise None."""
    if isinstance(value, dict):
        return value.get("ref")
    return None
