"""Manifest provider — explicit list of git URLs at an HTTP(S) URL.

Format (JSON or YAML):

    repos:
      - id: my-repo                  # optional; auto-derived from URL when omitted
        url: https://github.com/o/r.git
        branch: main                 # optional, default "main"
      - https://gitlab.com/g/p.git   # short form
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import yaml

from ckg.sources._http import DEFAULT_TIMEOUT
from ckg.sources.base import DiscoveredRepo, SourceSpec


@dataclass
class ManifestProvider:
    kind: str = "manifest"

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]:
        headers = {"Accept": "*/*"}
        if spec.token:
            # Some private manifest URLs (e.g. GitLab raw) accept a PRIVATE-TOKEN
            headers["PRIVATE-TOKEN"] = spec.token
        with httpx.Client(headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=True) as c:
            r = c.get(spec.name)
            r.raise_for_status()
            text = r.text
        doc = _parse(text, url=spec.name)
        repos = doc.get("repos") if isinstance(doc, dict) else doc
        if not isinstance(repos, list):
            raise ValueError(f"manifest at {spec.name} does not contain a list of repos")
        for item in repos:
            yield _row_to_discovered(item, override_branch=spec.default_branch_override)

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        # The manifest can include any git URL — we don't pretend to know the
        # right auth shape for them. Return as-is; callers can pre-bake creds
        # into the URLs in the manifest.
        return clone_url


def _parse(text: str, *, url: str) -> dict | list:
    text_lower = url.lower()
    if text_lower.endswith(".json"):
        import json

        return json.loads(text)
    return yaml.safe_load(text)


def _row_to_discovered(item, *, override_branch: str | None) -> DiscoveredRepo:
    if isinstance(item, str):
        url = item
        rid = None
        branch = None
    elif isinstance(item, dict):
        url = item.get("url") or item.get("clone_url")
        rid = item.get("id")
        branch = item.get("branch")
    else:
        raise ValueError(f"manifest item not understood: {item!r}")
    if not url:
        raise ValueError(f"manifest item missing 'url': {item!r}")
    owner, name = _owner_and_name(url)
    return DiscoveredRepo(
        external_id=rid or url,
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        clone_url=url,
        default_branch=branch or override_branch or "main",
        private=False,
        archived=False,
        fork=False,
    )


def _owner_and_name(url: str) -> tuple[str, str]:
    """Best-effort split of a git URL into (owner, repo)."""
    path = urlsplit(url).path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return "/".join(parts[:-1]), parts[-1]
    if len(parts) == 1:
        return "manifest", parts[0]
    return "manifest", "repo"
