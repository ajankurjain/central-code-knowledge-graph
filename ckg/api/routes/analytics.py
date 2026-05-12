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
    ApiCall,
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


class TokenUsageRow(BaseModel):
    token_id: int | None
    token_name: str
    calls_24h: int
    last_call_at: datetime | None
    last_status: int | None


class EndpointUsageRow(BaseModel):
    route: str
    method: str
    calls_24h: int
    p95_duration_ms: int
    error_rate_pct: float


class ApiCallRow(BaseModel):
    ts: datetime
    token_name: str
    method: str
    route: str
    status: int
    duration_ms: int


class UsageSummary(BaseModel):
    """Live usage analytics for the /integrations page.

    All counts cover the trailing 24 h window. Empty when no requests have
    been made in that window — common right after deploy until traffic
    accumulates.
    """

    window_hours: int
    total_calls: int
    calls_per_hour: float  # last_24h_total / 24 (display convenience)
    distinct_tokens: int
    error_rate_pct: float
    top_tokens: list[TokenUsageRow]
    top_endpoints: list[EndpointUsageRow]
    recent: list[ApiCallRow]


@router.get("/usage", response_model=UsageSummary)
def usage(_: Principal = Depends(require_repo_read)) -> UsageSummary:
    """Per-token + per-endpoint usage over the last 24 h."""
    Session = get_sessionmaker()
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)

    with Session() as s:
        total = s.execute(
            select(func.count(ApiCall.id)).where(ApiCall.ts >= day_ago)
        ).scalar_one()
        errors = s.execute(
            select(func.count(ApiCall.id)).where(
                ApiCall.ts >= day_ago, ApiCall.status >= 400,
            )
        ).scalar_one()
        distinct_tokens = s.execute(
            select(func.count(func.distinct(ApiCall.token_name))).where(
                ApiCall.ts >= day_ago,
            )
        ).scalar_one()

        # Top tokens by call volume.
        token_rows = s.execute(
            text(
                """
                SELECT
                  token_id,
                  COALESCE(token_name, 'anonymous')        AS token_name,
                  COUNT(*)                                  AS calls,
                  MAX(ts)                                   AS last_call,
                  (ARRAY_AGG(status ORDER BY id DESC))[1]   AS last_status
                FROM api_calls
                WHERE ts >= :since
                GROUP BY token_id, token_name
                ORDER BY calls DESC
                LIMIT 10
                """
            ),
            {"since": day_ago},
        ).all()
        top_tokens = [
            TokenUsageRow(
                token_id=row.token_id,
                token_name=row.token_name,
                calls_24h=row.calls,
                last_call_at=row.last_call,
                last_status=row.last_status,
            )
            for row in token_rows
        ]

        # Top endpoints — `percentile_cont` gives us an honest p95 instead of
        # an average that gets swamped by the bulk of fast calls.
        endpoint_rows = s.execute(
            text(
                """
                SELECT
                  route,
                  method,
                  COUNT(*)                                                         AS calls,
                  COALESCE(
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms), 0
                  )::INT                                                            AS p95,
                  100.0 * SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) / COUNT(*) AS err_pct
                FROM api_calls
                WHERE ts >= :since
                GROUP BY route, method
                ORDER BY calls DESC
                LIMIT 12
                """
            ),
            {"since": day_ago},
        ).all()
        top_endpoints = [
            EndpointUsageRow(
                route=row.route,
                method=row.method,
                calls_24h=row.calls,
                p95_duration_ms=int(row.p95),
                error_rate_pct=round(float(row.err_pct), 1),
            )
            for row in endpoint_rows
        ]

        # Live tail — newest 20 calls.
        recent_rows = s.execute(
            select(ApiCall).order_by(ApiCall.id.desc()).limit(20)
        ).scalars().all()
        recent = [
            ApiCallRow(
                ts=r.ts,
                token_name=r.token_name,
                method=r.method,
                route=r.route,
                status=r.status,
                duration_ms=r.duration_ms,
            )
            for r in recent_rows
        ]

    error_rate = (
        round(100.0 * float(errors) / float(total), 1) if total else 0.0
    )
    return UsageSummary(
        window_hours=24,
        total_calls=int(total),
        calls_per_hour=round(float(total) / 24.0, 1),
        distinct_tokens=int(distinct_tokens),
        error_rate_pct=error_rate,
        top_tokens=top_tokens,
        top_endpoints=top_endpoints,
        recent=recent,
    )


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
