"""Pick the right provider kind from a user-pasted URL.

We accept a wide range of input forms — full URLs, "shortcut" forms like
`gh:acme`, and plain `github.com/acme`. The user pastes whatever they
have on hand and we figure it out.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

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

# Self-hosted GitLab: any URL we don't recognise that has the shape of a
# bare host (e.g. `https://code.concirrusquest.com`) is treated as a GitLab
# instance root — the provider then lists every project the token can see
# via `<base>/api/v4/projects?membership=true`. Subgroup URLs like
# `<base>/groups/<path>` route to gitlab_group with the full URL kept as
# the name so the provider can pull the base out at API-call time.
_GITLAB_HOSTED_GROUP = re.compile(
    r"^(https?://[^/?#]+)/groups/(.+?)/?$", re.IGNORECASE
)
_BARE_HOST = re.compile(r"^https?://[^/?#]+/?$", re.IGNORECASE)


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

    # Self-hosted GitLab fallbacks. We never enable these for github.com,
    # gitlab.com or bitbucket.org — those have their own patterns above and
    # a miss there means the URL is genuinely malformed, not self-hosted.
    parts = urlsplit(u)
    host = (parts.netloc or "").lower()
    if host and host not in {"github.com", "gitlab.com", "bitbucket.org"}:
        if _GITLAB_HOSTED_GROUP.match(u):
            # `<base>/groups/<path>` — keep the whole URL as `name`; the
            # provider will parse base + path out of it.
            return "gitlab_group", u.rstrip("/")
        if _BARE_HOST.match(u):
            # `https://<host>` — whole-instance discovery (everything the
            # token has access to).
            return "gitlab_instance", u.rstrip("/")

    raise ValueError(f"unrecognized source URL: {url!r}")
