"""Keyword + semantic search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ckg.auth import Principal, require_repo_read
from ckg.db.neo4j import session as neo_session

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/keyword")
def keyword_search(
    q: str = Query(..., min_length=1),
    repo_id: str | None = Query(None),
    limit: int = Query(25, ge=1, le=200),
    _: Principal = Depends(require_repo_read),
) -> dict:
    """Lucene full-text search across function/class names + docs."""
    where = "WHERE node.repo_id = $rid" if repo_id else ""
    cy = f"""
        CALL db.index.fulltext.queryNodes('fn_text', $q) YIELD node, score
        {where}
        RETURN node.repo_id AS repo_id,
               node.qualified_name AS qualified_name,
               node.file_path AS path,
               node.start_line AS line,
               labels(node)[0] AS kind,
               score
        ORDER BY score DESC
        LIMIT $limit
    """
    params = {"q": q, "limit": limit}
    if repo_id:
        params["rid"] = repo_id
    with neo_session() as s:
        rows = s.run(cy, **params).data()
    return {"query": q, "results": rows}


@router.get("/semantic")
def semantic_search(
    q: str = Query(..., min_length=1),
    repo_id: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
    _: Principal = Depends(require_repo_read),
) -> dict:
    """Vector search over function embeddings."""
    from ckg.services.embeddings import embed_text  # lazy: model load is heavy

    vec = embed_text(q).tolist()
    where = "WHERE node.repo_id = $rid" if repo_id else ""
    cy = f"""
        CALL db.index.vector.queryNodes('function_embedding', $limit, $vec)
        YIELD node, score
        {where}
        RETURN node.repo_id AS repo_id,
               node.qualified_name AS qualified_name,
               node.file_path AS path,
               node.start_line AS line,
               score
        ORDER BY score DESC
    """
    params = {"vec": vec, "limit": limit}
    if repo_id:
        params["rid"] = repo_id
    with neo_session() as s:
        rows = s.run(cy, **params).data()
    return {"query": q, "results": rows}
