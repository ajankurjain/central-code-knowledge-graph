"""GitHub provider — orgs and users (cloud + Enterprise)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from ckg.sources._http import paginated_get
from ckg.sources.base import DiscoveredRepo, SourceSpec


GITHUB_API = "https://api.github.com"


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"token {token}"
    return h


def _to_discovered(row: dict) -> DiscoveredRepo:
    return DiscoveredRepo(
        external_id=str(row["id"]),
        owner=row["owner"]["login"],
        name=row["name"],
        full_name=row["full_name"],
        clone_url=row["clone_url"],
        default_branch=row.get("default_branch") or "main",
        private=bool(row.get("private")),
        archived=bool(row.get("archived")),
        fork=bool(row.get("fork")),
    )


def _filter(rows: Iterable[dict], spec: SourceSpec) -> Iterable[DiscoveredRepo]:
    for row in rows:
        if not spec.include_archived and row.get("archived"):
            continue
        if not spec.include_forks and row.get("fork"):
            continue
        if not spec.include_private and row.get("private"):
            continue
        yield _to_discovered(row)


@dataclass
class GitHubOrgProvider:
    kind: str = "github_org"

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]:
        url = f"{GITHUB_API}/orgs/{quote(spec.name)}/repos"
        params = {"per_page": 100, "type": "all" if spec.token else "public"}
        rows = paginated_get(url, _headers(spec.token), params)
        return _filter(rows, spec)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        return _inject_token(clone_url, token)


@dataclass
class GitHubUserProvider:
    kind: str = "github_user"

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]:
        # When the token belongs to the same user, use /user/repos to include
        # private + collaborator repos. Otherwise /users/{name}/repos which is
        # public-only.
        url = f"{GITHUB_API}/users/{quote(spec.name)}/repos"
        params = {"per_page": 100, "type": "owner"}
        rows = paginated_get(url, _headers(spec.token), params)
        return _filter(rows, spec)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        return _inject_token(clone_url, token)


def _inject_token(clone_url: str, token: str) -> str:
    """https://github.com/o/r.git  →  https://x-access-token:TOKEN@github.com/o/r.git"""
    parts = urlsplit(clone_url)
    if parts.scheme not in {"http", "https"}:
        return clone_url
    netloc = f"x-access-token:{token}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
