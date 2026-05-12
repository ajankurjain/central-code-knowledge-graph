"""FastAPI entrypoint."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from ckg import __version__
from ckg.api.routes import analytics as analytics_routes
from ckg.api.routes import architecture as architecture_routes
from ckg.api.routes import auth as auth_routes
from ckg.api.routes import graph as graph_routes
from ckg.api.routes import graphql as graphql_routes
from ckg.api.routes import health as health_routes
from ckg.api.routes import mcp as mcp_routes
from ckg.api.routes import repos as repos_routes
from ckg.api.routes import search as search_routes
from ckg.api.routes import sources as sources_routes
from ckg.api.routes import webhooks as webhooks_routes
from ckg.config import get_settings
from ckg.db import neo4j as neo4j_db
from ckg.db import postgres as pg
from ckg.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("ckg_api_startup", version=__version__)
    pg.init_schema()
    try:
        neo4j_db.init_schema()
    except Exception as exc:  # don't crash if neo4j is briefly unavailable
        log.warning("neo4j_schema_init_deferred", error=str(exc))
    yield
    neo4j_db.close_driver()
    log.info("ckg_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Central Code Knowledge Graph",
        version=__version__,
        description="Neo4j-backed structural index of multi-repo codebases for AI agents.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_routes.router)
    app.include_router(auth_routes.router, prefix="/v1")
    app.include_router(repos_routes.router, prefix="/v1")
    app.include_router(sources_routes.router, prefix="/v1")
    app.include_router(graph_routes.router, prefix="/v1")
    app.include_router(search_routes.router, prefix="/v1")
    app.include_router(mcp_routes.router, prefix="/v1")
    app.include_router(graphql_routes.router, prefix="/v1")
    app.include_router(webhooks_routes.router, prefix="/v1")
    app.include_router(architecture_routes.router, prefix="/v1")
    app.include_router(analytics_routes.router, prefix="/v1")

    # Per-request log used by /v1/analytics/usage. Has to live below the
    # route registrations because we read `request.scope["route"]` for the
    # parameterised path. Skips meta-endpoints (health, the analytics
    # endpoints themselves — otherwise the UI polling would dominate the
    # data) so the log reflects real client usage.
    _SKIP_PATHS: set[str] = {"/healthz", "/readyz", "/"}
    _SKIP_PREFIXES = ("/v1/analytics/", "/v1/graphql", "/docs", "/openapi", "/static")

    @app.middleware("http")
    async def log_api_calls(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        try:
            path = request.url.path
            if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PREFIXES):
                return response

            principal = getattr(request.state, "principal", None)
            # Resolve the route TEMPLATE (e.g. /v1/repos/{repo_id}) rather
            # than the raw path so per-repo URLs aggregate together. Falls
            # back to the raw path for 404s where no route matched.
            route_obj = request.scope.get("route")
            route = getattr(route_obj, "path", None) or path

            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            # Late import: avoids circular load at startup. Cheap once warm.
            from ckg.db.postgres import ApiCall, get_sessionmaker

            Session = get_sessionmaker()
            with Session() as s:
                s.add(
                    ApiCall(
                        token_id=principal.token_id if principal else None,
                        token_name=principal.name if principal else "anonymous",
                        method=request.method,
                        route=route[:200],
                        status=response.status_code,
                        duration_ms=elapsed_ms,
                    )
                )
                s.commit()
        except SQLAlchemyError:
            # A logging failure must never break a real request.
            log.warning("api_call_log_db_error", exc_info=True)
        except Exception:
            log.warning("api_call_log_failed", exc_info=True)
        return response

    return app


app = create_app()
