"""Tests for repository capability connector providers."""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_orchestrator.connectors.models import (
    CapabilityType,
    ConnectorInvocationRequest,
    ConnectorStatus,
    ExternalArtifact,
)
from agent_orchestrator.connectors.providers.repository import (
    GitHubRepositoryProvider,
    GitLabRepositoryProvider,
)
from agent_orchestrator.connectors.providers.repository._base import (
    BaseRepositoryProvider,
    RepositoryProviderError,
    _REPOSITORY_OPS,
)
from agent_orchestrator.connectors.registry import ConnectorProviderProtocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_http_client(json_response: object = None):
    """Return an (AsyncMock client, fake response) pair with canned JSON."""
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    if json_response is not None:
        fake_response.json.return_value = json_response
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, fake_response


def _b64(text: str) -> str:
    """Return a base64-encoded string (no newlines)."""
    return base64.b64encode(text.encode()).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def github() -> GitHubRepositoryProvider:
    return GitHubRepositoryProvider(api_token="ghp_testtoken")


@pytest.fixture
def gitlab() -> GitLabRepositoryProvider:
    return GitLabRepositoryProvider(api_token="glpat-test")


@pytest.fixture
def gitlab_bearer() -> GitLabRepositoryProvider:
    return GitLabRepositoryProvider(api_token="oauth-token", use_bearer=True)


@pytest.fixture
def gitlab_self_hosted() -> GitLabRepositoryProvider:
    return GitLabRepositoryProvider(
        api_token="glpat-test",
        base_url="https://gitlab.example.com",
    )


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructorValidation:
    def test_github_empty_token_raises(self) -> None:
        with pytest.raises(ValueError, match="api_token"):
            GitHubRepositoryProvider(api_token="")

    def test_gitlab_empty_token_raises(self) -> None:
        with pytest.raises(ValueError, match="api_token"):
            GitLabRepositoryProvider(api_token="")

    def test_gitlab_strips_trailing_slash(self) -> None:
        p = GitLabRepositoryProvider(
            api_token="tok", base_url="https://gitlab.example.com/"
        )
        assert not p._base_url.endswith("/")

    def test_gitlab_default_base_url(self, gitlab: GitLabRepositoryProvider) -> None:
        assert "gitlab.com" in gitlab._base_url


# ---------------------------------------------------------------------------
# Descriptor shape
# ---------------------------------------------------------------------------


class TestDescriptorShape:
    def test_github_descriptor(self, github: GitHubRepositoryProvider) -> None:
        desc = github.get_descriptor()
        assert CapabilityType.REPOSITORY in desc.capability_types
        ops = {op.operation for op in desc.operations}
        assert ops == {"search_repo", "get_file", "list_commits", "get_pull_request"}
        assert desc.provider_id == "repository.github"
        assert desc.auth_required is True

    def test_gitlab_descriptor(self, gitlab: GitLabRepositoryProvider) -> None:
        desc = gitlab.get_descriptor()
        assert CapabilityType.REPOSITORY in desc.capability_types
        ops = {op.operation for op in desc.operations}
        assert ops == {"search_repo", "get_file", "list_commits", "get_pull_request"}
        assert desc.provider_id == "repository.gitlab"

    def test_all_ops_are_read_only(self) -> None:
        for op in _REPOSITORY_OPS:
            assert op.read_only is True, f"{op.operation} should be read_only=True"


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------


class TestProtocolCheck:
    def test_github_satisfies_protocol(self, github: GitHubRepositoryProvider) -> None:
        assert isinstance(github, ConnectorProviderProtocol)

    def test_gitlab_satisfies_protocol(self, gitlab: GitLabRepositoryProvider) -> None:
        assert isinstance(gitlab, ConnectorProviderProtocol)


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_github_available_with_token(self, github: GitHubRepositoryProvider) -> None:
        assert github.is_available() is True

    def test_gitlab_available_with_token(self, gitlab: GitLabRepositoryProvider) -> None:
        assert gitlab.is_available() is True

    def test_github_unavailable_when_cleared(
        self, github: GitHubRepositoryProvider
    ) -> None:
        github._api_token = ""
        assert github.is_available() is False


# ---------------------------------------------------------------------------
# GitHub: search_repo
# ---------------------------------------------------------------------------


