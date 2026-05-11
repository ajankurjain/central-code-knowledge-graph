# ADR 0010 — Auto-generated architecture map + coupling warnings

**Status**: Accepted
**Date**: 2026-05-11

## Context

We have a rich file/call graph but no zoomed-out view of how a repo is
*organised*. Reviewers asking "is this module too coupled?" or "are
there circular dependencies between these layers?" have nowhere to look.

## Decision

Add a post-ingest analyzer that clusters files into modules using
community detection and surfaces a small set of well-known design-smell
warnings. The result lives next to the existing graph so MCP/CLI/Web
clients can read it the same way they read everything else.

### Algorithm

1. **Build a file→file dependency graph** by aggregating the existing
   `:CALLS` edges (`File-DEFINES-Function-CALLS-Function-DEFINES-File`)
   plus a best-effort `:IMPORTS` match (Module name matching the
   importer-side file path stem — works for Python/Java where parser-
   emitted module names match path slugs).
2. **Cluster** the files: NetworkX `louvain_communities` on the
   undirected weighted graph with a fixed seed (deterministic re-runs).
3. **Per-file metrics**: distinct-fan-in, distinct-fan-out.
4. **Per-cluster metrics**:
   - Martin instability `I = fan_out / (fan_in + fan_out)`,
   - cohesion = intra-cluster edges / (intra + external),
   - file count.
5. **Cluster→Cluster edges** by summing cross-cluster file-pair weights.
6. **Detect cycles** with `strongly_connected_components` on the
   directed graph.
7. **Persist** as new Neo4j labels — `Cluster`, `Warning` — under the
   same `repo_id` namespace. Re-runnable; each run replaces the prior
   set.

### Warnings emitted (initial)

| kind | trigger | severity |
|---|---|---|
| `cyclic_dependency` | SCC of >1 files | high |
| `high_fan_in` | file fan-in > `CKG_ARCH_FAN_IN_THRESHOLD` (default 20) | medium |
| `high_fan_out` | file fan-out > `CKG_ARCH_FAN_OUT_THRESHOLD` (default 15) | medium |
| `low_cohesion` | cluster cohesion < `CKG_ARCH_COHESION_FLOOR` (default 0.4) | low |
| `sdp_violation` | cluster A→B where `I(A) + 0.1 < I(B)` | medium |
| `hub_cluster` | cluster has > `CKG_ARCH_HUB_THRESHOLD` (default 8) incoming clusters | low |

All thresholds are env-driven so deployments can tune without code.

### Schema

```
(:Cluster {repo_id, id, name, file_count, instability, cohesion,
           fan_in, fan_out, computed_at})
(:Cluster)-[:GROUPS]->(:File)
(:Cluster)-[:DEPENDS_ON {weight, cross_file_edges}]->(:Cluster)

(:Warning {repo_id, kind, severity, target_kind, target_id,
           message, detail, computed_at})
```

### API

| Verb | Path | Purpose |
|---|---|---|
| `POST` | `/v1/repos/{id}/architecture` | Queue recompute (async via Celery) |
| `GET`  | `/v1/repos/{id}/architecture` | Cluster nodes + cluster→cluster edges |
| `GET`  | `/v1/repos/{id}/architecture/warnings?severity=high\|medium\|low` | Warnings list |

CLI: `ckg arch compute|show|warnings`. Web UI gets a dedicated page in
the follow-up commit.

## Consequences

Good:
- Re-runnable + idempotent — every ingest can trigger this safely.
- All thresholds env-driven; deployments can re-tune without touching
  code or restarting workers (next run picks up new values).
- Uses only NetworkX — no Neo4j GDS plugin requirement.

Tradeoffs:
- Edge weights inherit CALLS precision from the resolver. Without LSP
  enabled, name-collision false positives inflate fan-in/fan-out and may
  shift cluster boundaries. With LSP turned on, results sharpen.
- Louvain is non-deterministic in the general case; we pass a fixed
  seed so re-runs on the same graph give the same cluster IDs. A
  large delta-ingest can still re-shape clusters, so cluster IDs are
  not stable across ingests — only the snapshot is.
- The IMPORTS-based file→file edge is best-effort. A proper resolver
  that links `:Module` nodes to concrete `:File` targets would tighten
  this; out of scope for this ADR.

## Out of scope (deferred)

- Time-series of warnings across ingests (good for regression
  detection).
- A `policy.yaml` that lets operators ban specific cluster→cluster
  edges (architectural fitness functions).
