"""Structural graph queries (callers/callees/imports/tests_for/impact)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ckg.auth import Principal, require_repo_read
from ckg.db.neo4j import session as neo_session

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/stats")
def graph_stats(_: Principal = Depends(require_repo_read)) -> dict:
    with neo_session() as s:
        nodes = s.run("MATCH (n) RETURN count(n) AS c").single()
        edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
        repos = s.run("MATCH (r:Repo) RETURN count(r) AS c").single()
        files = s.run("MATCH (f:File) RETURN count(f) AS c").single()
        return {
            "nodes": nodes["c"] if nodes else 0,
            "edges": edges["c"] if edges else 0,
            "repos": repos["c"] if repos else 0,
            "files": files["c"] if files else 0,
        }


@router.get("/callers_of")
def callers_of(
    repo_id: str,
    qualified_name: str,
    depth: int = Query(1, ge=1, le=4),
    limit: int = Query(100, ge=1, le=1000),
    _: Principal = Depends(require_repo_read),
) -> dict:
    """Functions that transitively call the given function (up to `depth`)."""
    cy = f"""
        MATCH (target:Function {{repo_id: $rid, qualified_name: $qn}})
        MATCH (caller:Function)-[:CALLS*1..{depth}]->(target)
        RETURN DISTINCT caller.qualified_name AS qn,
                        caller.file_path AS path,
                        caller.start_line AS line
        LIMIT $limit
    """
    with neo_session() as s:
        rows = s.run(cy, rid=repo_id, qn=qualified_name, limit=limit).data()
    return {"target": qualified_name, "depth": depth, "results": rows}


@router.get("/callees_of")
def callees_of(
    repo_id: str,
    qualified_name: str,
    depth: int = Query(1, ge=1, le=4),
    limit: int = Query(100, ge=1, le=1000),
    _: Principal = Depends(require_repo_read),
) -> dict:
    """Functions transitively called by the given function."""
    cy = f"""
        MATCH (source:Function {{repo_id: $rid, qualified_name: $qn}})
        MATCH (source)-[:CALLS*1..{depth}]->(callee:Function)
        RETURN DISTINCT callee.qualified_name AS qn,
                        callee.file_path AS path,
                        callee.start_line AS line
        LIMIT $limit
    """
    with neo_session() as s:
        rows = s.run(cy, rid=repo_id, qn=qualified_name, limit=limit).data()
    return {"source": qualified_name, "depth": depth, "results": rows}


@router.get("/imports_of")
def imports_of(
    repo_id: str,
    path: str,
    limit: int = Query(200, ge=1, le=2000),
    _: Principal = Depends(require_repo_read),
) -> dict:
    cy = """
        MATCH (f:File {repo_id: $rid, path: $path})-[:IMPORTS]->(m)
        RETURN m.name AS name, labels(m) AS labels
        LIMIT $limit
    """
    with neo_session() as s:
        rows = s.run(cy, rid=repo_id, path=path, limit=limit).data()
    return {"file": path, "results": rows}


@router.get("/blast_radius")
def blast_radius(
    repo_id: str,
    path: str,
    depth: int = Query(2, ge=1, le=4),
    limit: int = Query(500, ge=1, le=5000),
    _: Principal = Depends(require_repo_read),
) -> dict:
    """Files that would be affected if this file changes — i.e. the *upstream*
    callers of functions defined here, transitively up to `depth` hops.

    Cypher walks `(target:Function in src)<-[:CALLS*1..N]-(caller:Function)`,
    then reports the files containing those callers. CALLS edges resolved
    name-only (Phase 1) inflate this with false positives; turn on
    `CKG_LSP_ENABLED=true` for precise edges where supported.

    Known gap: this does not yet follow `:IMPORTS` edges. A file that
    imports a class/type defined here but never invokes a function on it
    is not currently counted. Tracked in ADR-0008.
    """
    cy = f"""
        MATCH (src:File {{repo_id: $rid, path: $path}})
        MATCH (src)-[:DEFINES]->(target:Function)<-[:CALLS*1..{depth}]-(caller:Function)
        MATCH (caller_file:File)-[:DEFINES]->(caller)
        WHERE caller_file <> src
        RETURN DISTINCT caller_file.path AS path,
                        caller_file.language AS language
        LIMIT $limit
    """
    with neo_session() as s:
        rows = s.run(cy, rid=repo_id, path=path, limit=limit).data()
    return {"source": path, "depth": depth, "affected_files": rows}


@router.get("/downstream_dependencies")
def downstream_dependencies(
    repo_id: str,
    path: str,
    depth: int = Query(2, ge=1, le=4),
    limit: int = Query(500, ge=1, le=5000),
    _: Principal = Depends(require_repo_read),
) -> dict:
    """The *opposite* of blast radius: files that this file depends on —
    everything reachable from its functions via outgoing CALLS edges, up to
    `depth` hops.

    Useful for "what does this file pull in" / "what would break this file
    if it disappeared". Same precision caveats as blast_radius.
    """
    cy = f"""
        MATCH (src:File {{repo_id: $rid, path: $path}})
        MATCH (src)-[:DEFINES]->(:Function)-[:CALLS*1..{depth}]->(target:Function)
        MATCH (target_file:File)-[:DEFINES]->(target)
        WHERE target_file <> src
        RETURN DISTINCT target_file.path AS path,
                        target_file.language AS language
        LIMIT $limit
    """
    with neo_session() as s:
        rows = s.run(cy, rid=repo_id, path=path, limit=limit).data()
    return {"source": path, "depth": depth, "dependency_files": rows}


@router.get("/file")
def file_overview(
    repo_id: str,
    path: str,
    _: Principal = Depends(require_repo_read),
) -> dict:
    """Symbols defined in a single file."""
    cy = """
        MATCH (f:File {repo_id: $rid, path: $path})
        OPTIONAL MATCH (f)-[:DEFINES]->(c:Class)
        OPTIONAL MATCH (f)-[:DEFINES]->(fn:Function)
        RETURN
          f.language AS language,
          f.size_bytes AS size_bytes,
          collect(DISTINCT { name: c.name, qualified_name: c.qualified_name,
                             start_line: c.start_line, end_line: c.end_line }) AS classes,
          collect(DISTINCT { name: fn.name, qualified_name: fn.qualified_name,
                             start_line: fn.start_line, end_line: fn.end_line,
                             is_async: fn.is_async }) AS functions
    """
    with neo_session() as s:
        row = s.run(cy, rid=repo_id, path=path).single()
    if not row:
        raise HTTPException(404, "file not found in graph")
    return {
        "repo_id": repo_id,
        "path": path,
        **dict(row),
    }