class TestGitHubSearchRepo:
    async def test_search_repo_success(self, github: GitHubRepositoryProvider) -> None:
        response_data = {
            "total_count": 2,
            "items": [
                {
                    "full_name": "octocat/hello-world",
                    "description": "My first repo",
                    "html_url": "https://github.com/octocat/hello-world",
                    "default_branch": "main",
                },
                {
                    "full_name": "octocat/Spoon-Knife",
                    "description": "Fork me!",
                    "html_url": "https://github.com/octocat/Spoon-Knife",
                    "default_branch": "main",
                },
            ],
        }
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="search_repo",
                    parameters={"query": "hello-world"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["capability_type"] == "repository"
        assert result.payload["resource_type"] == "repository"
        assert result.payload["provider"] == "repository.github"
        raw = result.payload["raw_payload"]
        assert raw["total"] == 2
        assert len(raw["items"]) == 2
        assert raw["items"][0]["repo_id"] == "octocat/hello-world"

    async def test_search_repo_passes_query_and_limit(
        self, github: GitHubRepositoryProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client({"total_count": 0, "items": []})
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="search_repo",
                    parameters={"query": "python cli", "limit": "10"},
                )
            )

        call_params = mock_client.get.call_args.kwargs.get("params", {})
        assert call_params["q"] == "python cli"
        assert call_params["per_page"] == 10

    async def test_search_repo_http_error(self, github: GitHubRepositoryProvider) -> None:
        mock_client, fake_response = _mock_http_client()
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "503", request=MagicMock(), response=MagicMock()
            )
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="search_repo",
                    parameters={"query": "fail"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE


# ---------------------------------------------------------------------------
# GitHub: get_file
# ---------------------------------------------------------------------------


class TestGitHubGetFile:
    async def test_get_file_success(self, github: GitHubRepositoryProvider) -> None:
        encoded_content = _b64("print('hello world')\n")
        response_data = {
            "name": "main.py",
            "path": "src/main.py",
            "sha": "abc123",
            "size": 22,
            "content": encoded_content,
            "encoding": "base64",
            "html_url": "https://github.com/octocat/repo/blob/main/src/main.py",
        }
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_file",
                    parameters={
                        "repo_id": "octocat/repo",
                        "path": "src/main.py",
                        "ref": "main",
                    },
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "repo_file"
        normalized = result.payload["normalized_payload"]
        assert normalized["repo_id"] == "octocat/repo"
        assert normalized["path"] == "src/main.py"
        assert normalized["ref"] == "main"
        assert "hello world" in normalized["content"]
        assert normalized["encoding"] == "utf-8"
        assert normalized["size"] == 22
        assert len(result.payload["references"]) == 1

    async def test_get_file_directory_path_fails(
        self, github: GitHubRepositoryProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client([{"name": "a"}, {"name": "b"}])
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_file",
                    parameters={"repo_id": "octocat/repo", "path": "src/"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE
        assert "directory" in result.error_message

    async def test_get_file_not_found(self, github: GitHubRepositoryProvider) -> None:
        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404
        mock_client, fake_response = _mock_http_client()
        fake_response.status_code = 404
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=mock_response_404
            )
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_file",
                    parameters={"repo_id": "octocat/repo", "path": "missing.py"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE

    async def test_get_file_binary_stays_base64(
        self, github: GitHubRepositoryProvider
    ) -> None:
        binary_content = base64.b64encode(b"\x89PNG\r\n").decode()
        response_data = {
            "path": "logo.png",
            "sha": "def456",
            "size": 6,
            "content": binary_content,
            "encoding": "base64",
            "html_url": "https://github.com/octocat/repo/blob/main/logo.png",
        }
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_file",
                    parameters={"repo_id": "octocat/repo", "path": "logo.png"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["normalized_payload"]["encoding"] == "base64"

    async def test_get_file_passes_ref(self, github: GitHubRepositoryProvider) -> None:
        mock_client, fake_response = _mock_http_client(
            {"path": "f.py", "sha": "s", "size": 1, "content": _b64("x"), "encoding": "base64", "html_url": None}
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_file",
                    parameters={
                        "repo_id": "octocat/repo",
                        "path": "f.py",
                        "ref": "v1.0.0",
                    },
                )
            )

        call_params = mock_client.get.call_args.kwargs.get("params", {})
        assert call_params.get("ref") == "v1.0.0"


# ---------------------------------------------------------------------------
# GitHub: list_commits
# ---------------------------------------------------------------------------


class TestGitHubListCommits:
    async def test_list_commits_success(self, github: GitHubRepositoryProvider) -> None:
        response_data = [
            {
                "sha": "aaa111",
                "commit": {
                    "message": "Fix login bug",
                    "author": {"name": "Alice", "date": "2024-01-01T00:00:00Z"},
                },
                "html_url": "https://github.com/octocat/repo/commit/aaa111",
            },
            {
                "sha": "bbb222",
                "commit": {
                    "message": "Add feature X",
                    "author": {"name": "Bob", "date": "2024-01-02T00:00:00Z"},
                },
                "html_url": "https://github.com/octocat/repo/commit/bbb222",
            },
        ]
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="list_commits",
                    parameters={"repo_id": "octocat/repo", "ref": "main"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "commit_list"
        raw = result.payload["raw_payload"]
        assert raw["repo_id"] == "octocat/repo"
        assert raw["ref"] == "main"
        assert raw["total"] == 2
        assert raw["commits"][0]["sha"] == "aaa111"
        assert raw["commits"][0]["author"] == "Alice"
        assert raw["commits"][1]["message"] == "Add feature X"

    async def test_list_commits_passes_ref_as_sha(
        self, github: GitHubRepositoryProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client([])
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="list_commits",
                    parameters={"repo_id": "octocat/repo", "ref": "develop", "limit": "5"},
                )
            )

        call_params = mock_client.get.call_args.kwargs.get("params", {})
        assert call_params.get("sha") == "develop"
        assert call_params.get("per_page") == 5


# ---------------------------------------------------------------------------
# GitHub: get_pull_request
# ---------------------------------------------------------------------------


class TestGitHubGetPullRequest:
    async def test_get_pull_request_success(
        self, github: GitHubRepositoryProvider
    ) -> None:
        response_data = {
            "number": 42,
            "title": "Add dark mode",
            "body": "Closes #100",
            "state": "open",
            "user": {"login": "alice"},
            "head": {"ref": "feature/dark-mode"},
            "base": {"ref": "main"},
            "html_url": "https://github.com/octocat/repo/pull/42",
        }
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_pull_request",
                    parameters={"repo_id": "octocat/repo", "pr_id": "42"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "pull_request"
        normalized = result.payload["normalized_payload"]
        assert normalized["repo_id"] == "octocat/repo"
        assert normalized["pr_id"] == "42"
        assert normalized["title"] == "Add dark mode"
        assert normalized["state"] == "open"
        assert normalized["author"] == "alice"
        assert normalized["source_branch"] == "feature/dark-mode"
        assert normalized["target_branch"] == "main"
        assert len(result.payload["references"]) == 1

    async def test_get_pull_request_not_found(
        self, github: GitHubRepositoryProvider
    ) -> None:
        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404
        mock_client, fake_response = _mock_http_client()
        fake_response.status_code = 404
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=mock_response_404
            )
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.github.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await github.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_pull_request",
                    parameters={"repo_id": "octocat/repo", "pr_id": "9999"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE


# ---------------------------------------------------------------------------
# GitHub: auth headers
# ---------------------------------------------------------------------------


class TestGitHubAuthHeaders:
    def test_bearer_auth_header(self, github: GitHubRepositoryProvider) -> None:
        headers = github._auth_headers()
        assert headers["Authorization"].startswith("Bearer ")
        assert "application/vnd.github" in headers["Accept"]


# ---------------------------------------------------------------------------
# GitHub: unknown operation
# ---------------------------------------------------------------------------


class TestGitHubUnknownOperation:
    async def test_unknown_op_returns_not_found(
        self, github: GitHubRepositoryProvider
    ) -> None:
        result = await github.execute(
            ConnectorInvocationRequest(
                capability_type=CapabilityType.REPOSITORY,
                operation="create_branch",
                parameters={},
            )
        )
        assert result.status == ConnectorStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# GitLab: search_repo
# ---------------------------------------------------------------------------


class TestGitLabSearchRepo:
    async def test_search_repo_success(self, gitlab: GitLabRepositoryProvider) -> None:
        response_data = [
            {
                "id": 123,
                "path_with_namespace": "mygroup/myproject",
                "name": "myproject",
                "description": "A project",
                "web_url": "https://gitlab.com/mygroup/myproject",
                "default_branch": "main",
            }
        ]
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="search_repo",
                    parameters={"query": "myproject"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        raw = result.payload["raw_payload"]
        assert raw["total"] == 1
        assert raw["items"][0]["repo_id"] == "123"
        assert raw["items"][0]["name"] == "mygroup/myproject"

    async def test_search_repo_passes_search_param(
        self, gitlab: GitLabRepositoryProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client([])
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="search_repo",
                    parameters={"query": "awesome-lib", "limit": "5"},
                )
            )

        call_params = mock_client.get.call_args.kwargs.get("params", {})
        assert call_params["search"] == "awesome-lib"
        assert call_params["per_page"] == 5


# ---------------------------------------------------------------------------
# GitLab: get_file
# ---------------------------------------------------------------------------


class TestGitLabGetFile:
    async def test_get_file_success(self, gitlab: GitLabRepositoryProvider) -> None:
        encoded = _b64("def hello(): pass\n")
        response_data = {
            "file_name": "main.py",
            "file_path": "src/main.py",
            "size": 18,
            "encoding": "base64",
            "content": encoded,
            "blob_id": "xyz789",
        }
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_file",
                    parameters={
                        "repo_id": "42",
                        "path": "src/main.py",
                        "ref": "main",
                    },
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "repo_file"
        normalized = result.payload["normalized_payload"]
        assert "hello" in normalized["content"]
        assert normalized["encoding"] == "utf-8"
        assert normalized["path"] == "src/main.py"
        assert normalized["ref"] == "main"

    async def test_get_file_path_url_encoded(
        self, gitlab: GitLabRepositoryProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client(
            {"file_path": "a/b.py", "size": 1, "encoding": "base64",
             "content": _b64("x"), "blob_id": "b"}
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_file",
                    parameters={"repo_id": "42", "path": "src/sub/file.py"},
                )
            )

        called_url: str = mock_client.get.call_args.args[0]
        assert "src%2Fsub%2Ffile.py" in called_url

    async def test_get_file_namespace_project_url_encoded(
        self, gitlab: GitLabRepositoryProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client(
            {"file_path": "f.py", "size": 1, "encoding": "base64",
             "content": _b64("x"), "blob_id": "b"}
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_file",
                    parameters={"repo_id": "mygroup/myproject", "path": "f.py"},
                )
            )

        called_url: str = mock_client.get.call_args.args[0]
        assert "mygroup%2Fmyproject" in called_url


# ---------------------------------------------------------------------------
# GitLab: list_commits
# ---------------------------------------------------------------------------


class TestGitLabListCommits:
    async def test_list_commits_success(self, gitlab: GitLabRepositoryProvider) -> None:
        response_data = [
            {
                "id": "sha111",
                "short_id": "sha111",
                "title": "Fix null pointer",
                "author_name": "Carol",
                "authored_date": "2024-03-01T10:00:00Z",
                "web_url": "https://gitlab.com/group/proj/-/commit/sha111",
            }
        ]
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="list_commits",
                    parameters={"repo_id": "42", "ref": "main"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "commit_list"
        commits = result.payload["raw_payload"]["commits"]
        assert commits[0]["sha"] == "sha111"
        assert commits[0]["author"] == "Carol"
        assert commits[0]["message"] == "Fix null pointer"

    async def test_list_commits_passes_ref_name(
        self, gitlab: GitLabRepositoryProvider
    ) -> None:
        mock_client, fake_response = _mock_http_client([])
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="list_commits",
                    parameters={"repo_id": "42", "ref": "develop", "limit": "3"},
                )
            )

        call_params = mock_client.get.call_args.kwargs.get("params", {})
        assert call_params.get("ref_name") == "develop"
        assert call_params.get("per_page") == 3


# ---------------------------------------------------------------------------
# GitLab: get_pull_request
# ---------------------------------------------------------------------------


class TestGitLabGetPullRequest:
    async def test_get_pull_request_success(
        self, gitlab: GitLabRepositoryProvider
    ) -> None:
        response_data = {
            "iid": 7,
            "title": "Implement caching",
            "description": "Adds Redis cache",
            "state": "merged",
            "author": {"name": "Dave", "id": 99},
            "source_branch": "feature/caching",
            "target_branch": "main",
            "web_url": "https://gitlab.com/group/proj/-/merge_requests/7",
        }
        mock_client, fake_response = _mock_http_client(response_data)
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_pull_request",
                    parameters={"repo_id": "42", "pr_id": "7"},
                )
            )

        assert result.status == ConnectorStatus.SUCCESS
        assert result.payload["resource_type"] == "pull_request"
        normalized = result.payload["normalized_payload"]
        assert normalized["pr_id"] == "7"
        assert normalized["title"] == "Implement caching"
        assert normalized["state"] == "merged"
        assert normalized["author"] == "Dave"
        assert normalized["source_branch"] == "feature/caching"
        assert normalized["target_branch"] == "main"

    async def test_get_pull_request_not_found(
        self, gitlab: GitLabRepositoryProvider
    ) -> None:
        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404
        mock_client, fake_response = _mock_http_client()
        fake_response.status_code = 404
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=mock_response_404
            )
        )
        mock_client.get = AsyncMock(return_value=fake_response)

        with patch(
            "agent_orchestrator.connectors.providers.repository.gitlab.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await gitlab.execute(
                ConnectorInvocationRequest(
                    capability_type=CapabilityType.REPOSITORY,
                    operation="get_pull_request",
                    parameters={"repo_id": "42", "pr_id": "9999"},
                )
            )

        assert result.status == ConnectorStatus.FAILURE


