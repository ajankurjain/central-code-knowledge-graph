"""Pick the right provider kind from a user-pasted URL.

We accept a wide range of input forms — full URLs, "shortcut" forms like
`gh:acme`, and plain `github.com/acme`. The user pastes whatever they
have on hand and we figure it out.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, kind, group-index of the name capture (as a string for clarity))
    (r"^(?:https?://)?github\.com/orgs/([^/?#]+)/?", "github_org", "1"),
    (r"^(?:https?://)?github\.com/users/([^/?#]+)/?", "github_user", "1"),
    (r"^(?:https?://)?github\.com/([^/?#]+)/?$", "github_user", "1"),  # bare user
    (r"^gh:([^/?#]+)$", "github_user", "1"),
    (r"^(?:https?://)?gitlab\.com/groups/(.+?)/?$", "gitlab_group", "1"),
    (r"^(?:https?://)?gitlab\.com/([^/?#]+)/?$", "gitlab_user", "1"),
    (r"^gl:([^/?#]+)$", "gitlab_user", "1"),
    (r"^(?:https?://)?bitbucket\.org/([^/?#]+)/?$", "bitbucket_workspace", "1"),
    (r"^bb:([^/?#]+)$", "bitbucket_workspace", "1"),
]


def detect_source_kind(url: str) -> tuple[str, str]:
    """Returns (kind, name). Raises ValueError if nothing matches.

    Manifest URLs are recognised by extension (.json / .yaml / .yml) and
    return the full URL as the `name`.
    """
    u = url.strip()
    if not u:
        raise ValueError("empty URL")
    if u.endswith((".json", ".yaml", ".yml")):
        return "manifest", u
    for pat, kind, _ in _PATTERNS:
        m = re.match(pat, u, re.IGNORECASE)
        if m:
            return kind, m.group(1)
    raise ValueError(f"unrecognized source URL: {url!r}")
