"""Bulk-source REST endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ckg.auth import Principal, require_admin, require_repo_read, require_repo_write
from ckg.db.postgres import BulkSource, SourceRepo, get_sessionmaker
from ckg.services import webhooks as wh
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
    sync_interval_seconds: int = 0
    webhook_enabled: bool = False


class SourceSchedule(BaseModel):
    sync_interval_seconds: int = Field(0, ge=0)


class WebhookConfig(BaseModel):
    enabled: bool = True
    rotate_secret: bool = False


class WebhookInfo(BaseModel):
    enabled: bool
    secret: str | None
    receiver_url_template: str = "POST {origin}/v1/webhooks/{source_id}"


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
        sync_interval_seconds=row.sync_interval_seconds or 0,
        webhook_enabled=bool(row.webhook_enabled and row.webhook_secret),
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


@router.put("/{source_id}/schedule", response_model=SourceOut)
def set_schedule(
    source_id: int,
    body: SourceSchedule,
    _: Principal = Depends(require_repo_write),
) -> SourceOut:
    """Set per-source polling interval (seconds). 0 disables.

    Min floor enforced by the scheduler is 60s — values below that are
    promoted at run time."""
    Session = get_sessionmaker()
    with Session() as s:
        row = s.get(BulkSource, source_id)
        if not row:
            raise HTTPException(404, "source not found")
        row.sync_interval_seconds = max(0, int(body.sync_interval_seconds))
        s.commit()
        count = s.execute(select(SourceRepo).where(SourceRepo.source_id == source_id)).scalars().all()
        return _to_out(row, repo_count=len(count))


@router.put("/{source_id}/webhook", response_model=WebhookInfo)
def configure_webhook(
    source_id: int,
    body: WebhookConfig,
    _: Principal = Depends(require_repo_write),
) -> WebhookInfo:
    """Enable / disable / rotate the inbound webhook for this source.

    Returns the plaintext secret — paste it into the upstream provider's
    webhook config. Keep this response audience-restricted."""
    Session = get_sessionmaker()
    with Session() as s:
        row = s.get(BulkSource, source_id)
        if not row:
            raise HTTPException(404, "source not found")
        if body.enabled:
            if body.rotate_secret or not row.webhook_secret:
                row.webhook_secret = wh.new_secret()
            row.webhook_enabled = True
        else:
            row.webhook_enabled = False
        s.commit()
        return WebhookInfo(
            enabled=row.webhook_enabled,
            secret=row.webhook_secret if row.webhook_enabled else None,
        )


@router.get("/{source_id}/webhook", response_model=WebhookInfo)
def get_webhook(source_id: int, _: Principal = Depends(require_repo_write)) -> WebhookInfo:
    Session = get_sessionmaker()
    with Session() as s:
        row = s.get(BulkSource, source_id)
        if not row:
            raise HTTPException(404, "source not found")
        return WebhookInfo(
            enabled=bool(row.webhook_enabled and row.webhook_secret),
            secret=row.webhook_secret if row.webhook_enabled else None,
        )