# ---------------------------------------------------------------------------
# GitLab: auth headers
# ---------------------------------------------------------------------------


class TestGitLabAuthHeaders:
    def test_private_token_header(self, gitlab: GitLabRepositoryProvider) -> None:
        headers = gitlab._auth_headers()
        assert "PRIVATE-TOKEN" in headers
        assert "Authorization" not in headers

    def test_bearer_when_use_bearer_true(
        self, gitlab_bearer: GitLabRepositoryProvider
    ) -> None:
        headers = gitlab_bearer._auth_headers()
        assert headers["Authorization"].startswith("Bearer ")
        assert "PRIVATE-TOKEN" not in headers

    def test_self_hosted_uses_custom_base_url(
        self, gitlab_self_hosted: GitLabRepositoryProvider
    ) -> None:
        url = gitlab_self_hosted._api_url("projects")
        assert url.startswith("https://gitlab.example.com")


# ---------------------------------------------------------------------------
# GitLab: encode_project_id
# ---------------------------------------------------------------------------


class TestGitLabEncodeProjectId:
    def test_numeric_id_unchanged(self, gitlab: GitLabRepositoryProvider) -> None:
        assert gitlab._encode_project_id("42") == "42"

    def test_namespace_path_url_encoded(self, gitlab: GitLabRepositoryProvider) -> None:
        encoded = gitlab._encode_project_id("mygroup/myproject")
        assert "/" not in encoded
        assert "%2F" in encoded.upper() or "%2f" in encoded.lower()


