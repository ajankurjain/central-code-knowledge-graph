"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ckg import __version__
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
    return app


app = create_app()
