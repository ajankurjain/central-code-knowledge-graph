"""Bitbucket Cloud provider — repositories under a workspace.

Auth: Bitbucket App Passwords (recommended) or workspace access tokens.
Pass the value as `token`; we always use HTTP basic auth and prefer the
`x-bitbucket-api-token-auth` username when the secret looks like an API
token (starts with `ATBB`), falling back to a literal username:password
pair when the user supplies it in `user:pass` form.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from ckg.sources._http import paginated_get
from ckg.sources.base import DiscoveredRepo, SourceSpec

BITBUCKET_API = "https://api.bitbucket.org/2.0"


def _auth_header(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    user, sep, pw = token.partition(":")
    if not sep:
        # Bitbucket API tokens start with `ATBB...`; use the documented
        # `x-bitbucket-api-token-auth` username for those, otherwise treat
        # the value as a raw app-password tied to the workspace handle (the
        # caller will need to use user:pass form for that case).
        user = "x-bitbucket-api-token-auth"
        pw = token
    creds = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/json"}
    h.update(_auth_header(token))
    return h


def _to_discovered(row: dict) -> DiscoveredRepo:
    full_name = row.get("full_name") or ""
    owner, _, name = full_name.partition("/")
    clone_url = ""
    for link in (row.get("links", {}) or {}).get("clone", []) or []:
        if link.get("name") == "https":
            clone_url = link.get("href") or ""
            break
    if not clone_url:
        clone_url = f"https://bitbucket.org/{full_name}.git"
    return DiscoveredRepo(
        external_id=str(row.get("uuid") or row.get("full_name") or ""),
        owner=owner,
        name=name or row.get("slug") or "",
        full_name=full_name,
        clone_url=clone_url,
        default_branch=(row.get("mainbranch") or {}).get("name") or "main",
        private=bool(row.get("is_private")),
        archived=False,                # Bitbucket has no "archived" flag
        fork="parent" in row,
    )


def _filter(rows: Iterable[dict], spec: SourceSpec) -> Iterable[DiscoveredRepo]:
    for row in rows:
        if not spec.include_forks and ("parent" in row):
            continue
        if not spec.include_private and row.get("is_private"):
            continue
        yield _to_discovered(row)


@dataclass
class BitbucketWorkspaceProvider:
    kind: str = "bitbucket_workspace"

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]:
        url = f"{BITBUCKET_API}/repositories/{quote(spec.name)}"
        params = {"pagelen": 100}
        rows = paginated_get(url, _headers(spec.token), params)
        return _filter(rows, spec)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        """Inject basic-auth into the HTTPS clone URL."""
        if not token:
            return clone_url
        user, sep, pw = token.partition(":")
        if not sep:
            user, pw = "x-bitbucket-api-token-auth", token
        parts = urlsplit(clone_url)
        if parts.scheme not in {"http", "https"}:
            return clone_url
        netloc = f"{quote(user, safe='')}:{quote(pw, safe='')}@{parts.netloc}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