# ---------------------------------------------------------------------------
# GitLab: unknown operation
# ---------------------------------------------------------------------------


class TestGitLabUnknownOperation:
    async def test_unknown_op_returns_not_found(
        self, gitlab: GitLabRepositoryProvider
    ) -> None:
        result = await gitlab.execute(
            ConnectorInvocationRequest(
                capability_type=CapabilityType.REPOSITORY,
                operation="delete_branch",
                parameters={},
            )
        )
        assert result.status == ConnectorStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# Static artifact factory helpers
# ---------------------------------------------------------------------------


class TestArtifactFactories:
    def test_make_repo_artifact_uses_repository_artifact_normalized(self) -> None:
        artifact = BaseRepositoryProvider._make_repo_artifact(
            provider="repository.github",
            connector_id="repository.github",
            repo_id="octocat/hello-world",
            name="octocat/hello-world",
            description="A test repo",
            url="https://github.com/octocat/hello-world",
            default_branch="main",
            raw_payload={"full_name": "octocat/hello-world"},
            provenance={"provider": "github"},
        )

        assert isinstance(artifact, ExternalArtifact)
        assert artifact.capability_type == CapabilityType.REPOSITORY
        assert artifact.resource_type == "repository"
        normalized = artifact.normalized_payload
        assert normalized["repo_id"] == "octocat/hello-world"
        assert normalized["name"] == "octocat/hello-world"
        assert normalized["default_branch"] == "main"

    def test_make_repo_list_artifact_has_no_normalized_payload(self) -> None:
        artifact = BaseRepositoryProvider._make_repo_list_artifact(
            provider="repository.github",
            connector_id="repository.github",
            query="python cli",
            items=[{"repo_id": "r/r", "name": "r/r"}],
            total=1,
            provenance={"provider": "github"},
        )

        assert artifact.resource_type == "repository"
        assert artifact.normalized_payload is None
        assert artifact.raw_payload["total"] == 1

    def test_make_file_artifact_structure(self) -> None:
        artifact = BaseRepositoryProvider._make_file_artifact(
            provider="repository.github",
            connector_id="repository.github",
            repo_id="octocat/repo",
            path="src/main.py",
            ref="main",
            content="print('hello')",
            encoding="utf-8",
            size=14,
            url="https://github.com/octocat/repo/blob/main/src/main.py",
            raw_payload={"sha": "abc"},
            provenance={"provider": "github"},
        )

        assert artifact.resource_type == "repo_file"
        norm = artifact.normalized_payload
        assert norm["path"] == "src/main.py"
        assert norm["ref"] == "main"
        assert norm["content"] == "print('hello')"
        assert norm["encoding"] == "utf-8"
        assert norm["size"] == 14

    def test_make_commit_list_artifact_structure(self) -> None:
        commits = [{"sha": "abc", "message": "fix bug", "author": "Alice"}]
        artifact = BaseRepositoryProvider._make_commit_list_artifact(
            provider="repository.github",
            connector_id="repository.github",
            repo_id="octocat/repo",
            ref="main",
            commits=commits,
            total=1,
            provenance={"provider": "github"},
        )

        assert artifact.resource_type == "commit_list"
        assert artifact.normalized_payload is None
        raw = artifact.raw_payload
        assert raw["repo_id"] == "octocat/repo"
        assert raw["total"] == 1
        assert raw["commits"][0]["sha"] == "abc"

    def test_make_pr_artifact_structure(self) -> None:
        from agent_orchestrator.connectors.models import ExternalReference

        artifact = BaseRepositoryProvider._make_pr_artifact(
            provider="repository.github",
            connector_id="repository.github",
            repo_id="octocat/repo",
            pr_id="42",
            title="Add feature",
            description="Details",
            state="open",
            author="alice",
            source_branch="feature/x",
            target_branch="main",
            url="https://github.com/octocat/repo/pull/42",
            raw_payload={"number": 42},
            provenance={"provider": "github"},
            references=[
                ExternalReference(
                    provider="repository.github",
                    resource_type="github_pull_request",
                    external_id="42",
                )
            ],
        )

        assert artifact.resource_type == "pull_request"
        norm = artifact.normalized_payload
        assert norm["pr_id"] == "42"
        assert norm["title"] == "Add feature"
        assert norm["state"] == "open"
        assert norm["author"] == "alice"
        assert norm["source_branch"] == "feature/x"
        assert norm["target_branch"] == "main"
        assert len(artifact.references) == 1


