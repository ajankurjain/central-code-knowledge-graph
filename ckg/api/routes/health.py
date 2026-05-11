"""Health + readiness probes (unauthenticated)."""

from fastapi import APIRouter

from ckg import __version__
from ckg.db import neo4j as neo4j_db
from ckg.db import postgres as pg
from ckg.db import redis as redis_db

router = APIRouter(tags=["system"])


@router.get("/healthz")
def healthz() -> dict:
    """Liveness — process is up."""
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
def readyz() -> dict:
    """Readiness — all backing stores reachable."""
    checks = {
        "neo4j": neo4j_db.ping(),
        "postgres": pg.ping(),
        "redis": redis_db.ping(),
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "version": __version__,
    }
