"""Source-provider protocol + shared types."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SourceSpec:
    """A user-facing source registration."""

    kind: str               # github_org | github_user | gitlab_group | gitlab_user | bitbucket_workspace | manifest
    name: str               # org/group/user/workspace handle, or manifest URL
    token: str | None       # decrypted PAT (in memory only); None for anonymous
    include_private: bool = True
    include_forks: bool = False
    include_archived: bool = False
    default_branch_override: str | None = None


@dataclass(frozen=True)
class DiscoveredRepo:
    """One repo returned by a provider's discover() call."""

    external_id: str        # provider's stable id (e.g. GitHub numeric id)
    owner: str              # org or user handle that owns the repo
    name: str               # short repo name
    full_name: str          # "owner/name" — same format across providers
    clone_url: str          # https clone URL (without credentials)
    default_branch: str
    private: bool
    archived: bool
    fork: bool


class SourceProvider(Protocol):
    """Provider for one `kind`. Statelessly returns the repos under a spec."""

    kind: str

    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]: ...

    def credentialed_clone_url(self, clone_url: str, token: str) -> str:
        """Inject a token into the HTTPS clone URL for `git clone` over HTTPS."""
        ...
