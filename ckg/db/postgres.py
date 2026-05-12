"""Postgres setup — repos, API tokens, ingest runs, audit log."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from ckg.config import get_settings
from ckg.logging import get_logger

log = get_logger(__name__)


class Base(DeclarativeBase):
    pass


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Pipe-separated list, e.g. "repo:read|repo:write|admin"
    scopes: Mapped[str] = mapped_column(String(500), default="repo:read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug
    url: Mapped[str] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(120), default="main")
    languages: Mapped[str | None] = mapped_column(String(500), nullable=True)  # csv
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_indexed_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Foreign key to the bulk_sources table when this repo was discovered via a
    # source URL; nullable when the repo was registered directly.
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bulk_sources.id", ondelete="SET NULL"), nullable=True
    )
    # Per-repo PAT for cloning private repos that weren't registered via a
    # bulk source. Fernet-encrypted; never logged. Optional — when null, the
    # clone falls back to the repo's source's auth_secret (if any) or just
    # an anonymous clone (works for public repos / local file:// paths).
    auth_secret: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # Per-repo polling: when > 0, the scheduler queues an incremental ingest
    # this often (seconds). 0 = disabled. Min 60s enforced by scheduler.
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    runs: Mapped[list[IngestRun]] = relationship(back_populates="repo")


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(64), ForeignKey("repos.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30))  # queued|running|success|failed
    mode: Mapped[str] = mapped_column(String(20), default="full")  # full|incremental
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    repo: Mapped[Repo] = relationship(back_populates="runs")


class BulkSource(Base):
    """A registered upstream that we bulk-discover repos from.

    `kind` is one of: github_org, github_user, gitlab_group, gitlab_user,
    bitbucket_workspace, manifest. The combination (kind, name) identifies
    the upstream — `name` is the org / group / user / workspace handle, or
    the manifest URL for kind=manifest.

    `auth_secret` is a Fernet-encrypted token (see ckg/secrets.py) or empty
    for anonymous access. We never log it.
    """

    __tablename__ = "bulk_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auth_secret: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    slug_template: Mapped[str] = mapped_column(String(255), default="{owner}-{name}")
    include_private: Mapped[bool] = mapped_column(Boolean, default=True)
    include_forks: Mapped[bool] = mapped_column(Boolean, default=False)
    include_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    default_branch_override: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_stats: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Scheduled polling: when > 0, the scheduler re-discovers + ingests this
    # often (seconds). 0 = disabled. Min 60s enforced by scheduler.
    sync_interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # Inbound webhook config — presence of `webhook_secret` + enabled flag
    # opens the POST /v1/webhooks/{source_id} endpoint to push events.
    webhook_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_secret: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceRepo(Base):
    """The link between a bulk source and a registered Repo.

    One bulk_source produces 0..N source_repos; each source_repo owns
    exactly one Repo row (cascade on source delete).
    """

    __tablename__ = "source_repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bulk_sources.id", ondelete="CASCADE"), index=True
    )
    repo_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("repos.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    full_name: Mapped[str] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(120))
    private: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    fork: Mapped[bool] = mapped_column(Boolean, default=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(120))  # token name or "bootstrap"
    action: Mapped[str] = mapped_column(String(120))  # e.g. "repo.register", "token.create"
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_engine(s.postgres_dsn, pool_pre_ping=True, pool_size=10, max_overflow=10)
    return _engine


def get_sessionmaker():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


# Additive migrations applied after `create_all`. Each tuple is
# `(table, column, type)` and is run via `ALTER TABLE … ADD COLUMN IF NOT
# EXISTS`. This handles the case where a previously-deployed database is
# missing a column added to the ORM model in a later release. Bigger schema
# changes (drops, renames, type changes) go through proper Alembic
# migrations in `alembic/versions/`.
ADDITIVE_MIGRATIONS: list[tuple[str, str, str]] = [
    ("repos", "auth_secret", "VARCHAR(2000)"),
    ("repos", "source_id", "INTEGER"),
    ("repos", "poll_interval_seconds", "INTEGER DEFAULT 0"),
    ("ingest_runs", "mode", "VARCHAR(20) DEFAULT 'full'"),
    ("bulk_sources", "sync_interval_seconds", "INTEGER DEFAULT 0"),
    ("bulk_sources", "webhook_enabled", "BOOLEAN DEFAULT FALSE"),
    ("bulk_sources", "webhook_secret", "VARCHAR(120)"),
]


def init_schema() -> None:
    """Create tables and apply additive migrations (idempotent)."""
    from sqlalchemy import text

    Base.metadata.create_all(get_engine())
    with get_engine().begin() as conn:
        for table, col, typ in ADDITIVE_MIGRATIONS:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}"))
    log.info("postgres_schema_ready")


def ping() -> bool:
    try:
        with get_sessionmaker()() as s:
            s.execute(select(1)).scalar()
        return True
    except Exception as exc:
        log.warning("postgres_ping_failed", error=str(exc))
        return False
