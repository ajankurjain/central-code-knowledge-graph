"""Architecture-map REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ckg.auth import Principal, require_repo_read, require_repo_write
from ckg.db.postgres import AuditLog, Repo, get_sessionmaker
from ckg.services.architecture import (
    get_edge_source,
    list_cluster_edges,
    list_clusters,
    list_warnings,
)

router = APIRouter(prefix="/repos/{repo_id}/architecture", tags=["architecture"])


@router.post("", status_code=status.HTTP_200_OK)
def trigger(repo_id: str, principal: Principal = Depends(require_repo_write)) -> dict:
    """Recompute the architecture map for `repo_id` synchronously.

    Runs in the API process (uvicorn farms sync handlers off to a
    threadpool, so this doesn't block the event loop) instead of
    going through the Celery queue. Previously the task piled up
    behind a backlog of ingest_repo tasks on the same queue and
    could sit unprocessed for minutes — and a UI that polls
    `Computing…` while nothing happens looks broken.
    """
    from ckg.services.architecture import compute_architecture

    Session = get_sessionmaker()
    with Session() as s:
        if not s.get(Repo, repo_id):
            raise HTTPException(404, "repo not found")
        s.add(AuditLog(actor=principal.name, action="arch.compute", target=repo_id))
        s.commit()
    try:
        stats = compute_architecture(repo_id)
    except Exception as exc:
        # Bubble up the actual reason so the UI shows it. 502 because
        # we couldn't talk to / write to Neo4j the way we needed to.
        raise HTTPException(502, f"architecture compute failed: {exc}") from exc
    return {"status": "done", "repo_id": repo_id, **stats.to_dict()}


@router.get("")
def get_map(repo_id: str, _: Principal = Depends(require_repo_read)) -> dict:
    """Cluster nodes + cluster→cluster dependency edges.

    Call POST first if the response is empty — the architecture is computed
    asynchronously by the worker.
    """
    Session = get_sessionmaker()
    with Session() as s:
        if not s.get(Repo, repo_id):
            raise HTTPException(404, "repo not found")
    return {
        "repo_id": repo_id,
        "clusters": list_clusters(repo_id),
        "edges": list_cluster_edges(repo_id),
        # `edge_source` tells the UI whether the clusters came from real
        # call/import signal or from the directory-tree fallback (so it
        # can show a "built from directory layout — call graph was thin"
        # banner instead of pretending the metrics are precise).
        "edge_source": get_edge_source(repo_id),
    }


@router.get("/warnings")
def get_warnings(
    repo_id: str,
    severity: str | None = Query(None, regex="^(high|medium|low)$"),
    _: Principal = Depends(require_repo_read),
) -> dict:
    return {
        "repo_id": repo_id,
        "warnings": list_warnings(repo_id, severity=severity),
    }
