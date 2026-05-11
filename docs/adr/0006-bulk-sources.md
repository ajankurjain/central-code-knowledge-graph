# ADR 0006 — Bulk-source ingest

**Status**: Accepted
**Date**: 2026-05-11

## Context

The Phase 1 onboarding story was: register one repo at a time. Real
deployments often want to point at a whole org, group, or workspace and
let the server discover every accessible repo automatically.

## Decision

Add a **bulk source** abstraction. A source is one URL (GitHub org/user,
GitLab group/user, Bitbucket workspace, or a JSON/YAML manifest) and an
optional Personal Access Token. The server discovers every repo
reachable from that source, registers them as normal `Repo` rows, links
them via a `SourceRepo` join row, and queues full ingests for each.

### Schema

```
bulk_sources
  id, kind, name, url, auth_secret (Fernet-encrypted),
  slug_template, include_private, include_forks, include_archived,
  default_branch_override, last_synced_at, last_sync_stats

source_repos
  id, source_id (FK), repo_id (FK), external_id, full_name,
  default_branch, private, archived, fork, discovered_at

repos
  + source_id  (FK, nullable; non-null when discovered via a source)
```

### URL auto-detection

`POST /v1/sources` accepts a single `url` field. The detector recognises:

| Pattern | Kind |
|---|---|
| `github.com/orgs/<name>` | github_org |
| `github.com/<name>` (no `/orgs/`) | github_user |
| `gitlab.com/groups/<path>` | gitlab_group |
| `gitlab.com/<name>` | gitlab_user |
| `bitbucket.org/<workspace>` | bitbucket_workspace |
| `*.json` / `*.yaml` / `*.yml` URL | manifest |

`kind` + `name` may also be supplied explicitly to override auto-detection.

### Provider protocol

```python
class SourceProvider(Protocol):
    kind: str
    def discover(self, spec: SourceSpec) -> Iterable[DiscoveredRepo]: ...
    def credentialed_clone_url(self, clone_url: str, token: str) -> str: ...
```

Built-in providers: `github`, `gitlab`, `bitbucket`, `manifest`. Each
handles pagination and provider-specific filter flags (private / forks /
archived) inside `discover`.

### Auth at rest

PATs are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) keyed by
`CKG_SECRET_KEY`. They never appear in `repos.url`; the worker decrypts
them at clone time and synthesizes a `https://<user>:<token>@host/…`
URL on the fly via the provider's `credentialed_clone_url`.

### Slug generation

Default template `{owner}-{name}`, normalized to `[a-z0-9-_]{1,63}`.
Collisions raise — the caller picks a different template or renames the
existing repo. Manifest-derived repos use `{owner}-{name}` where owner
falls back to `"manifest"` when the URL has no owner segment.

### Cascade delete

`DELETE /v1/sources/{id}` removes the `BulkSource` row, every linked
`SourceRepo`, every `Repo` registered via this source, every
`IngestRun` for those repos, and detach-deletes the Neo4j sub-graphs for
each repo. This matches the explicit "delete this and everything it
created" intent.

## Consequences

Good:
- One command pulls a whole org into the graph.
- Private repos work end-to-end via stored PATs.
- The `repos` table stays clean (no embedded credentials).

Tradeoffs:
- `CKG_SECRET_KEY` is now a load-bearing secret. Lose it and the encrypted
  PATs become unrecoverable; you have to re-enter them per source.
- We re-discover the whole upstream on every `sync` — fine for orgs in the
  100s of repos, will need pagination + delta detection for very large
  GitLab installs (Phase 5).
- Bitbucket's API has no "archived" flag; that filter is a no-op there.

## Open work

- Per-source / per-repo polling intervals (ADR-0007 / Commit B).
- Inbound webhooks for push-driven incremental ingest (ADR-0007 / Commit B).
- Manifest spec stabilization + versioning.
