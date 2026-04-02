"""Shared base for repository capability connector providers."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from ...models import (
    CapabilityType,
    ConnectorCostInfo,
    ConnectorInvocationRequest,
    ConnectorInvocationResult,
    ConnectorOperationDescriptor,
    ConnectorProviderDescriptor,
    ConnectorStatus,
    ExternalArtifact,
    ExternalReference,
)
from ...normalized import RepositoryArtifact

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 25

_REPOSITORY_OPS: list[ConnectorOperationDescriptor] = [
    ConnectorOperationDescriptor(
        operation="search_repo",
        description="Search for repositories matching a query string",
        capability_type=CapabilityType.REPOSITORY,
        read_only=True,
        required_parameters=["query"],
        optional_parameters=["limit"],
    ),
    ConnectorOperationDescriptor(
        operation="get_file",
        description="Retrieve the contents of a file at a given path and ref",
        capability_type=CapabilityType.REPOSITORY,
        read_only=True,
        required_parameters=["repo_id", "path"],
        optional_parameters=["ref"],
    ),
    ConnectorOperationDescriptor(
        operation="list_commits",
        description="List recent commits in a repository, optionally filtered by ref",
        capability_type=CapabilityType.REPOSITORY,
        read_only=True,
        required_parameters=["repo_id"],
        optional_parameters=["ref", "limit"],
    ),
    ConnectorOperationDescriptor(
        operation="get_pull_request",
        description="Retrieve a pull request or merge request by repository and PR ID",
        capability_type=CapabilityType.REPOSITORY,
        read_only=True,
        required_parameters=["repo_id", "pr_id"],
        optional_parameters=[],
    ),
    ConnectorOperationDescriptor(
        operation="create_issue",
        description="Create a new issue in a repository",
        capability_type=CapabilityType.REPOSITORY,
        read_only=False,
        required_parameters=["repo_id", "title"],
        optional_parameters=["body", "labels"],
    ),
    ConnectorOperationDescriptor(
        operation="list_issues",
        description="List issues in a repository filtered by state",
        capability_type=CapabilityType.REPOSITORY,
        read_only=True,
        required_parameters=["repo_id"],
        optional_parameters=["state", "limit"],
    ),
    ConnectorOperationDescriptor(
        operation="create_pull_request",
        description="Create a new pull request in a repository",
        capability_type=CapabilityType.REPOSITORY,
        read_only=False,
        required_parameters=["repo_id", "title", "head"],
        optional_parameters=["base", "body"],
    ),
    ConnectorOperationDescriptor(
        operation="add_review_comment",
        description="Add a review comment to a pull request",
        capability_type=CapabilityType.REPOSITORY,
        read_only=False,
        required_parameters=["repo_id", "pr_id", "body"],
        optional_parameters=[],
    ),
]


class RepositoryProviderError(Exception):
    """Raised when a repository provider encounters an unrecoverable error."""


class BaseRepositoryProvider(ABC):
    """Abstract base with common execute() dispatch for repository providers.

    Subclasses implement _search_repo(), _get_file(), _list_commits(), and
    _get_pull_request(). Each must return a tuple of
    (dict, ConnectorCostInfo | None) where the dict is an ExternalArtifact
    model_dump().

    All operations are read_only=True; they do not mutate remote state.
    """

    def get_descriptor(self) -> ConnectorProviderDescriptor:
        """Return the provider descriptor for registry discovery."""
        return ConnectorProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            capability_types=[CapabilityType.REPOSITORY],
            operations=_REPOSITORY_OPS,
            enabled=self.is_available(),
            auth_required=True,
            auth_type="api_key",
            version="1.0",
        )

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    def is_available(self) -> bool:
        """Return True if the provider has credentials configured."""
        return bool(getattr(self, "_api_token", None))

    async def execute(
        self, request: ConnectorInvocationRequest
    ) -> ConnectorInvocationResult:
        """Dispatch the request to the appropriate handler and return a result.

        Args:
            request: Connector invocation request with operation and parameters.

        Returns:
            ConnectorInvocationResult with status, payload as ExternalArtifact
            dict, and optional cost info.
        """
        start = time.monotonic()
        op = request.operation
        params = request.parameters

        try:
            payload, cost_info = await self._dispatch(op, params)
        except RepositoryProviderError as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self.provider_id,
                provider=self.provider_id,
                capability_type=request.capability_type,
                operation=op,
                status=ConnectorStatus.FAILURE,
                error_message=str(exc),
                duration_ms=duration_ms,
            )

        if payload is None:
            return ConnectorInvocationResult(
                request_id=request.request_id,
                connector_id=self.provider_id,
                provider=self.provider_id,
                capability_type=request.capability_type,
                operation=op,
                status=ConnectorStatus.NOT_FOUND,
                error_message=f"Unknown operation: {op!r}",
            )

        duration_ms = (time.monotonic() - start) * 1000
        return ConnectorInvocationResult(
            request_id=request.request_id,
            connector_id=self.provider_id,
            provider=self.provider_id,
            capability_type=request.capability_type,
            operation=op,
            status=ConnectorStatus.SUCCESS,
            payload=payload,
            cost_info=cost_info,
            duration_ms=duration_ms,
        )

    async def _dispatch(
        self, op: str, params: dict
    ) -> tuple[dict, ConnectorCostInfo | None] | tuple[None, None]:
        """Route an operation name to the corresponding handler method."""
        if op == "search_repo":
            return await self._search_repo(
                query=params["query"],
                limit=int(params.get("limit", _DEFAULT_LIMIT)),
            )
        if op == "get_file":
            return await self._get_file(
                repo_id=params["repo_id"],
                path=params["path"],
                ref=params.get("ref"),
            )
        if op == "list_commits":
            return await self._list_commits(
                repo_id=params["repo_id"],
                ref=params.get("ref"),
                limit=int(params.get("limit", _DEFAULT_LIMIT)),
            )
        if op == "get_pull_request":
            return await self._get_pull_request(
                repo_id=params["repo_id"],
                pr_id=params["pr_id"],
            )
        if op == "create_issue":
            return await self._create_issue(
                repo_id=params["repo_id"],
                title=params["title"],
                body=params.get("body", ""),
                labels=params.get("labels"),
            )
        if op == "list_issues":
            return await self._list_issues(
                repo_id=params["repo_id"],
                state=params.get("state", "open"),
                limit=int(params.get("limit", _DEFAULT_LIMIT)),
            )
        if op == "create_pull_request":
            return await self._create_pull_request(
                repo_id=params["repo_id"],
                title=params["title"],
                head=params["head"],
                base=params.get("base", "main"),
                body=params.get("body", ""),
            )
        if op == "add_review_comment":
            return await self._add_review_comment(
                repo_id=params["repo_id"],
                pr_id=params["pr_id"],
                body=params["body"],
            )
        return None, None

    @abstractmethod
    async def _search_repo(
        self,
        query: str,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _get_file(
        self,
        repo_id: str,
        path: str,
        ref: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _list_commits(
        self,
        repo_id: str,
        ref: str | None,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    @abstractmethod
    async def _get_pull_request(
        self,
        repo_id: str,
        pr_id: str,
    ) -> tuple[dict, ConnectorCostInfo | None]: ...

    async def _create_issue(
        self,
        repo_id: str,
        title: str,
        body: str,
        labels: list[str] | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Create a new issue in a repository. Optional — subclasses may override."""
        raise RepositoryProviderError(
            f"{self.provider_id} does not support create_issue"
        )

    async def _list_issues(
        self,
        repo_id: str,
        state: str,
        limit: int,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List issues in a repository. Optional — subclasses may override."""
        raise RepositoryProviderError(
            f"{self.provider_id} does not support list_issues"
        )

    async def _create_pull_request(
        self,
        repo_id: str,
        title: str,
        head: str,
        base: str,
        body: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Create a pull request. Optional — subclasses may override."""
        raise RepositoryProviderError(
            f"{self.provider_id} does not support create_pull_request"
        )

    async def _add_review_comment(
        self,
        repo_id: str,
        pr_id: str,
        body: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Add a review comment to a PR. Optional — subclasses may override."""
        raise RepositoryProviderError(
            f"{self.provider_id} does not support add_review_comment"
        )

    # ------------------------------------------------------------------
    # Static artifact factory helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_repo_artifact(
        provider: str,
        connector_id: str,
        repo_id: str | None,
        name: str,
        description: str | None,
        url: str | None,
        default_branch: str | None,
        raw_payload: dict,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap a single repository in a platform-standard ExternalArtifact.

        The normalized_payload contains a RepositoryArtifact-shaped dict.

        Args:
            provider: Provider ID.
            connector_id: Connector ID (typically same as provider).
            repo_id: Provider-specific repository ID or full name.
            name: Repository name.
            description: Repository description, or None.
            url: Web URL of the repository, or None.
            default_branch: Default branch name, or None.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict (provider, query, etc.).
            references: Optional list of ExternalReference.

        Returns:
            ExternalArtifact with resource_type "repository".
        """
        normalized = RepositoryArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            repo_id=repo_id,
            name=name,
            description=description,
            url=url,
            default_branch=default_branch,
        )
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            resource_type="repository",
            raw_payload=raw_payload,
            normalized_payload=normalized.model_dump(mode="json"),
            references=references or [],
            provenance=provenance,
        )

    @staticmethod
    def _make_repo_list_artifact(
        provider: str,
        connector_id: str,
        query: str,
        items: list[dict],
        total: int,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap a list of repository search results in an ExternalArtifact.

        The raw_payload contains the full result set. normalized_payload is
        omitted because RepositoryArtifact represents a single repository.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            query: Original search query string.
            items: List of repo summary dicts with keys repo_id, name,
                description, url, default_branch.
            total: Total result count reported by the provider.
            provenance: Provenance dict.

        Returns:
            ExternalArtifact with resource_type "repository".
        """
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            resource_type="repository",
            raw_payload={"query": query, "total": total, "items": items},
            normalized_payload=None,
            references=[],
            provenance=provenance,
        )

    @staticmethod
    def _make_file_artifact(
        provider: str,
        connector_id: str,
        repo_id: str,
        path: str,
        ref: str | None,
        content: str | None,
        encoding: str,
        size: int | None,
        url: str | None,
        raw_payload: dict,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap a repository file in a platform-standard ExternalArtifact.

        The normalized_payload is a structured dict with well-known keys:
        repo_id, path, ref, content, encoding, size, url.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            repo_id: Repository identifier.
            path: File path within the repository.
            ref: Git ref (branch, tag, or SHA) the file was fetched at.
            content: Decoded file content string, or None if binary.
            encoding: Content encoding label (e.g. "utf-8" or "base64").
            size: File size in bytes, or None.
            url: Web URL for the file, or None.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict.
            references: Optional list of ExternalReference.

        Returns:
            ExternalArtifact with resource_type "repo_file".
        """
        normalized: dict = {
            "repo_id": repo_id,
            "path": path,
            "ref": ref,
            "content": content,
            "encoding": encoding,
            "size": size,
            "url": url,
        }
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            resource_type="repo_file",
            raw_payload=raw_payload,
            normalized_payload=normalized,
            references=references or [],
            provenance=provenance,
        )

    @staticmethod
    def _make_commit_list_artifact(
        provider: str,
        connector_id: str,
        repo_id: str,
        ref: str | None,
        commits: list[dict],
        total: int,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap a list of commits in a platform-standard ExternalArtifact.

        Each commit dict should have at minimum: sha, message, author,
        authored_at, url.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            repo_id: Repository identifier.
            ref: Git ref the commits were listed from, or None.
            commits: List of commit summary dicts.
            total: Number of commits returned (may differ from total on remote).
            provenance: Provenance dict.

        Returns:
            ExternalArtifact with resource_type "commit_list".
        """
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            resource_type="commit_list",
            raw_payload={
                "repo_id": repo_id,
                "ref": ref,
                "total": total,
                "commits": commits,
            },
            normalized_payload=None,
            references=[],
            provenance=provenance,
        )

    @staticmethod
    def _make_pr_artifact(
        provider: str,
        connector_id: str,
        repo_id: str,
        pr_id: str,
        title: str,
        description: str | None,
        state: str | None,
        author: str | None,
        source_branch: str | None,
        target_branch: str | None,
        url: str | None,
        raw_payload: dict,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap a pull request in a platform-standard ExternalArtifact.

        The normalized_payload is a structured dict with well-known keys
        common across all providers: repo_id, pr_id, title, description,
        state, author, source_branch, target_branch, url.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            repo_id: Repository identifier.
            pr_id: Pull/merge request ID (string for cross-provider consistency).
            title: PR title.
            description: PR body or description, or None.
            state: PR state (e.g. "open", "closed", "merged"), or None.
            author: Author username or display name, or None.
            source_branch: Head/source branch name, or None.
            target_branch: Base/target branch name, or None.
            url: Web URL of the PR, or None.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict.
            references: Optional list of ExternalReference.

        Returns:
            ExternalArtifact with resource_type "pull_request".
        """
        normalized: dict = {
            "repo_id": repo_id,
            "pr_id": pr_id,
            "title": title,
            "description": description,
            "state": state,
            "author": author,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "url": url,
        }
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            resource_type="pull_request",
            raw_payload=raw_payload,
            normalized_payload=normalized,
            references=references or [],
            provenance=provenance,
        )

    @staticmethod
    def _make_issue_artifact(
        provider: str,
        connector_id: str,
        issue_id: str,
        title: str,
        body: str | None,
        state: str | None,
        url: str | None,
        raw_payload: dict,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap an issue in a platform-standard ExternalArtifact.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            issue_id: Issue number or ID (string).
            title: Issue title.
            body: Issue body text, or None.
            state: Issue state (e.g. "open", "closed"), or None.
            url: Web URL of the issue, or None.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict.
            references: Optional list of ExternalReference.

        Returns:
            ExternalArtifact with resource_type "issue".
        """
        normalized: dict = {
            "issue_id": issue_id,
            "title": title,
            "body": body,
            "state": state,
            "url": url,
        }
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            resource_type="issue",
            raw_payload=raw_payload,
            normalized_payload=normalized,
            references=references or [],
            provenance=provenance,
        )

    @staticmethod
    def _make_issue_list_artifact(
        provider: str,
        connector_id: str,
        repo_id: str,
        state: str,
        items: list[dict],
        total: int,
        provenance: dict,
    ) -> ExternalArtifact:
        """Wrap a list of issues in a platform-standard ExternalArtifact.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            repo_id: Repository identifier.
            state: Issue state filter used.
            items: List of issue summary dicts.
            total: Number of issues returned.
            provenance: Provenance dict.

        Returns:
            ExternalArtifact with resource_type "issue_list".
        """
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            resource_type="issue_list",
            raw_payload={
                "repo_id": repo_id,
                "state": state,
                "total": total,
                "items": items,
            },
            normalized_payload=None,
            references=[],
            provenance=provenance,
        )

    @staticmethod
    def _make_review_comment_artifact(
        provider: str,
        connector_id: str,
        comment_id: str,
        pr_id: str,
        body: str,
        url: str | None,
        raw_payload: dict,
        provenance: dict,
        references: list[ExternalReference] | None = None,
    ) -> ExternalArtifact:
        """Wrap a review comment in a platform-standard ExternalArtifact.

        Args:
            provider: Provider ID.
            connector_id: Connector ID.
            comment_id: Comment ID (string).
            pr_id: Pull request number (string).
            body: Comment body text.
            url: Web URL of the comment, or None.
            raw_payload: Raw provider API response dict.
            provenance: Provenance dict.
            references: Optional list of ExternalReference.

        Returns:
            ExternalArtifact with resource_type "review_comment".
        """
        normalized: dict = {
            "comment_id": comment_id,
            "pr_id": pr_id,
            "body": body,
            "url": url,
        }
        return ExternalArtifact(
            source_connector=connector_id,
            provider=provider,
            capability_type=CapabilityType.REPOSITORY,
            resource_type="review_comment",
            raw_payload=raw_payload,
            normalized_payload=normalized,
            references=references or [],
            provenance=provenance,
        )
