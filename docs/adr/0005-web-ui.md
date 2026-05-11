# ADR 0005 — Next.js web UI

**Status**: Accepted (Phase 4)
**Date**: 2026-05-11

## Context

The CLI is great for automation but doesn't help anyone get oriented in a
fresh graph. We want a browser UI that:

1. Shows graph counts and repo state.
2. Lets you register repos and trigger ingests.
3. Searches functions by keyword and semantic similarity.
4. Visualizes the call graph around a chosen function.

## Decision

Ship a static Next.js 15 (App Router) bundle as a third Compose service.

- **TypeScript + Tailwind CSS** for the app.
- **TanStack Query v5** for API state.
- **react-force-graph-2d** for the call-graph view (canvas, fast, no D3 ceremony).
- **Single-tenant auth**: paste an API token once; persist to localStorage;
  bearer it on every fetch. No server-side session. This matches the
  hosting model decided in ADR-0001 — when we go multi-tenant in Phase 5
  we'll swap this for proper OIDC.
- **No backend rendering of API responses**: the browser calls the API
  directly using CORS (already configured for `http://localhost:3000`).
  Keeping the Next server stateless means it can run as a small
  `output: 'standalone'` build with no secrets baked in.

### Pages

| Path | Purpose |
|---|---|
| `/login` | Paste-token form; validates against `/v1/graph/stats`. |
| `/` | Dashboard — stats cards + repo summary. |
| `/repos` | Register new repos; per-repo ingest (Δ / full) buttons. |
| `/repos/[id]` | Repo detail + live-polling ingest-run table. |
| `/search` | Keyword (FTS) and semantic (vector) search with repo filter. |
| `/graph?repo=…&qname=…&depth=…` | Force-directed call-graph viz. |

### Risks / open issues

- Token in `localStorage`: a cross-site script could read it. We mitigate
  with strict CSP (TODO Phase 5) and by keeping the UI on the same origin
  as the API in production.
- React 19 RC pin: Next 15 ships against it. Once 19.0 is stable we'll
  bump.
- `react-force-graph-2d` uses canvas; the page is dynamically imported
  with `ssr: false` so it never runs server-side.

## Out of scope (Phase 5+)

- Multi-user, role-based UI gates.
- Server-side rendering with auth.
- Flow viewer that animates a request path through the call graph (the
  data is in the graph today; the UI just needs another route).
- File-tree browser per repo.
