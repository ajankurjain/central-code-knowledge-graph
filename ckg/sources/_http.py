"""Shared HTTP helpers for providers — paginated GET + Link-header parsing."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def paginated_get(url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> Iterator[Any]:
    """Yield items from each page following RFC 5988 `Link: <…>; rel="next"`."""
    next_url: str | None = url
    next_params: dict[str, Any] | None = dict(params or {})
    with httpx.Client(headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        while next_url:
            r = client.get(next_url, params=next_params)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                yield from data
            elif isinstance(data, dict) and "values" in data:
                # Bitbucket-style paged envelope
                yield from data["values"]
                next_url = data.get("next")
                next_params = None
                continue
            else:
                yield data
            link = r.headers.get("Link") or r.headers.get("link")
            next_url = _next_link(link)
            next_params = None  # next URL already contains its query


_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    m = _LINK_RE.search(link_header)
    return m.group(1) if m else None
