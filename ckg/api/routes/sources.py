"""Bulk-source REST endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ckg.auth import Principal, require_admin, require_repo_read, require_repo_write
from ckg.db.postgres import BulkSource, SourceRepo, get_sessionmaker
from ckg.services.sources import (
    CreateSourceInput,
    SyncStats,
    create_source,
    delete_source,
    sync_source,
)
from ckg.sources.detect import detect_source_kind
from ckg.sources.registry import known_kinds

router = APIRouter(prefix="/sources", tags=["sources"])


# ── Request / response shapes ───────────────────────────────────────────────


class SourceCreate(BaseModel):
    url: str = Field(..., description="The public URL (we auto-detect provider) OR `kind:name`.")
    kind: str | None = Field(None, description="Override auto-detection.")
    name: str | None = Field(None, description="Override auto-detection.")
    token: str | None = Field(None, description="PAT for private repos / higher rate limits.")
    include_private: bool = True
    include_forks: bool = False
    include_archived: bool = False
    default_branch_override: str | None = None
    slug_template: str = "{owner}-{name}"
    sync_now: bool = True


class SourceOut(BaseModel):
    id: int
    kind: str
    name: str
    url: str | None
    include_private: bool
    include_forks: bool
    include_archived: bool
    slug_template: str
    default_branch_override: str | None
    last_synced_at: datetime | None
    last_sync_stats: dict | None
    has_token: bool
    repos: int


class SourceRepoOut(BaseModel):
    repo_id: str
    full_name: str
    default_branch: str
    private: bool
    archived: bool
    fork: bool


# ── Helpers ─────────────────────────────────────────────────────────────────


def _to_out(row: BulkSource, repo_count: int) -> SourceOut:
    return SourceOut(
        id=row.id, kind=row.kind, name=row.name, url=row.url,
        include_private=row.include_private,
        include_forks=row.include_forks,
        include_archived=row.include_archived,
        slug_template=row.slug_template,
        default_branch_override=row.default_branch_override,
        last_synced_at=row.last_synced_at,
        last_sync_stats=row.last_sync_stats,
        has_token=bool(row.auth_secret),
        repos=repo_count,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/kinds")
def list_kinds(_: Principal = Depends(require_repo_read)) -> dict:
    return {"kinds": known_kinds()}


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def register(body: SourceCreate, principal: Principal = Depends(require_repo_write)) -> SourceOut:
    if body.kind and body.name:
        kind, name = body.kind, body.name
        original_url = body.url
    else:
        try:
            kind, name = detect_source_kind(body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        original_url = body.url

    src_id = create_source(
        CreateSourceInput(
            kind=kind, name=name, token=body.token, url=original_url,
            include_private=body.include_private,
            include_forks=body.include_forks,
            include_archived=body.include_archived,
            default_branch_override=body.default_branch_override,
            slug_template=body.slug_template,
        ),
        actor=principal.name,
    )
    Session = get_sessionmaker()
    with Session() as s:
        row = s.get(BulkSource, src_id)
        if row is None:
            raise HTTPException(500, "source creation race")
        out = _to_out(row, repo_count=0)

    if body.sync_now:
        # Run synchronously so the caller sees discovered counts in the response.
        try:
            stats = sync_source(src_id, actor=principal.name)
            out.last_sync_stats = stats.to_dict()
            out.repos = stats.added + stats.already
        except Exception as exc:
            raise HTTPException(502, f"sync failed: {exc}") from exc
    return out


@router.get("", response_model=list[SourceOut])
def list_sources(_: Principal = Depends(require_repo_read)) -> list[SourceOut]:
    Session = get_sessionmaker()
    with Session() as s:
        rows = s.execute(select(BulkSource).order_by(BulkSource.id)).scalars().all()
        out: list[SourceOut] = []
        for r in rows:
            count = s.execute(
                select(SourceRepo).where(SourceRepo.source_id == r.id)
            ).scalars().all()
            out.append(_to_out(r, repo_count=len(count)))
        return out


@router.get("/{source_id}", response_model=SourceOut)
def get_source(source_id: int, _: Principal = Depends(require_repo_read)) -> SourceOut:
    Session = get_sessionmaker()
    with Session() as s:
        row = s.get(BulkSource, source_id)
        if not row:
            raise HTTPException(404, "source not found")
        count = s.execute(
            select(SourceRepo).where(SourceRepo.source_id == source_id)
        ).scalars().all()
        return _to_out(row, repo_count=len(count))


@router.get("/{source_id}/repos", response_model=list[SourceRepoOut])
def list_source_repos(source_id: int, _: Principal = Depends(require_repo_read)) -> list[SourceRepoOut]:
    Session = get_sessionmaker()
    with Session() as s:
        rows = s.execute(
            select(SourceRepo).where(SourceRepo.source_id == source_id).order_by(SourceRepo.full_name)
        ).scalars().all()
        return [
            SourceRepoOut(
                repo_id=r.repo_id, full_name=r.full_name, default_branch=r.default_branch,
                private=r.private, archived=r.archived, fork=r.fork,
            )
            for r in rows
        ]


@router.post("/{source_id}/sync")
def trigger_sync(source_id: int, principal: Principal = Depends(require_repo_write)) -> dict:
    try:
        stats: SyncStats = sync_source(source_id, actor=principal.name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return stats.to_dict()


@router.delete("/{source_id}")
def delete(source_id: int, principal: Principal = Depends(require_admin)) -> dict:
    try:
        return delete_source(source_id, actor=principal.name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