# ---------------------------------------------------------------------------
# Package exports
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_exported_from_repository_package(self) -> None:
        from agent_orchestrator.connectors.providers.repository import (
            GitHubRepositoryProvider,
            GitLabRepositoryProvider,
        )

        assert GitHubRepositoryProvider is not None
        assert GitLabRepositoryProvider is not None

    def test_exported_from_providers_package(self) -> None:
        from agent_orchestrator.connectors.providers import (
            GitHubRepositoryProvider,
            GitLabRepositoryProvider,
        )

        assert GitHubRepositoryProvider is not None
        assert GitLabRepositoryProvider is not None

    def test_provider_ids(self) -> None:
        gh = GitHubRepositoryProvider(api_token="ghp_tok")
        gl = GitLabRepositoryProvider(api_token="glpat-tok")

        assert gh.provider_id == "repository.github"
        assert gl.provider_id == "repository.gitlab"


# ---------------------------------------------------------------------------
# Permission hook integration: all ops are read-only, never require approval
# ---------------------------------------------------------------------------


class TestPermissionHookIntegration:
    def test_all_ops_are_allowed_under_requires_approval_policy(self) -> None:
        """All repository operations start with read-like prefixes (get/list/search),
        so they must never trigger the REQUIRES_APPROVAL path."""
        from agent_orchestrator.connectors.permissions import (
            PermissionOutcome,
            evaluate_permission_detailed,
        )
        from agent_orchestrator.connectors.models import (
            ConnectorPermissionPolicy,
        )

        policy = ConnectorPermissionPolicy(
            description="Restrict repo access",
            allowed_capability_types=[CapabilityType.REPOSITORY],
            requires_approval=True,
        )

        for op_name in ("search_repo", "get_file", "list_commits", "get_pull_request"):
            request = ConnectorInvocationRequest(
                capability_type=CapabilityType.REPOSITORY,
                operation=op_name,
                parameters={},
            )
            result = evaluate_permission_detailed(request, [policy])
            assert result.outcome == PermissionOutcome.ALLOW, (
                f"Expected ALLOW for {op_name!r}, got {result.outcome}"
            )
