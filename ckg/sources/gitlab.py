"""GitLab provider — groups, users, and whole self-hosted instances.

Routes API calls to either gitlab.com or a self-hosted instance:

- `gitlab_group` / `gitlab_user` with a plain handle  → gitlab.com
- `gitlab_group` / `gitlab_user` whose `name` is a full URL
  (`https://code.example.com/groups/foo/bar`) → that host's GitLab
- `gitlab_instance` → whole-instance discovery (every project the token
  has access to), `name` is the base URL
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from ckg.sources._http import paginated_get
from ckg.sources.base import DiscoveredRepo, SourceSpec

DEFAULT_BASE = "https://gitlab.com"


def _base_and_path(name: str) -> tuple[str, str]:
    """Split a name into (base_url, handle).

    - `acme` → ("https://gitlab.com", "acme")
    - `https://code.example.com/groups/acme/sub` → ("https://code.example.com", "acme/sub")
    - `https://code.example.com/acme` → ("https://code.example.com", "acme")
    - `https://code.example.com` → ("https://code.example.com", "")
    """
    if name.startswith(("http://", "https://")):
        parts = urlsplit(name.rstrip("/"))
        base = f"{parts.scheme}://{parts.netloc}"
        path = parts.path.lstrip("/")
        # Strip leading `groups/` (group-page URL) — the API uses the group
        # path without that prefix.
        if path.startswith("groups/"):
            path = path[len("groups/"):]
        return base, path
    return DEFAULT_BASE, name


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
        base, group = _base_and_path(spec.name)
        if not group:
            raise ValueError(
                f"gitlab_group requires a group path; got bare host {spec.name!r}. "
                "Use kind=gitlab_instance to discover everything on a self-hosted GitLab."
            )
        url = f"{base}/api/v4/groups/{quote(group, safe='')}/projects"
        params = {
            "per_page": 100,
            "include_subgroups": "true",
            "archived": str(spec.include_archived).lower(),
        }
        rows = paginated_get(url, _headers(spec.token), params)
        return _filter(rows, spec)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        return _inject_token(clone_url, token)


@dataclass
class GitLabUserProvider:
    kind: str = "gitlab_user"

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]:
        base, user = _base_and_path(spec.name)
        if not user:
            raise ValueError(f"gitlab_user requires a user handle; got {spec.name!r}")
        url = f"{base}/api/v4/users/{quote(user)}/projects"
        params = {"per_page": 100}
        rows = paginated_get(url, _headers(spec.token), params)
        return _filter(rows, spec)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        return _inject_token(clone_url, token)


@dataclass
class GitLabInstanceProvider:
    """Discover every project the token has access to on a self-hosted GitLab.

    `name` is the base URL (e.g. `https://code.example.com`). Without a token
    this only returns public projects on the instance, which may be empty.
    With a token it returns every project the token's user is a member of.
    """

    kind: str = "gitlab_instance"

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]:
        base, _ = _base_and_path(spec.name)
        url = f"{base}/api/v4/projects"
        params = {
            "per_page": 100,
            "membership": "true" if spec.token else "false",
            "archived": str(spec.include_archived).lower(),
            "simple": "true",
        }
        rows = paginated_get(url, _headers(spec.token), params)
        return _filter(rows, spec)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        return _inject_token(clone_url, token)


def _inject_token(clone_url: str, token: str) -> str:
    """https://<host>/g/r.git  →  https://oauth2:TOKEN@<host>/g/r.git

    Works for gitlab.com AND self-hosted (the host is taken from clone_url
    itself, so any GitLab instance with HTTPS access works).
    """
    parts = urlsplit(clone_url)
    if parts.scheme not in {"http", "https"}:
        return clone_url
    netloc = f"oauth2:{token}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
