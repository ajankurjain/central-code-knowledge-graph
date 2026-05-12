"""Aggregate analytics for the dashboard + /integrations page.

Single endpoint that joins counts across Postgres + Neo4j so the UI
doesn't have to fan out to five separate endpoints to render a summary.
Keeping it small and dependency-free — every query here is indexed and
read-only.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
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
from ckg.services.savings import (
    MODELS,
    aggregate_savings,
    get_model,
    integration_for_route,
    list_models,
    normalise_route,
    tokens_saved_for_route,
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


# ─── Savings ──────────────────────────────────────────────────────────────


class ModelOption(BaseModel):
    id: str
    label: str
    input_per_million_usd: float
    output_per_million_usd: float
    blended_per_million_usd: float


class SavingsRouteRow(BaseModel):
    route: str
    integration: str  # mcp | graphql | rest | other
    calls: int
    tokens_saved: int
    dollars_saved: float


class SavingsTokenRow(BaseModel):
    token_id: int | None
    token_name: str
    calls: int
    tokens_saved: int
    dollars_saved: float


class SavingsBucketRow(BaseModel):
    """Per-integration breakdown — mcp / graphql / rest."""

    integration: str
    calls: int
    tokens_saved: int
    dollars_saved: float


class SavingsDayPoint(BaseModel):
    day: str  # YYYY-MM-DD (UTC)
    tokens_saved: int
    dollars_saved: float


class SavingsSummary(BaseModel):
    """Heuristic cost-saving roll-up across all logged API calls.

    Premise: every ckg call replaced "agent reads N files of source"
    with "agent reads a small structured JSON response". The delta in
    tokens, priced at the chosen model's per-token cost, surfaces as
    dollars saved. See `ckg.services.savings` for the per-endpoint
    baseline numbers.
    """

    model: ModelOption
    window_hours: int
    total_calls: int
    total_calls_saving: int  # subset of total_calls that had a > 0 saving
    tokens_saved: int
    dollars_saved: float
    lifetime_tokens_saved: int
    lifetime_dollars_saved: float
    by_route: list[SavingsRouteRow]
    by_token: list[SavingsTokenRow]
    by_integration: list[SavingsBucketRow]
    daily: list[SavingsDayPoint]
    available_models: list[ModelOption]


def _model_option(m_id: str) -> ModelOption:
    m = get_model(m_id)
    return ModelOption(
        id=m.id,
        label=m.label,
        input_per_million_usd=m.input_per_million_usd,
        output_per_million_usd=m.output_per_million_usd,
        blended_per_million_usd=round(m.blended_per_million_usd(), 4),
    )


@router.get("/savings", response_model=SavingsSummary)
def savings(
    model: str = Query(None, description="Model id from /v1/analytics/savings/models"),
    window_hours: int = Query(24, ge=1, le=24 * 30),
    _: Principal = Depends(require_repo_read),
) -> SavingsSummary:
    """Token + dollar savings rolled up from the request log.

    `window_hours` controls every bucket EXCEPT `lifetime_*` and the
    daily series — the daily series covers the same window so the UI
    can render a 7- or 30-day chart by passing 168 or 720.
    """
    price = get_model(model)
    dollars_per_token = price.dollars_per_token()
    Session = get_sessionmaker()
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours)

    with Session() as s:
        # Window per-route counts.
        route_counts = s.execute(
            text(
                """
                SELECT route, COUNT(*) AS calls
                FROM api_calls
                WHERE ts >= :since
                GROUP BY route
                """
            ),
            {"since": since},
        ).all()
        # Lifetime (everything in the log; pruned to 7d by the beat task).
        lifetime_route_counts = s.execute(
            text("SELECT route, COUNT(*) FROM api_calls GROUP BY route")
        ).all()

        # Per-token counts (window only — lifetime here would over-promise
        # since old tokens may have been revoked).
        token_route_rows = s.execute(
            text(
                """
                SELECT token_id, COALESCE(token_name, 'anonymous') AS token_name,
                       route, COUNT(*) AS calls
                FROM api_calls
                WHERE ts >= :since
                GROUP BY token_id, token_name, route
                """
            ),
            {"since": since},
        ).all()

        # Daily series — one row per UTC day in window with total saving.
        daily_rows = s.execute(
            text(
                """
                SELECT date_trunc('day', ts AT TIME ZONE 'UTC') AS day, route, COUNT(*) AS calls
                FROM api_calls
                WHERE ts >= :since
                GROUP BY day, route
                ORDER BY day ASC
                """
            ),
            {"since": since},
        ).all()

    total_calls = sum(int(c) for _r, c in route_counts)

    # Window totals + per-route breakdown.
    window_total_tokens, route_savings = aggregate_savings(
        (normalise_route(r), int(c)) for r, c in route_counts
    )
    window_total_dollars = window_total_tokens * dollars_per_token

    lifetime_total_tokens, _ = aggregate_savings(
        (normalise_route(r), int(c)) for r, c in lifetime_route_counts
    )
    lifetime_total_dollars = lifetime_total_tokens * dollars_per_token

    by_route = [
        SavingsRouteRow(
            route=r.route,
            integration=integration_for_route(r.route),
            calls=r.calls,
            tokens_saved=r.tokens_saved,
            dollars_saved=round(r.tokens_saved * dollars_per_token, 4),
        )
        for r in route_savings[:15]
    ]

    # Per-token aggregation: sum savings across all routes for each token.
    by_token_map: dict[
        tuple[int | None, str], dict[str, int]
    ] = {}
    for row in token_route_rows:
        per_call = tokens_saved_for_route(normalise_route(row.route))
        if per_call <= 0:
            continue
        key = (row.token_id, row.token_name)
        bucket = by_token_map.setdefault(key, {"calls": 0, "tokens": 0})
        bucket["calls"] += int(row.calls)
        bucket["tokens"] += per_call * int(row.calls)
    by_token = sorted(
        (
            SavingsTokenRow(
                token_id=tid,
                token_name=tname,
                calls=v["calls"],
                tokens_saved=v["tokens"],
                dollars_saved=round(v["tokens"] * dollars_per_token, 4),
            )
            for (tid, tname), v in by_token_map.items()
        ),
        key=lambda r: r.tokens_saved,
        reverse=True,
    )[:10]

    # Per-integration: mcp / graphql / rest.
    bucket_acc: dict[str, dict[str, int]] = {}
    total_calls_saving = 0
    for r in route_savings:
        bucket = bucket_acc.setdefault(
            integration_for_route(r.route),
            {"calls": 0, "tokens": 0},
        )
        bucket["calls"] += r.calls
        bucket["tokens"] += r.tokens_saved
        total_calls_saving += r.calls
    by_integration = sorted(
        (
            SavingsBucketRow(
                integration=name,
                calls=v["calls"],
                tokens_saved=v["tokens"],
                dollars_saved=round(v["tokens"] * dollars_per_token, 4),
            )
            for name, v in bucket_acc.items()
        ),
        key=lambda b: b.tokens_saved,
        reverse=True,
    )

    # Daily series.
    daily_acc: dict[str, int] = {}
    for row in daily_rows:
        per_call = tokens_saved_for_route(normalise_route(row.route))
        if per_call <= 0:
            continue
        day_key = row.day.strftime("%Y-%m-%d") if hasattr(row.day, "strftime") else str(row.day)[:10]
        daily_acc[day_key] = daily_acc.get(day_key, 0) + per_call * int(row.calls)
    daily = [
        SavingsDayPoint(
            day=day,
            tokens_saved=tokens,
            dollars_saved=round(tokens * dollars_per_token, 4),
        )
        for day, tokens in sorted(daily_acc.items())
    ]

    return SavingsSummary(
        model=_model_option(price.id),
        window_hours=window_hours,
        total_calls=total_calls,
        total_calls_saving=total_calls_saving,
        tokens_saved=window_total_tokens,
        dollars_saved=round(window_total_dollars, 2),
        lifetime_tokens_saved=lifetime_total_tokens,
        lifetime_dollars_saved=round(lifetime_total_dollars, 2),
        by_route=by_route,
        by_token=by_token,
        by_integration=by_integration,
        daily=daily,
        available_models=[_model_option(m_id) for m_id in MODELS],
    )


@router.get("/savings/models", response_model=list[ModelOption])
def savings_models(_: Principal = Depends(require_repo_read)) -> list[ModelOption]:
    """Catalog of model price cards. Useful for clients that just want
    to render a model picker without pulling the full savings payload."""
    return [_model_option(m.id) for m in list_models()]


# ─── Integrations summary ─────────────────────────────────────────────────


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
