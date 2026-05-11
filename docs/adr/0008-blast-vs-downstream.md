# ADR 0008 — Split `impact_radius` into `blast_radius` + `downstream_dependencies`

**Status**: Accepted
**Date**: 2026-05-11

## Context

`impact_radius` was the original "if I change this file, what breaks?"
endpoint. The implementation walked **outgoing** CALLS edges, which is
the wrong direction — it returns files this file *depends on*, not files
that *depend on* this file. The name and the README description both
called it "blast radius", but the Cypher returned downstream callees.

## Decision

Two endpoints with honest names:

| Endpoint | Direction | "I want to know…" |
|---|---|---|
| `GET /v1/graph/blast_radius` | upstream callers | …what breaks if I change this file |
| `GET /v1/graph/downstream_dependencies` | outgoing callees | …what this file depends on |

`blast_radius` walks:

```cypher
MATCH (src:File {…})-[:DEFINES]->(target:Function)<-[:CALLS*1..N]-(caller:Function)
MATCH (caller_file:File)-[:DEFINES]->(caller)
WHERE caller_file <> src
RETURN DISTINCT caller_file.path
```

`downstream_dependencies` walks the same path with the CALLS arrow
flipped — same shape, opposite direction. Both filter out the source
file itself so self-recursion doesn't pad results.

Same change replicated through:
- GraphQL: `blastRadius` + `downstreamDependencies`
- MCP: `ckg.blast_radius` + `ckg.downstream_dependencies`
- CLI: `ckg graph blast` + `ckg graph downstream`
- Web UI: `api.blastRadius()` + `api.downstreamDependencies()`

## Known gap (deferred)

Neither endpoint follows `:IMPORTS` edges yet. A file that imports a
class/type from `src` but never invokes a function on it isn't counted
in `blast_radius`. To fix this we'd need to either:

1. Resolve `IMPORTS` targets to concrete `File` nodes at ingest time
   (currently they point to `Module` nodes keyed by the import string),
   OR
2. Persist a `module_qname` property on `File` so the query can JOIN
   `Module.name = File.module_qname` cheaply.

Option (2) is cheaper; tracked for the next change. Until then the
docstring on `blast_radius` flags the limitation.

## Why not preserve the old name as an alias?

The repo is a few hours old and no production caller relies on
`impact_radius`. A backwards-compatibility shim would be dead weight
forever. Clean break is right here.

## Precision caveat (unchanged)

Both endpoints inherit the precision of the underlying `CALLS` edges. With
the name-based resolver (Phase 1 default), short-name collisions inflate
both sides. Turn on `CKG_LSP_ENABLED=true` for precise edges in languages
that have a registered LSP adapter (pyright today).
