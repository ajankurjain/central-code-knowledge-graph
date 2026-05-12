"""Map kind → provider instance."""

from __future__ import annotations

from ckg.sources.base import SourceProvider
from ckg.sources.bitbucket import BitbucketWorkspaceProvider
from ckg.sources.github import GitHubOrgProvider, GitHubUserProvider
from ckg.sources.gitlab import (
    GitLabGroupProvider,
    GitLabInstanceProvider,
    GitLabUserProvider,
)
from ckg.sources.manifest import ManifestProvider

_PROVIDERS: dict[str, SourceProvider] = {
    "github_org": GitHubOrgProvider(),
    "github_user": GitHubUserProvider(),
    "gitlab_group": GitLabGroupProvider(),
    "gitlab_user": GitLabUserProvider(),
    "gitlab_instance": GitLabInstanceProvider(),
    "bitbucket_workspace": BitbucketWorkspaceProvider(),
    "manifest": ManifestProvider(),
}


def get_provider(kind: str) -> SourceProvider:
    if kind not in _PROVIDERS:
        raise ValueError(f"unknown source kind: {kind}. Known: {sorted(_PROVIDERS)}")
    return _PROVIDERS[kind]


def known_kinds() -> list[str]:
    return sorted(_PROVIDERS)
