"""Periodic scan tasks: find sources / repos due for a refresh and enqueue."""

from __future__ import annotations

from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import select

from ckg.db.postgres import BulkSource, IngestRun, Repo, get_sessionmaker
from ckg.logging import configure_logging, get_logger
from ckg.config import get_settings

configure_logging(get_settings().log_level)
log = get_logger(__name__)


@shared_task(name="ckg.scan_sources_for_sync")
def scan_sources_for_sync() -> dict:
    """For every BulkSource with sync_interval_seconds > 0, enqueue a sync
    when (now - last_synced_at) >= interval."""
    from ckg.worker.celery_app import celery_app

    now = datetime.now(timezone.utc)
    queued: list[int] = []
    Session = get_sessionmaker()
    with Session() as s:
        rows = s.execute(
            select(BulkSource).where(BulkSource.sync_interval_seconds > 0)
        ).scalars().all()
        for row in rows:
            interval = max(60, row.sync_interval_seconds)  # floor: 60s
            last = row.last_synced_at
            if last is None or (now - last).total_seconds() >= interval:
                queued.append(row.id)
    for sid in queued:
        celery_app.send_task("ckg.run_source_sync", args=[sid, "scheduler"])
    log.info("scan_sources", scheduled=len(queued))
    return {"scheduled": queued}


@shared_task(name="ckg.scan_repos_for_poll")
def scan_repos_for_poll() -> dict:
    """For every Repo with poll_interval_seconds > 0, enqueue an incremental
    ingest when (now - last_indexed_at) >= interval."""
    from ckg.worker.celery_app import celery_app

    now = datetime.now(timezone.utc)
    queued: list[str] = []
    Session = get_sessionmaker()
    with Session() as s:
        rows = s.execute(
            select(Repo).where(Repo.poll_interval_seconds > 0)
        ).scalars().all()
        for row in rows:
            interval = max(60, row.poll_interval_seconds)
            last = row.last_indexed_at
            if last is None or (now - last).total_seconds() >= interval:
                # Coerce to full ingest if never indexed before.
                mode = "full" if last is None else "incremental"
                run = IngestRun(repo_id=row.id, status="queued", mode=mode)
                s.add(run)
                s.commit()
                s.refresh(run)
                celery_app.send_task("ckg.ingest_repo", args=[row.id, run.id, mode])
                queued.append(row.id)
    log.info("scan_repos", queued=len(queued))
    return {"queued": queued}


@shared_task(name="ckg.run_source_sync")
def run_source_sync(source_id: int, actor: str = "scheduler") -> dict:
    """Worker-side wrapper around the synchronous sync service so the
    HTTP request returns immediately on scheduled triggers."""
    from ckg.services.sources import sync_source

    try:
        stats = sync_source(source_id, actor=actor)
        return stats.to_dict()
    except Exception as exc:
        log.warning("scheduled_sync_failed", source_id=source_id, error=str(exc))
        raise
