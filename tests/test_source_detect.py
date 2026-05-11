"""URL kind auto-detection."""

import pytest

from ckg.sources.detect import detect_source_kind


@pytest.mark.parametrize(
    "url,kind,name",
    [
        ("https://github.com/orgs/anthropics", "github_org", "anthropics"),
        ("github.com/orgs/anthropics/", "github_org", "anthropics"),
        ("https://github.com/users/octocat", "github_user", "octocat"),
        ("https://github.com/octocat", "github_user", "octocat"),
        ("gh:octocat", "github_user", "octocat"),
        ("https://gitlab.com/groups/gitlab-org", "gitlab_group", "gitlab-org"),
        ("https://gitlab.com/groups/gitlab-org/sub-group", "gitlab_group", "gitlab-org/sub-group"),
        ("https://gitlab.com/octocat", "gitlab_user", "octocat"),
        ("gl:octocat", "gitlab_user", "octocat"),
        ("https://bitbucket.org/atlassian", "bitbucket_workspace", "atlassian"),
        ("bb:atlassian", "bitbucket_workspace", "atlassian"),
        ("https://example.com/repos.yaml", "manifest", "https://example.com/repos.yaml"),
        ("https://example.com/list.json", "manifest", "https://example.com/list.json"),
    ],
)
def test_detect_known(url: str, kind: str, name: str) -> None:
    k, n = detect_source_kind(url)
    assert k == kind
    assert n == name


def test_detect_unknown():
    with pytest.raises(ValueError):
        detect_source_kind("https://example.com/something-else")
