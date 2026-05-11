"""Async ingest task — clones (or pulls) the repo and writes the graph."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from celery import shared_task

from ckg.config import get_settings
from ckg.db.postgres import IngestRun, Repo, get_sessionmaker
from ckg.logging import configure_logging, get_logger
from ckg.services.ingest import IngestMode, IngestStats
from ckg.services.ingest import ingest_repo as _ingest_repo

configure_logging(get_settings().log_level)
log = get_logger(__name__)


@shared_task(name="ckg.ingest_repo", bind=True, max_retries=2)
def ingest_repo(self, repo_id: str, run_id: int, mode: str = "full") -> dict:
    """Clone / refresh the repo and write its graph to Neo4j."""
    Session = get_sessionmaker()
    with Session() as s:
        repo = s.get(Repo, repo_id)
        run = s.get(IngestRun, run_id)
        if not repo or not run:
            log.warning("ingest_no_repo_or_run", repo_id=repo_id, run_id=run_id)
            return {"status": "missing"}
        run.status = "running"
        run.mode = mode
        run.started_at = datetime.now(UTC)
        s.commit()
        url = repo.url
        branch = repo.default_branch

    s_settings = get_settings()
    workdir = Path(s_settings.repo_root) / repo_id

    try:
        m: IngestMode = "incremental" if mode == "incremental" else "full"
        stats: IngestStats = _ingest_repo(
            repo_id=repo_id, url=url, branch=branch, workdir=workdir, mode=m,
        )
        with Session() as s:
            run = s.get(IngestRun, run_id)
            repo = s.get(Repo, repo_id)
            if run is not None:
                run.status = "success"
                run.finished_at = datetime.now(UTC)
                run.stats = stats.to_dict()
            if repo is not None:
                repo.last_indexed_at = datetime.now(UTC)
                repo.last_indexed_sha = stats.head_sha
                repo.languages = ",".join(sorted(stats.languages))
            s.commit()
        log.info("ingest_done", repo_id=repo_id, **stats.to_dict())
        return stats.to_dict()
    except Exception as exc:
        log.exception("ingest_failed", repo_id=repo_id)
        with Session() as s:
            run = s.get(IngestRun, run_id)
            if run is not None:
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
                run.error = str(exc)[:1900]
                s.commit()
        # Retry transient failures (network, etc.)
        raise self.retry(exc=exc, countdown=30) from exc


@shared_task(name="ckg.compute_architecture")
def compute_architecture_task(repo_id: str) -> dict:
    """Build the cluster map + warnings for `repo_id`. Idempotent — replaces
    prior Cluster/Warning nodes for the repo on each run."""
    from ckg.services.architecture import compute_architecture

    try:
        stats = compute_architecture(repo_id)
        return stats.to_dict()
    except Exception as exc:
        log.exception("arch_failed", repo_id=repo_id, error=str(exc))
        raise
