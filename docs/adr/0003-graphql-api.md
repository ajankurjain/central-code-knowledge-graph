# ADR 0003 — GraphQL endpoint

**Status**: Accepted
**Date**: 2026-05-11

## Context

The REST surface is fine for one-shot queries but agents and the future web
UI want to compose graph queries — "for these N functions, give me their
callers + the files those callers live in + the blast radius of each". One
GraphQL round-trip is cleaner than N REST round-trips.

## Decision

Add a GraphQL endpoint at `POST /v1/graphql` using **Strawberry** (modern
Python GraphQL library, native FastAPI integration, types-first). It
mirrors the REST query surface — no separate domain model.

Auth is reused: the FastAPI dependency `require_repo_read` runs before the
Strawberry router resolves the request, so the same bearer-token contract
applies. GraphiQL UI is exposed at the same URL for interactive
exploration.

## Schema (initial)

```graphql
type Query {
  stats: Stats!
  callersOf(repoId: String!, qualifiedName: String!, depth: Int = 1, limit: Int = 100): [FunctionRef!]!
  calleesOf(repoId: String!, qualifiedName: String!, depth: Int = 1, limit: Int = 100): [FunctionRef!]!
  importsOf(repoId: String!, path: String!, limit: Int = 200): [ImportEntry!]!
  blastRadius(repoId: String!, path: String!, depth: Int = 2, limit: Int = 500): [String!]!
  downstreamDependencies(repoId: String!, path: String!, depth: Int = 2, limit: Int = 500): [String!]!
  fileOverview(repoId: String!, path: String!): FileSymbols
  searchKeyword(q: String!, repoId: String, limit: Int = 25): [SearchHit!]!
  searchSemantic(q: String!, repoId: String, limit: Int = 10): [SearchHit!]!
}
```

## Why not just REST?

- **N+1 round-trips** are common when an agent traverses the graph.
- **Selectable fields** — the agent only pays for what it asks for.
- **Composition** — a single request can mix structural, keyword, and
  semantic queries.

REST stays as the primary contract for simple cases and OpenAPI tooling.
Both surfaces are first-class.

## Consequences

- One more dependency (`strawberry-graphql[fastapi]`).
- GraphiQL UI is on by default — useful for dev, fine in single-tenant
  mode. When we go multi-tenant in Phase 5 we'll toggle it off in prod.
- No mutations exposed yet. Repo register / ingest / token mint stay
  REST-only on purpose — they're side-effectful and audit-logged through
  the existing routes.
