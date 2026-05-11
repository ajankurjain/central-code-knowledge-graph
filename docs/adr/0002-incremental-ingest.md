# ADR 0002 — Incremental ingest via per-file sha + persistent CallSites

**Status**: Accepted
**Date**: 2026-05-11

## Context

Phase 1 ingest was always a full wipe + re-parse: 30–90 s for a ~10 kfile repo,
which is painful for the watch-and-update workflow. Most real workloads change
one or two files at a time.

## Decision

Add an `incremental` mode that diffs on-disk file shas against the shas
stored on `File` nodes in Neo4j, and only touches files whose sha changed
(plus deleted-file cleanup and added-file insertion).

The hard part is **call edges**: a `(:Function)-[:CALLS]->(:Function)` edge
spans two files. If file `B` changes and re-creates `B::foo`, all
`*->B::foo` edges from unchanged file `A` were lost when `A`'s `foo` was
detach-deleted. Re-parsing `A` to fix that defeats the point.

The fix: keep **CallSite** nodes — one per call site, owned by the caller —
permanent between ingests, tagged with `file_path`. They're the source of
truth for unresolved call edges. A `_resolve_call_edges` Cypher pass
materializes `CALLS` from `CallSite` repo-wide after every ingest. Because
unchanged files' CallSites stay put, the resolver re-attaches `A`'s call
edges to the new `B::foo` automatically.

## Algorithm

```
on_disk = walk_repo()
existing = (path, sha) for every (:File) in repo

for each path in on_disk:
    if path not in existing:               add → parse + write
    elif sha(path) != existing[path]:      change → purge file sub-graph, parse + write
    else:                                  unchanged → skip

for each path in existing not in on_disk:  remove → purge file sub-graph

resolve_call_edges(repo)                   # idempotent MERGE
```

`purge_file_subgraph` is three Cypher statements:
1. `DETACH DELETE` Class + Function defined by the file (cascades CALLS, HAS_METHOD).
2. `DETACH DELETE` CallSite nodes WHERE `file_path = $p`.
3. `DELETE` `IMPORTS` edges from the file (Module nodes left orphaned, harmless).

## Consequences

- **First-ingest semantics unchanged.** The API endpoint coerces `mode` to
  `full` when `repo.last_indexed_at IS NULL` — incremental on an empty
  graph would be confusing.
- **Storage cost**: ~one CallSite node per call site. For a repo with 500 k
  CALLS edges, that's 500 k extra nodes (Neo4j handles this trivially).
- **Resolver runs every ingest** — repo-scoped, indexed by `repo_id`, fast.
- **Removed files**: deleted from graph and their CallSites are purged.
  Any CALLS edge pointing to a function that lived in the removed file is
  removed by `DETACH DELETE`.

## Alternatives considered

- **Two parallel arrays on Function for pending-calls** (`pending_call_names`,
  `pending_call_lines`): Neo4j-native but harder to scope per-file.
- **JSON-string property**: hard to update and not Cypher-queryable.
- **Full re-parse only**: simple but defeats the incremental story.

## Open questions for Phase 3

- LSP-backed cross-file resolution will replace name-based CallSite matching.
  The CallSite layer becomes optional then but staying with it gives us a
  precise pre-LSP fallback.
