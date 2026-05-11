"""Repository registration + ingest control."""

from __future__ import annotations

import re
from datetime import datetime

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ckg.auth import Principal, require_repo_read, require_repo_write
from ckg.db.postgres import AuditLog, IngestRun, Repo, get_sessionmaker

router = APIRouter(prefix="/repos", tags=["repos"])

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-_]{0,62}$")


class RepoIn(BaseModel):
    id: str = Field(..., description="Stable slug, e.g. 'submission-enterprise'")
    url: str = Field(..., description="Clone URL (https or ssh). Local path also accepted: file:///abs/path")
    default_branch: str = "main"


class RepoOut(BaseModel):
    id: str
    url: str
    default_branch: str
    languages: list[str]
    last_indexed_at: datetime | None
    last_indexed_sha: str | None


class IngestRunOut(BaseModel):
    id: int
    repo_id: str
    status: str
    mode: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict | None
    error: str | None


def _repo_to_out(r: Repo) -> RepoOut:
    return RepoOut(
        id=r.id,
        url=r.url,
        default_branch=r.default_branch,
        languages=[lang for lang in (r.languages or "").split(",") if lang],
        last_indexed_at=r.last_indexed_at,
        last_indexed_sha=r.last_indexed_sha,
    )


@router.post("", response_model=RepoOut, status_code=status.HTTP_201_CREATED)
def register_repo(body: RepoIn, principal: Principal = Depends(require_repo_write)) -> RepoOut:
    if not _SLUG.match(body.id):
        raise HTTPException(422, "id must be a lowercase slug (a-z, 0-9, -, _)")
    Session = get_sessionmaker()
    with Session() as s:
        if s.get(Repo, body.id):
            raise HTTPException(409, "repo with this id already exists")
        r = Repo(id=body.id, url=body.url, default_branch=body.default_branch)
        s.add(r)
        s.add(AuditLog(actor=principal.name, action="repo.register", target=body.id, detail={"url": body.url}))
        s.commit()
        return _repo_to_out(r)


@router.get("", response_model=list[RepoOut])
def list_repos(_: Principal = Depends(require_repo_read)) -> list[RepoOut]:
    Session = get_sessionmaker()
    with Session() as s:
        rows = s.execute(select(Repo).order_by(Repo.id)).scalars().all()
        return [_repo_to_out(r) for r in rows]


@router.get("/{repo_id}", response_model=RepoOut)
def get_repo(repo_id: str, _: Principal = Depends(require_repo_read)) -> RepoOut:
    Session = get_sessionmaker()
    with Session() as s:
        r = s.get(Repo, repo_id)
        if not r:
            raise HTTPException(404, "repo not found")
        return _repo_to_out(r)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repo(repo_id: str, principal: Principal = Depends(require_repo_write)) -> None:
    """Delete the repo registration AND its graph data."""
    from ckg.db.neo4j import session as neo_session

    Session = get_sessionmaker()
    with Session() as s:
        r = s.get(Repo, repo_id)
        if not r:
            raise HTTPException(404, "repo not found")
        s.delete(r)
        s.add(AuditLog(actor=principal.name, action="repo.delete", target=repo_id))
        s.commit()
    # Best-effort wipe of Neo4j sub-graph for this repo
    try:
        with neo_session() as sess:
            sess.run(
                "MATCH (n) WHERE n.repo_id = $rid DETACH DELETE n",
                rid=repo_id,
            )
    except Exception:
        pass


@router.post("/{repo_id}/ingest", response_model=IngestRunOut, status_code=status.HTTP_202_ACCEPTED)
def trigger_ingest(
    repo_id: str,
    mode: Literal["full", "incremental"] = Query(
        "incremental", description="`incremental` only re-parses files whose sha changed; `full` wipes and re-parses everything."
    ),
    principal: Principal = Depends(require_repo_write),
) -> IngestRunOut:
    """Queue an ingest. Returns the run id immediately."""
    from ckg.worker.celery_app import celery_app  # local import keeps API startup fast

    Session = get_sessionmaker()
    with Session() as s:
        r = s.get(Repo, repo_id)
        if not r:
            raise HTTPException(404, "repo not found")
        # If this is the first ingest for the repo, force a full ingest
        # regardless of caller's request — we have nothing to diff against.
        effective_mode = "full" if r.last_indexed_at is None else mode
        run = IngestRun(repo_id=repo_id, status="queued", mode=effective_mode)
        s.add(run)
        s.add(AuditLog(
            actor=principal.name, action="repo.ingest", target=repo_id,
            detail={"mode": effective_mode, "requested": mode},
        ))
        s.commit()
        s.refresh(run)
        run_id = run.id

    celery_app.send_task("ckg.ingest_repo", args=[repo_id, run_id, effective_mode])

    with Session() as s:
        run = s.get(IngestRun, run_id)
        return IngestRunOut(
            id=run.id, repo_id=run.repo_id, status=run.status, mode=run.mode,
            started_at=run.started_at, finished_at=run.finished_at,
            stats=run.stats, error=run.error,
        )


@router.get("/{repo_id}/runs", response_model=list[IngestRunOut])
def list_runs(repo_id: str, _: Principal = Depends(require_repo_read)) -> list[IngestRunOut]:
    Session = get_sessionmaker()
    with Session() as s:
        runs = s.execute(
            select(IngestRun).where(IngestRun.repo_id == repo_id).order_by(IngestRun.id.desc())
        ).scalars().all()
        return [
            IngestRunOut(
                id=r.id, repo_id=r.repo_id, status=r.status, mode=r.mode,
                started_at=r.started_at, finished_at=r.finished_at,
                stats=r.stats, error=r.error,
            )
            for r in runs
        ]
