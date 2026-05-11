# ADR 0001 — Initial architecture

**Status**: Accepted  
**Date**: 2026-05-11  
**Decision-makers**: project initial scope

## Context

We want a multi-repo code knowledge graph service that AI agents (Cursor,
VS Code, Claude Code) can query for structural relationships, keyword search,
and semantic search. Existing local-only tools cover parts of this, but none
is multi-repo + multi-language + central + token-secured in one package.

## Decision

Build a Python-based service with the following components:

- **Graph store**: Neo4j 5 Community (native vector + FTS + Cypher) — one store
  for relationship traversal, semantic search, and keyword search.
- **API**: FastAPI; REST endpoints; HTTP JSON-RPC for MCP; async-ready.
- **Workers**: Celery with Redis broker for ingest (clone + parse + write).
- **Postgres**: Repo registry, API tokens, ingest run history, audit log.
- **Parsing**: Tree-sitter via `tree-sitter-language-pack`. One parser module
  per language under `ckg/parsers/`.
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (local; no API
  cost). Pluggable via env.
- **Auth**: API tokens, argon2id-hashed in Postgres. A bootstrap token in env
  is the only way to mint the first real token.
- **CLI**: Typer-based `ckg` command that talks to the API over REST.
- **Deployment**: Docker Compose for now; the service boundaries are k8s-ready
  for a later phase.

## Alternatives considered

- **NetworkX / SQLite (like the existing CRG tool)**: simple, but doesn't scale
  to many repos and lacks vector + Cypher query power.
- **JanusGraph / Memgraph**: more operational complexity, no clear win over
  Neo4j for our query patterns.
- **Build the graph layer ourselves on Postgres**: slow on multi-hop traversals
  compared to a native graph DB.
- **Node.js / TypeScript stack**: we picked Python because Tree-sitter
  Python bindings + sentence-transformers + Celery are the shortest path.

## Consequences

Good:
- Single graph DB simplifies indexing (vector + FTS + structural).
- Workers can scale horizontally without touching the API.
- Bring-up via `docker compose up` is one command.

Tradeoffs:
- Tree-sitter alone can't resolve all cross-file calls precisely; that's why
  the schema reserves `CALLS` as a separate edge that LSP integration (Phase 4)
  will improve.
- A single Neo4j instance is the throughput bottleneck. Phase 5 ops work adds
  a Neo4j Causal Cluster or Aura.

## Out of scope (deferred)

- Web UI — Phase 5.
- Multi-tenant org/user model — Phase 5.
- Rust / Ruby / Go / Java parsers — Phase 4.
- Incremental update (only changed files) — Phase 2.
