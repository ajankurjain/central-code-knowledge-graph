"""GitHub provider — discovery + filtering + token injection."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from ckg.sources.base import SourceSpec
from ckg.sources.github import GitHubOrgProvider, GitHubUserProvider, _inject_token

FAKE_ROWS = [
    {
        "id": 1, "name": "open", "full_name": "acme/open",
        "owner": {"login": "acme"}, "clone_url": "https://github.com/acme/open.git",
        "default_branch": "main", "private": False, "archived": False, "fork": False,
    },
    {
        "id": 2, "name": "private", "full_name": "acme/private",
        "owner": {"login": "acme"}, "clone_url": "https://github.com/acme/private.git",
        "default_branch": "develop", "private": True, "archived": False, "fork": False,
    },
    {
        "id": 3, "name": "fork", "full_name": "acme/fork",
        "owner": {"login": "acme"}, "clone_url": "https://github.com/acme/fork.git",
        "default_branch": "main", "private": False, "archived": False, "fork": True,
    },
    {
        "id": 4, "name": "archived", "full_name": "acme/archived",
        "owner": {"login": "acme"}, "clone_url": "https://github.com/acme/archived.git",
        "default_branch": "main", "private": False, "archived": True, "fork": False,
    },
]


@pytest.fixture
def patched_pages(monkeypatch):
    def _fake_paginated_get(url: str, headers: dict, params=None) -> Iterable[dict]:
        return FAKE_ROWS

    monkeypatch.setattr("ckg.sources.github.paginated_get", _fake_paginated_get)


def test_github_org_default_filters(patched_pages) -> None:
    provider = GitHubOrgProvider()
    spec = SourceSpec(kind="github_org", name="acme", token="ghp_fake")
    out = list(provider.discover(spec))
    names = {r.name for r in out}
    # Default: private allowed, forks excluded, archived excluded
    assert names == {"open", "private"}


def test_github_org_include_forks_and_archived(patched_pages) -> None:
    provider = GitHubOrgProvider()
    spec = SourceSpec(
        kind="github_org", name="acme", token=None,
        include_private=False, include_forks=True, include_archived=True,
    )
    out = list(provider.discover(spec))
    names = {r.name for r in out}
    assert names == {"open", "fork", "archived"}


def test_github_user_discover(patched_pages) -> None:
    provider = GitHubUserProvider()
    spec = SourceSpec(kind="github_user", name="octocat", token=None, include_private=False)
    out = list(provider.discover(spec))
    assert {r.name for r in out} == {"open"}  # only public, no forks, no archived


def test_inject_token_https():
    url = "https://github.com/acme/repo.git"
    new = _inject_token(url, "ghp_xyz")
    assert new == "https://x-access-token:ghp_xyz@github.com/acme/repo.git"


def test_inject_token_leaves_ssh_alone():
    url = "git@github.com:acme/repo.git"
    assert _inject_token(url, "ghp_xyz") == url
