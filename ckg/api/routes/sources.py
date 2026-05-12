"""Bulk-source REST endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from ckg.auth import Principal, require_admin, require_repo_read, require_repo_write
from ckg.db.postgres import BulkSource, Repo, SourceRepo, get_sessionmaker
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


class SourceBranchOverride(BaseModel):
    """Body for `PUT /sources/{id}/branch`. Empty string clears the override
    (each discovered repo then falls back to its provider-reported default).
    """

    default_branch_override: str = Field("", max_length=200)


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


class SourceProgress(BaseModel):
    """Live ingest progress for every repo this source produced.

    Counts are computed from the LATEST `ingest_runs` row per repo plus the
    `repos.last_indexed_at` flag — so a repo whose latest run failed but was
    indexed previously still counts as `indexed`. UI uses this to render a
    progress bar that auto-refreshes while `in_progress` is true.
    """

    source_id: int
    total: int
    indexed: int
    queued: int
    running: int
    success: int
    failed: int
    unstarted: int
    in_progress: bool
    last_run_at: datetime | None
    last_synced_at: datetime | None
    # When any latest-run is `failed`, surface up to N representative error
    # messages so the operator sees the actual cause (e.g. "Branch 'main'
    # has no source files…"). Empty list when nothing is failed.
    recent_failures: list[dict] = []


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


@router.get("/{source_id}/progress", response_model=SourceProgress)
def source_progress(
    source_id: int,
    _: Principal = Depends(require_repo_read),
) -> SourceProgress:
    """Aggregate ingest progress for every repo this source produced.

    Polled by the UI while a sync is in flight. Cheap: one indexed
    aggregation over `ingest_runs` plus a count over `repos`.
    """
    Session = get_sessionmaker()
    with Session() as s:
        source = s.get(BulkSource, source_id)
        if not source:
            raise HTTPException(404, "source not found")

        # Total + indexed counts from the canonical `repos` table — this is
        # the source of truth for "has this repo ever been indexed".
        total = s.execute(
            select(Repo).where(Repo.source_id == source_id)
        ).scalars().all()
        total_count = len(total)
        indexed_count = sum(1 for r in total if r.last_indexed_at is not None)

        # Latest run per repo (status snapshot). `DISTINCT ON` keeps Postgres
        # happy on a single index scan over (repo_id, id DESC).
        latest_rows = s.execute(
            text(
                """
                SELECT DISTINCT ON (ir.repo_id)
                    ir.repo_id,
                    ir.status,
                    ir.started_at,
                    ir.finished_at
                FROM ingest_runs ir
                JOIN repos r ON r.id = ir.repo_id
                WHERE r.source_id = :sid
                ORDER BY ir.repo_id, ir.id DESC
                """
            ),
            {"sid": source_id},
        ).all()

        queued = running = success = failed = 0
        last_run_at: datetime | None = None
        for row in latest_rows:
            status_ = row.status
            if status_ == "queued":
                queued += 1
            elif status_ == "running":
                running += 1
            elif status_ == "success":
                success += 1
            elif status_ == "failed":
                failed += 1
            ts = row.finished_at or row.started_at
            if ts is not None and (last_run_at is None or ts > last_run_at):
                last_run_at = ts

        unstarted = max(0, total_count - len(latest_rows))
        in_progress = queued > 0 or running > 0

        # Up to 5 representative latest-failed runs with their error text so
        # the operator sees what's actually wrong (wrong branch, auth, …)
        # instead of just a red bar with a count.
        recent_failures: list[dict] = []
        if failed > 0:
            fail_rows = s.execute(
                text(
                    """
                    SELECT DISTINCT ON (ir.repo_id)
                        ir.repo_id, ir.error, ir.finished_at
                    FROM ingest_runs ir
                    JOIN repos r ON r.id = ir.repo_id
                    WHERE r.source_id = :sid
                    ORDER BY ir.repo_id, ir.id DESC
                    """
                ),
                {"sid": source_id},
            ).all()
            failed_only = [
                {
                    "repo_id": row.repo_id,
                    "error": (row.error or "").strip()[:400],
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                }
                for row in fail_rows
                if (row.error or "").strip()
            ]
            # Newest first.
            failed_only.sort(key=lambda f: f["finished_at"] or "", reverse=True)
            recent_failures = failed_only[:5]

        return SourceProgress(
            source_id=source_id,
            total=total_count,
            indexed=indexed_count,
            queued=queued,
            running=running,
            success=success,
            failed=failed,
            unstarted=unstarted,
            in_progress=in_progress,
            last_run_at=last_run_at,
            last_synced_at=source.last_synced_at,
            recent_failures=recent_failures,
        )


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


@router.put("/{source_id}/branch", response_model=SourceOut)
def set_branch_override(
    source_id: int,
    body: SourceBranchOverride,
    _: Principal = Depends(require_repo_write),
) -> SourceOut:
    """Change the per-source branch override applied to every newly-
    discovered repo on the next sync. Existing repos keep their
    per-row `default_branch` (operator can change that on the repo
    page) — the override only takes effect for repos discovered after
    this call.
    """
    Session = get_sessionmaker()
    with Session() as s:
        row = s.get(BulkSource, source_id)
        if not row:
            raise HTTPException(404, "source not found")
        new_value = body.default_branch_override.strip() or None
        row.default_branch_override = new_value
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
