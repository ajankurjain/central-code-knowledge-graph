"""GitLab provider — groups (and subgroups) + users.

Uses the v4 REST API. Supports gitlab.com and self-hosted via a custom base
URL (today we only call out to gitlab.com; the provider is structured to
take a base in the future).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from ckg.sources._http import paginated_get
from ckg.sources.base import DiscoveredRepo, SourceSpec

GITLAB_API = "https://gitlab.com/api/v4"


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/json"}
    if token:
        h["PRIVATE-TOKEN"] = token
    return h


def _to_discovered(row: dict) -> DiscoveredRepo:
    namespace = row.get("namespace") or {}
    owner = namespace.get("full_path") or namespace.get("path") or ""
    return DiscoveredRepo(
        external_id=str(row["id"]),
        owner=owner,
        name=row["path"],
        full_name=row.get("path_with_namespace") or f"{owner}/{row['path']}",
        clone_url=row["http_url_to_repo"],
        default_branch=row.get("default_branch") or "main",
        private=row.get("visibility", "private") != "public",
        archived=bool(row.get("archived")),
        fork="forked_from_project" in row,
    )


def _filter(rows: Iterable[dict], spec: SourceSpec) -> Iterable[DiscoveredRepo]:
    for row in rows:
        if not spec.include_archived and row.get("archived"):
            continue
        if not spec.include_forks and ("forked_from_project" in row):
            continue
        if not spec.include_private and row.get("visibility", "private") != "public":
            continue
        yield _to_discovered(row)


@dataclass
class GitLabGroupProvider:
    kind: str = "gitlab_group"

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]:
        url = f"{GITLAB_API}/groups/{quote(spec.name, safe='')}/projects"
        params = {"per_page": 100, "include_subgroups": "true", "archived": str(spec.include_archived).lower()}
        rows = paginated_get(url, _headers(spec.token), params)
        return _filter(rows, spec)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        return _inject_token(clone_url, token)


@dataclass
class GitLabUserProvider:
    kind: str = "gitlab_user"

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]:
        url = f"{GITLAB_API}/users/{quote(spec.name)}/projects"
        params = {"per_page": 100}
        rows = paginated_get(url, _headers(spec.token), params)
        return _filter(rows, spec)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        return _inject_token(clone_url, token)


def _inject_token(clone_url: str, token: str) -> str:
    """https://gitlab.com/g/r.git  →  https://oauth2:TOKEN@gitlab.com/g/r.git"""
    parts = urlsplit(clone_url)
    if parts.scheme not in {"http", "https"}:
        return clone_url
    netloc = f"oauth2:{token}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
