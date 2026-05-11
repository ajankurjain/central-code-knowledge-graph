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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    runs: Mapped[list["IngestRun"]] = relationship(back_populates="repo")


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


def init_schema() -> None:
    """Create tables (idempotent)."""
    Base.metadata.create_all(get_engine())
    log.info("postgres_schema_ready")


def ping() -> bool:
    try:
        with get_sessionmaker()() as s:
            s.execute(select(1)).scalar()
        return True
    except Exception as exc:
        log.warning("postgres_ping_failed", error=str(exc))
        return False
