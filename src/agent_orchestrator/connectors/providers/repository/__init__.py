"""Repository capability connector providers."""
from .github import GitHubRepositoryProvider
from .gitlab import GitLabRepositoryProvider

__all__ = [
    "GitHubRepositoryProvider",
    "GitLabRepositoryProvider",
]
