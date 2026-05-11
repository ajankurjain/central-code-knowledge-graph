# ADR 0007 — Periodic sync + inbound webhooks

**Status**: Accepted
**Date**: 2026-05-11

## Context

Phase 4 left ingest as a manually-triggered action (`ckg repo ingest …` or
`ckg source sync …`). For day-to-day use we want the graph to stay fresh
without anyone driving it.

Two complementary mechanisms:

1. **Polling** — per-source and per-repo `*_interval_seconds`. Cheap, no
   external configuration; ideal when the operator doesn't have / want
   write access to the upstream's webhook settings.
2. **Webhooks** — push-based, ~instantaneous; ideal when the operator
   can configure GitHub / GitLab / Bitbucket to call us.

## Decision

### Polling

- Add a **`beat`** Compose service running `celery beat` with two
  periodic tasks at 60-second cadence:
  - `ckg.scan_sources_for_sync` — picks BulkSources with
    `sync_interval_seconds > 0` whose `last_synced_at` is older than the
    interval, enqueues `ckg.run_source_sync`.
  - `ckg.scan_repos_for_poll` — picks Repos with
    `poll_interval_seconds > 0` whose `last_indexed_at` is older than the
    interval, enqueues `ckg.ingest_repo` in incremental mode (or full on
    first ingest).
- Scheduler floor: 60 s. Set anything sub-minute and we treat it as 60 s.

### Webhooks

- One receiver: `POST /v1/webhooks/{source_id}`. Provider is auto-detected
  from request headers:
  - `X-GitHub-Event` / `X-Hub-Signature-256` → GitHub
  - `X-Gitlab-Event` / `X-Gitlab-Token` → GitLab
  - `X-Event-Key: repo:*` → Bitbucket
- Per-source `webhook_secret` (URL-safe, 32 bytes random). Verification
  matches each provider's idiom:
  - **GitHub**: `X-Hub-Signature-256` is `sha256=` + HMAC-SHA256 of the
    raw body. Compared timing-safely.
  - **GitLab**: `X-Gitlab-Token` header equality.
  - **Bitbucket**: `?secret=…` query parameter equality (Bitbucket Cloud
    doesn't sign payloads by default).
- After verification, we parse the push payload, extract
  `(full_name, ref)`, look up the matching `SourceRepo`, and enqueue an
  **incremental** ingest (coerced to full if `last_indexed_at IS NULL`).
- Non-push events are accepted but no-op. GitHub `ping` is recognised.

### Operator workflow

```bash
# Polling
ckg source schedule 1 30m         # re-sync source 1 every 30 minutes
ckg repo   poll     my-repo 5m    # incremental ingest every 5 minutes

# Webhooks
ckg source webhook 1 --enable     # prints the secret + receiver URL
# → paste secret into the upstream's webhook config (GitHub / GitLab / Bitbucket)
```

## Consequences

Good:
- One beat container plus the existing worker fleet handles cluster-wide
  scheduling. Beat is a single point of scheduling but not a single point
  of execution; the actual work runs on the worker pool.
- Webhooks reuse the existing `BulkSource → SourceRepo → Repo` chain;
  there's no extra coupling.

Tradeoffs:
- Only **one** beat process must run. Compose handles this trivially; on
  k8s we'll use a leader election or a CronJob (Phase 5).
- Webhook verification depends on the upstream's signing model. Bitbucket
  Cloud's lack of HMAC signing is a meaningful weak point — secrets in
  query strings are exposed in any access log between us and them.
- We don't track per-event delivery (no de-dup of replayed deliveries).
  GitHub adds a delivery ID we could persist; deferred to Phase 5.

## Open work

- HMAC for Bitbucket once Bitbucket Cloud rolls out signing (DC supports
  it today).
- Per-delivery audit + replay protection.
- A `dryRun` flag on `POST /v1/sources/{id}/sync` for CI use.
