"""Architecture-map REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ckg.auth import Principal, require_repo_read, require_repo_write
from ckg.db.postgres import AuditLog, Repo, get_sessionmaker
from ckg.services.architecture import (
    list_cluster_edges,
    list_clusters,
    list_warnings,
)

router = APIRouter(prefix="/repos/{repo_id}/architecture", tags=["architecture"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def trigger(repo_id: str, principal: Principal = Depends(require_repo_write)) -> dict:
    """Queue an async architecture recompute."""
    from ckg.worker.celery_app import celery_app

    Session = get_sessionmaker()
    with Session() as s:
        if not s.get(Repo, repo_id):
            raise HTTPException(404, "repo not found")
        s.add(AuditLog(actor=principal.name, action="arch.compute", target=repo_id))
        s.commit()
    celery_app.send_task("ckg.compute_architecture", args=[repo_id])
    return {"status": "queued", "repo_id": repo_id}


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
