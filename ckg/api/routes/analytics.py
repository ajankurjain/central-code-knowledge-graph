"""Aggregate analytics for the dashboard + /integrations page.

Single endpoint that joins counts across Postgres + Neo4j so the UI
doesn't have to fan out to five separate endpoints to render a summary.
Keeping it small and dependency-free — every query here is indexed and
read-only.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text

from ckg.auth import Principal, require_repo_read
from ckg.db.postgres import (
    ApiToken,
    BulkSource,
    IngestRun,
    Repo,
    get_sessionmaker,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


class CountByKey(BaseModel):
    key: str
    value: int


class SourcesAnalytics(BaseModel):
    total: int
    by_kind: list[CountByKey]
    with_webhook: int
    with_schedule: int
    last_synced_at: datetime | None


class TokensAnalytics(BaseModel):
    total: int
    active: int
    revoked: int
    used_in_last_24h: int
    most_recent_use: datetime | None


class ReposAnalytics(BaseModel):
    total: int
    indexed: int
    by_language: list[CountByKey]
    most_recent_index: datetime | None


class IngestAnalytics(BaseModel):
    last_24h_total: int
    last_24h_success: int
    last_24h_failed: int
    success_rate_pct: float
    queue_depth: int  # latest-runs in queued status
    recent_failures: list[dict]


class IntegrationsSummary(BaseModel):
    """One-shot payload for the dedicated `/integrations` page."""

    sources: SourcesAnalytics
    tokens: TokensAnalytics
    repos: ReposAnalytics
    ingests: IngestAnalytics


@router.get("/summary", response_model=IntegrationsSummary)
def summary(_: Principal = Depends(require_repo_read)) -> IntegrationsSummary:
    Session = get_sessionmaker()
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)

    with Session() as s:
        # ── Sources ────────────────────────────────────────────────────
        all_sources = s.execute(select(BulkSource)).scalars().all()
        kind_counts = Counter(b.kind for b in all_sources)
        sources_payload = SourcesAnalytics(
            total=len(all_sources),
            by_kind=[CountByKey(key=k, value=v) for k, v in sorted(kind_counts.items())],
            with_webhook=sum(
                1 for b in all_sources if b.webhook_enabled and b.webhook_secret
            ),
            with_schedule=sum(1 for b in all_sources if (b.sync_interval_seconds or 0) > 0),
            last_synced_at=max(
                (b.last_synced_at for b in all_sources if b.last_synced_at),
                default=None,
            ),
        )

        # ── API tokens ────────────────────────────────────────────────
        all_tokens = s.execute(select(ApiToken)).scalars().all()
        used_recent = sum(
            1
            for t in all_tokens
            if t.last_used_at is not None and t.last_used_at >= day_ago
        )
        tokens_payload = TokensAnalytics(
            total=len(all_tokens),
            active=sum(1 for t in all_tokens if not t.revoked),
            revoked=sum(1 for t in all_tokens if t.revoked),
            used_in_last_24h=used_recent,
            most_recent_use=max(
                (t.last_used_at for t in all_tokens if t.last_used_at),
                default=None,
            ),
        )

        # ── Repos + language histogram ────────────────────────────────
        repo_rows = s.execute(select(Repo)).scalars().all()
        lang_counter: Counter[str] = Counter()
        for r in repo_rows:
            for lang in (r.languages or "").split(","):
                lang = lang.strip()
                if lang:
                    lang_counter[lang] += 1
        repos_payload = ReposAnalytics(
            total=len(repo_rows),
            indexed=sum(1 for r in repo_rows if r.last_indexed_at is not None),
            by_language=[
                CountByKey(key=lang, value=cnt)
                for lang, cnt in lang_counter.most_common()
            ],
            most_recent_index=max(
                (r.last_indexed_at for r in repo_rows if r.last_indexed_at),
                default=None,
            ),
        )

        # ── Ingest activity (last 24h totals + queue depth) ────────────
        c_total = s.execute(
            select(func.count(IngestRun.id)).where(IngestRun.started_at >= day_ago)
        ).scalar_one()
        c_succ = s.execute(
            select(func.count(IngestRun.id)).where(
                IngestRun.started_at >= day_ago, IngestRun.status == "success",
            )
        ).scalar_one()
        c_fail = s.execute(
            select(func.count(IngestRun.id)).where(
                IngestRun.started_at >= day_ago, IngestRun.status == "failed",
            )
        ).scalar_one()
        # `queue_depth` = repos whose LATEST run is currently `queued`. This
        # is what "pending work" actually means; counting every historical
        # queued row would over-report.
        latest_queued = s.execute(
            text(
                """
                WITH latest AS (
                  SELECT DISTINCT ON (repo_id) repo_id, status
                  FROM ingest_runs
                  ORDER BY repo_id, id DESC
                )
                SELECT COUNT(*) FROM latest WHERE status = 'queued'
                """
            )
        ).scalar_one()

        # Up to 5 recent failures across all sources for the headline list.
        fail_rows = s.execute(
            select(IngestRun)
            .where(IngestRun.status == "failed")
            .where(IngestRun.error.is_not(None))
            .order_by(IngestRun.finished_at.desc())
            .limit(5)
        ).scalars().all()
        recent_failures = [
            {
                "repo_id": r.repo_id,
                "error": (r.error or "").strip()[:240],
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in fail_rows
        ]

        success_rate = (
            round(100.0 * c_succ / (c_succ + c_fail), 1) if (c_succ + c_fail) > 0 else 0.0
        )
        ingests_payload = IngestAnalytics(
            last_24h_total=int(c_total),
            last_24h_success=int(c_succ),
            last_24h_failed=int(c_fail),
            success_rate_pct=success_rate,
            queue_depth=int(latest_queued),
            recent_failures=recent_failures,
        )

    # Touch Neo4j only if we genuinely need to — we don't here. The graph
    # totals already live on /v1/graph/stats and the dashboard fetches them.

    return IntegrationsSummary(
        sources=sources_payload,
        tokens=tokens_payload,
        repos=repos_payload,
        ingests=ingests_payload,
    )
