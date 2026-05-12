"""Auto-generated architecture map + coupling warnings.

Reads the existing CALLS + IMPORTS graph for a repo, builds a file-level
dependency graph, clusters the files into modules via Louvain community
detection (NetworkX), computes per-file and per-cluster coupling
metrics, and writes:

  (:Cluster)        for each module
  (:Cluster)-[:GROUPS]->(:File)
  (:Cluster)-[:DEPENDS_ON]->(:Cluster)  with `weight` and `cross_file_edges`
  (:Warning)        for each design-smell hit

Re-runnable: a fresh run replaces the prior Cluster/Warning nodes for the
repo, so callers can re-trigger after each ingest.

Precision caveat: the file→file edges inherit the precision of the
underlying CALLS resolver. With name-only resolution (default), the
counts are upper bounds. Turn on `CKG_LSP_ENABLED` to tighten.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

import networkx as nx
from networkx.algorithms.community import louvain_communities

from ckg.db.neo4j import session as neo_session
from ckg.logging import get_logger

log = get_logger(__name__)


# Threshold defaults — overridable via env so deployments can tune.
DEFAULT_FAN_IN_THRESHOLD = int(os.environ.get("CKG_ARCH_FAN_IN_THRESHOLD", "20"))
DEFAULT_FAN_OUT_THRESHOLD = int(os.environ.get("CKG_ARCH_FAN_OUT_THRESHOLD", "15"))
DEFAULT_COHESION_FLOOR = float(os.environ.get("CKG_ARCH_COHESION_FLOOR", "0.4"))
DEFAULT_HUB_THRESHOLD = int(os.environ.get("CKG_ARCH_HUB_THRESHOLD", "8"))


@dataclass
class ArchStats:
    repo_id: str
    clusters: int = 0
    files: int = 0
    edges: int = 0
    warnings: int = 0
    warnings_by_kind: dict[str, int] = field(default_factory=dict)
    computed_at: str = ""
    # Diagnostic — explains how we derived the edges so the UI can show
    # something useful when results look thin. One of:
    #   "calls+imports" — primary signal worked
    #   "directory_fallback" — primary was empty, used directory grouping
    #   "no_files"        — no Files in the graph for this repo
    edge_source: str = "calls+imports"

    def to_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "clusters": self.clusters,
            "files": self.files,
            "edges": self.edges,
            "warnings": self.warnings,
            "warnings_by_kind": self.warnings_by_kind,
            "computed_at": self.computed_at,
            "edge_source": self.edge_source,
        }


# Common path prefixes that show up between the repo root and the source
# tree's logical root. Stripping these lets the IMPORTS matcher line up
# Java/Kotlin/Scala packages with their physical file paths.
_LAYOUT_PREFIXES = (
    "src/main/java/",
    "src/main/kotlin/",
    "src/main/scala/",
    "src/main/groovy/",
    "src/test/java/",
    "src/test/kotlin/",
    "src/test/scala/",
    "src/",
    "app/",
    "lib/",
    "pkg/",
    "internal/",
)


# ── Public entrypoint ───────────────────────────────────────────────────────


def compute_architecture(repo_id: str) -> ArchStats:
    log.info("arch_compute_start", repo_id=repo_id)
    edges = _file_dependency_edges(repo_id)
    edge_source = "calls+imports"

    # If the primary signal is too thin to cluster on (very common for
    # Java/Kotlin repos before LSP is on, plus any repo whose parsers
    # don't emit cross-file calls), fall back to a directory-tree edge
    # set so the user still gets a structural map instead of a blank
    # screen. The fallback only kicks in when CALLS+IMPORTS came up
    # essentially empty — never on healthy repos.
    if len(edges) < 2:
        repo_files = _list_repo_files(repo_id)
        if not repo_files:
            _wipe(repo_id)
            log.info("arch_compute_empty", repo_id=repo_id, reason="no_files")
            return ArchStats(
                repo_id=repo_id,
                computed_at=datetime.now(UTC).isoformat(),
                edge_source="no_files",
            )
        edges = _directory_proximity_edges(repo_files)
        edge_source = "directory_fallback"
        log.info(
            "arch_compute_fallback",
            repo_id=repo_id,
            files=len(repo_files),
            edges=len(edges),
        )

    # 1. Build the graphs we need.
    files = set()
    for src, dst, _w in edges:
        files.add(src)
        files.add(dst)
    undirected = _build_undirected(edges)
    directed = _build_directed(edges)

    # 2. Cluster files via Louvain on the undirected weighted graph.
    communities = list(louvain_communities(undirected, weight="weight", seed=42))
    # Stable cluster ids: sorted lexicographically by smallest member path.
    communities.sort(key=lambda c: min(c))
    file_to_cluster = {}
    clusters = []
    for cid, members in enumerate(communities):
        name = _cluster_name(members)
        cluster = {
            "id": cid,
            "name": name,
            "files": sorted(members),
        }
        clusters.append(cluster)
        for f in members:
            file_to_cluster[f] = cid

    # 3. Per-file metrics + per-cluster aggregates.
    file_fanin: dict[str, int] = defaultdict(int)
    file_fanout: dict[str, int] = defaultdict(int)
    seen_pairs: set[tuple[str, str]] = set()
    for src, dst, _w in edges:
        if (src, dst) in seen_pairs:
            continue
        seen_pairs.add((src, dst))
        file_fanout[src] += 1
        file_fanin[dst] += 1

    cluster_metrics: dict[int, dict] = {}
    for cluster in clusters:
        members = set(cluster["files"])
        total_fanin = sum(file_fanin[f] for f in members)
        total_fanout = sum(file_fanout[f] for f in members)
        denom = total_fanin + total_fanout
        instability = (total_fanout / denom) if denom else 0.0

        intra_edges = sum(1 for s, d, _ in edges if s in members and d in members)
        external_edges = sum(1 for s, d, _ in edges if (s in members) ^ (d in members))
        total_edges = intra_edges + external_edges
        cohesion = (intra_edges / total_edges) if total_edges else 1.0

        cluster_metrics[cluster["id"]] = {
            "instability": round(instability, 3),
            "cohesion": round(cohesion, 3),
            "fan_in": total_fanin,
            "fan_out": total_fanout,
        }

    # 4. Cluster→Cluster dependency edges.
    cluster_edges: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: {"weight": 0, "files": 0})
    for src, dst, w in edges:
        cs = file_to_cluster.get(src)
        cd = file_to_cluster.get(dst)
        if cs is None or cd is None or cs == cd:
            continue
        cluster_edges[(cs, cd)]["weight"] += w
        cluster_edges[(cs, cd)]["files"] += 1

    # 5. Warnings.
    warnings = _detect_warnings(
        repo_id=repo_id,
        directed=directed,
        clusters=clusters,
        cluster_metrics=cluster_metrics,
        cluster_edges=cluster_edges,
        file_fanin=file_fanin,
        file_fanout=file_fanout,
    )

    # 6. Persist.
    computed_at = datetime.now(UTC).isoformat()
    _wipe(repo_id)
    _write_clusters(
        repo_id, clusters, cluster_metrics, cluster_edges, computed_at, edge_source,
    )
    _write_warnings(repo_id, warnings, computed_at)

    by_kind: dict[str, int] = defaultdict(int)
    for w in warnings:
        by_kind[w["kind"]] += 1

    stats = ArchStats(
        repo_id=repo_id,
        clusters=len(clusters),
        files=len(files),
        edges=len(edges),
        warnings=len(warnings),
        warnings_by_kind=dict(by_kind),
        computed_at=computed_at,
        edge_source=edge_source,
    )
    log.info("arch_compute_done", **stats.to_dict())
    return stats


# ── Edge extraction from the existing graph ─────────────────────────────────


def _file_dependency_edges(repo_id: str) -> list[tuple[str, str, int]]:
    """File→File edge weight from CALLS (sum of call counts) + IMPORTS.

    IMPORTS today point to Module nodes keyed by the import-string; without
    a resolver we can't link them to a specific File. We pick them up
    in Python by name-stem equality, and in Java/Kotlin/Scala by walking
    a known set of Maven/Gradle layout prefixes off the file path before
    converting / → . to derive the candidate module name. Cross-language
    IMPORTS coverage will keep growing with the resolver work in Phase 3+.
    """
    out: dict[tuple[str, str], int] = defaultdict(int)
    with neo_session() as s:
        # CALLS-derived file→file edges.
        rows = s.run(
            """
            MATCH (a:File {repo_id: $rid})-[:DEFINES]->(:Function)
                  -[:CALLS]->(:Function)<-[:DEFINES]-(b:File {repo_id: $rid})
            WHERE a <> b
            RETURN a.path AS src, b.path AS dst, count(*) AS w
            """,
            rid=repo_id,
        ).data()
        for r in rows:
            out[(r["src"], r["dst"])] += r["w"]

        # IMPORTS-derived edges. We do the path → module candidate set
        # transformation in Python (instead of inline in Cypher) so the
        # Maven/Gradle prefix-stripping logic lives in one place. Cheap:
        # both result sets are small, and the join is a hash.
        imports = s.run(
            """
            MATCH (a:File {repo_id: $rid})-[:IMPORTS]->(m:Module {repo_id: $rid})
            RETURN a.path AS src, m.name AS module
            """,
            rid=repo_id,
        ).data()
        file_rows = s.run(
            """
            MATCH (b:File {repo_id: $rid})
            RETURN b.path AS path
            """,
            rid=repo_id,
        ).data()

        # Build module-candidate → file-path map. A single file can match
        # multiple candidate module names (one per layout prefix), all
        # pointing at the same File.
        module_to_file: dict[str, str] = {}
        for row in file_rows:
            for candidate in _module_candidates(row["path"]):
                module_to_file.setdefault(candidate, row["path"])

        for imp in imports:
            dst = module_to_file.get(imp["module"])
            if dst is None or dst == imp["src"]:
                continue
            out[(imp["src"], dst)] += 1

    return [(s, d, w) for (s, d), w in out.items()]


def _module_candidates(path: str) -> list[str]:
    """Return module-name candidates derived from a file path.

    For `src/main/java/com/foo/Bar.java` we yield:
        com.foo.Bar                 (Java/Kotlin/Scala)
        src.main.java.com.foo.Bar   (legacy / non-Maven layout)
        com/foo/Bar.java            (raw path matches some manifests)
    The first list element is the most likely match; later ones are
    progressively weaker fallbacks. We dedupe on the way out.
    """
    out: list[str] = [path]
    # Strip language extension.
    for ext in (".py", ".java", ".kt", ".kts", ".scala", ".groovy", ".ts", ".tsx", ".js", ".jsx"):
        if path.endswith(ext):
            stem = path[: -len(ext)]
            break
    else:
        stem = path

    # Maven/Gradle / src-rooted layouts. Strip the longest matching prefix
    # first so `src/main/java/...` doesn't shadow `src/...`.
    sorted_prefixes = sorted(_LAYOUT_PREFIXES, key=len, reverse=True)
    for prefix in sorted_prefixes:
        if stem.startswith(prefix):
            rel = stem[len(prefix):]
            out.append(rel.replace("/", "."))
            out.append(rel)  # raw path-without-prefix
            break

    # Universal fallback — works for Python and for any case where the
    # parser stored a name that mirrors the raw repo-relative path.
    out.append(stem.replace("/", "."))
    # Dedupe preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for m in out:
        if m and m not in seen:
            seen.add(m)
            deduped.append(m)
    return deduped


def _list_repo_files(repo_id: str) -> list[str]:
    """All File paths for `repo_id`, used by the directory-proximity
    fallback when CALLS+IMPORTS yields no edges."""
    with neo_session() as s:
        rows = s.run(
            "MATCH (f:File {repo_id: $rid}) RETURN f.path AS path",
            rid=repo_id,
        ).data()
    return [r["path"] for r in rows]


def _directory_proximity_edges(paths: list[str]) -> list[tuple[str, str, int]]:
    """Cluster-by-directory fallback. Adds a weight-1 edge between every
    pair of files that share a parent directory. Louvain on this graph
    yields the directory tree (modulo merges across short directories).
    Always non-empty for any repo with >1 file, so the user gets a
    meaningful structural map even when the call/import signal is thin.
    """
    by_dir: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        # Group by the file's immediate parent directory. Files at the
        # repo root all live in "".
        if "/" in p:
            parent = p.rsplit("/", 1)[0]
        else:
            parent = ""
        by_dir[parent].append(p)
    edges: list[tuple[str, str, int]] = []
    for siblings in by_dir.values():
        if len(siblings) < 2:
            continue
        # Star from the alphabetically-first file outward; an undirected
        # Louvain pass groups them all into one community regardless.
        anchor = siblings[0]
        for other in siblings[1:]:
            edges.append((anchor, other, 1))
    return edges


def _build_undirected(edges) -> nx.Graph:
    g = nx.Graph()
    for src, dst, w in edges:
        if g.has_edge(src, dst):
            g[src][dst]["weight"] += w
        else:
            g.add_edge(src, dst, weight=w)
    return g


def _build_directed(edges) -> nx.DiGraph:
    g = nx.DiGraph()
    for src, dst, w in edges:
        if g.has_edge(src, dst):
            g[src][dst]["weight"] += w
        else:
            g.add_edge(src, dst, weight=w)
    return g


# ── Cluster naming ─────────────────────────────────────────────────────────


def _cluster_name(members: set[str]) -> str:
    """Pick the longest common path prefix as the cluster name. Falls back
    to a representative member when no prefix is shared."""
    if not members:
        return "(empty)"
    paths = sorted(p.split("/") for p in members)
    first, last = paths[0], paths[-1]
    common: list[str] = []
    for a, b in zip(first, last, strict=False):
        if a == b:
            common.append(a)
        else:
            break
    if common:
        return "/".join(common)
    # Fallback: shortest member
    return min(members, key=len)


# ── Warnings ───────────────────────────────────────────────────────────────


def _detect_warnings(
    *,
    repo_id: str,
    directed: nx.DiGraph,
    clusters: list[dict],
    cluster_metrics: dict[int, dict],
    cluster_edges: dict[tuple[int, int], dict[str, int]],
    file_fanin: dict[str, int],
    file_fanout: dict[str, int],
) -> list[dict]:
    warnings: list[dict] = []

    # 1. Cyclic dependencies — SCCs > 1 in the file graph
    for scc in nx.strongly_connected_components(directed):
        if len(scc) > 1:
            cycle = sorted(scc)
            warnings.append({
                "kind": "cyclic_dependency",
                "severity": "high",
                "target_kind": "file_group",
                "target_id": cycle[0],
                "message": f"{len(cycle)} files form a dependency cycle.",
                "detail": {"files": cycle},
            })

    # 2. High fan-in (god module)
    for f, fin in file_fanin.items():
        if fin > DEFAULT_FAN_IN_THRESHOLD:
            warnings.append({
                "kind": "high_fan_in",
                "severity": "medium",
                "target_kind": "file",
                "target_id": f,
                "message": f"{f} has fan-in {fin} (threshold {DEFAULT_FAN_IN_THRESHOLD}); changes here have a large blast radius.",
                "detail": {"fan_in": fin, "threshold": DEFAULT_FAN_IN_THRESHOLD},
            })

    # 3. High fan-out (kitchen sink)
    for f, fout in file_fanout.items():
        if fout > DEFAULT_FAN_OUT_THRESHOLD:
            warnings.append({
                "kind": "high_fan_out",
                "severity": "medium",
                "target_kind": "file",
                "target_id": f,
                "message": f"{f} depends on {fout} other files (threshold {DEFAULT_FAN_OUT_THRESHOLD}); hard to test in isolation.",
                "detail": {"fan_out": fout, "threshold": DEFAULT_FAN_OUT_THRESHOLD},
            })

    # 4. Low cohesion per cluster
    for c in clusters:
        m = cluster_metrics[c["id"]]
        if m["cohesion"] < DEFAULT_COHESION_FLOOR and len(c["files"]) > 1:
            warnings.append({
                "kind": "low_cohesion",
                "severity": "low",
                "target_kind": "cluster",
                "target_id": str(c["id"]),
                "message": f"Cluster '{c['name']}' has cohesion {m['cohesion']} (< {DEFAULT_COHESION_FLOOR}); membership may be incidental.",
                "detail": {"cluster_id": c["id"], "cohesion": m["cohesion"], "files": c["files"]},
            })

    # 5. Stable-Dependencies-Principle violations:
    #    A → B but A is more stable (lower instability) than B.
    for (src_id, dst_id), payload in cluster_edges.items():
        i_src = cluster_metrics[src_id]["instability"]
        i_dst = cluster_metrics[dst_id]["instability"]
        # Only flag when the diff is meaningful (avoid noise on near-equal values)
        if i_src + 0.1 < i_dst:
            src_name = clusters[src_id]["name"]
            dst_name = clusters[dst_id]["name"]
            warnings.append({
                "kind": "sdp_violation",
                "severity": "medium",
                "target_kind": "cluster_edge",
                "target_id": f"{src_id}->{dst_id}",
                "message": (
                    f"Cluster '{src_name}' (I={i_src}) depends on '{dst_name}' (I={i_dst}); "
                    "a stable module depending on a less-stable one violates SDP."
                ),
                "detail": {
                    "source_cluster": src_id, "target_cluster": dst_id,
                    "source_instability": i_src, "target_instability": i_dst,
                    "weight": payload["weight"],
                },
            })

    # 6. Hub clusters — many incoming cluster edges
    in_degree: dict[int, int] = defaultdict(int)
    for (_src, dst), _payload in cluster_edges.items():
        in_degree[dst] += 1
    for cid, deg in in_degree.items():
        if deg > DEFAULT_HUB_THRESHOLD:
            warnings.append({
                "kind": "hub_cluster",
                "severity": "low",
                "target_kind": "cluster",
                "target_id": str(cid),
                "message": (
                    f"Cluster '{clusters[cid]['name']}' is a hub — depended on by {deg} other clusters."
                ),
                "detail": {"cluster_id": cid, "incoming_clusters": deg},
            })

    return warnings


# ── Persistence ─────────────────────────────────────────────────────────────


def _wipe(repo_id: str) -> None:
    with neo_session() as s:
        s.run(
            "MATCH (cl:Cluster {repo_id: $rid}) DETACH DELETE cl",
            rid=repo_id,
        )
        s.run(
            "MATCH (w:Warning {repo_id: $rid}) DETACH DELETE w",
            rid=repo_id,
        )


def _write_clusters(
    repo_id: str,
    clusters: list[dict],
    metrics: dict[int, dict],
    cluster_edges: dict[tuple[int, int], dict[str, int]],
    computed_at: str,
    edge_source: str = "calls+imports",
) -> None:
    cluster_rows = [
        {
            "id": c["id"],
            "name": c["name"],
            "file_count": len(c["files"]),
            "instability": metrics[c["id"]]["instability"],
            "cohesion": metrics[c["id"]]["cohesion"],
            "fan_in": metrics[c["id"]]["fan_in"],
            "fan_out": metrics[c["id"]]["fan_out"],
        }
        for c in clusters
    ]
    membership_rows = [
        {"id": c["id"], "path": p}
        for c in clusters
        for p in c["files"]
    ]
    edge_rows = [
        {"src": src, "dst": dst, "weight": payload["weight"], "cross_file_edges": payload["files"]}
        for (src, dst), payload in cluster_edges.items()
    ]

    with neo_session() as s:
        s.run(
            """
            UNWIND $rows AS row
            MERGE (cl:Cluster {repo_id: $rid, id: row.id})
              SET cl.name = row.name,
                  cl.file_count = row.file_count,
                  cl.instability = row.instability,
                  cl.cohesion = row.cohesion,
                  cl.fan_in = row.fan_in,
                  cl.fan_out = row.fan_out,
                  cl.computed_at = $computed_at,
                  cl.edge_source = $edge_source
            """,
            rid=repo_id, rows=cluster_rows, computed_at=computed_at,
            edge_source=edge_source,
        )
        if membership_rows:
            s.run(
                """
                UNWIND $rows AS row
                MATCH (cl:Cluster {repo_id: $rid, id: row.id})
                MATCH (f:File {repo_id: $rid, path: row.path})
                MERGE (cl)-[:GROUPS]->(f)
                """,
                rid=repo_id, rows=membership_rows,
            )
        if edge_rows:
            s.run(
                """
                UNWIND $rows AS row
                MATCH (a:Cluster {repo_id: $rid, id: row.src})
                MATCH (b:Cluster {repo_id: $rid, id: row.dst})
                MERGE (a)-[r:DEPENDS_ON]->(b)
                  SET r.weight = row.weight,
                      r.cross_file_edges = row.cross_file_edges
                """,
                rid=repo_id, rows=edge_rows,
            )


def _write_warnings(repo_id: str, warnings: list[dict], computed_at: str) -> None:
    if not warnings:
        return
    # Neo4j only allows primitive properties (or arrays of primitives) — a
    # nested map like {"files": [...]} or {"cluster_id": 0, "files": [...]}
    # rejects with a CypherTypeError. JSON-encode the detail payload so the
    # full structure survives the round-trip; the read side decodes it back.
    import json as _json

    rows = [
        {
            "kind": w["kind"],
            "severity": w["severity"],
            "target_kind": w["target_kind"],
            "target_id": w["target_id"],
            "message": w["message"],
            "detail_json": _json.dumps(w.get("detail") or {}, default=str),
        }
        for w in warnings
    ]
    with neo_session() as s:
        s.run(
            """
            UNWIND $rows AS row
            MERGE (w:Warning {
              repo_id: $rid, kind: row.kind,
              target_kind: row.target_kind, target_id: row.target_id
            })
              SET w.severity = row.severity,
                  w.message = row.message,
                  w.detail_json = row.detail_json,
                  w.computed_at = $computed_at
            """,
            rid=repo_id, rows=rows, computed_at=computed_at,
        )


# ── Read-side helpers used by the API layer ─────────────────────────────────


def list_clusters(repo_id: str) -> list[dict]:
    with neo_session() as s:
        rows = s.run(
            """
            MATCH (cl:Cluster {repo_id: $rid})
            OPTIONAL MATCH (cl)-[:GROUPS]->(f:File)
            RETURN cl.id AS id, cl.name AS name,
                   cl.file_count AS file_count,
                   cl.instability AS instability,
                   cl.cohesion AS cohesion,
                   cl.fan_in AS fan_in, cl.fan_out AS fan_out,
                   cl.computed_at AS computed_at,
                   collect(f.path) AS files
            ORDER BY cl.id
            """,
            rid=repo_id,
        ).data()
    return [
        {
            "id": r["id"], "name": r["name"], "file_count": r["file_count"],
            "instability": r["instability"], "cohesion": r["cohesion"],
            "fan_in": r["fan_in"], "fan_out": r["fan_out"],
            "computed_at": r["computed_at"],
            "files": [f for f in r["files"] if f],
        }
        for r in rows
    ]


def get_edge_source(repo_id: str) -> str | None:
    """Returns `edge_source` from any one Cluster of this repo (all Clusters
    in a single compute share it). Used by the GET endpoint so the UI can
    explain which signal the map was built from."""
    with neo_session() as s:
        row = s.run(
            """
            MATCH (cl:Cluster {repo_id: $rid})
            RETURN cl.edge_source AS edge_source
            LIMIT 1
            """,
            rid=repo_id,
        ).single()
    return row["edge_source"] if row else None


def list_cluster_edges(repo_id: str) -> list[dict]:
    with neo_session() as s:
        rows = s.run(
            """
            MATCH (a:Cluster {repo_id: $rid})-[r:DEPENDS_ON]->(b:Cluster {repo_id: $rid})
            RETURN a.id AS source, b.id AS target, r.weight AS weight,
                   r.cross_file_edges AS cross_file_edges
            """,
            rid=repo_id,
        ).data()
    return rows


def list_warnings(repo_id: str, severity: str | None = None) -> list[dict]:
    """Read warnings back, decoding the JSON-encoded `detail_json` property
    so callers see the original nested-dict shape."""
    import json as _json

    where = "WHERE w.severity = $sev" if severity else ""
    cy = f"""
        MATCH (w:Warning {{repo_id: $rid}})
        {where}
        RETURN w.kind AS kind, w.severity AS severity,
               w.target_kind AS target_kind, w.target_id AS target_id,
               w.message AS message,
               w.detail_json AS detail_json,
               w.computed_at AS computed_at
        ORDER BY w.severity, w.kind, w.target_id
    """
    params = {"rid": repo_id}
    if severity:
        params["sev"] = severity
    with neo_session() as s:
        rows = s.run(cy, **params).data()
    for r in rows:
        raw = r.pop("detail_json", None)
        try:
            r["detail"] = _json.loads(raw) if raw else {}
        except Exception:
            r["detail"] = {}
    return rows
