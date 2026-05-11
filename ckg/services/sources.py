"""Bulk-source service: discover, register, queue ingests, cascade-delete.

A "source" is a single URL (GitHub org/user, GitLab group/user, Bitbucket
workspace, or a JSON/YAML manifest) that we periodically discover repos
from. Each discovered repo becomes a normal `Repo` row plus a
`SourceRepo` link row that ties it back to the source.

Slug generation: each DiscoveredRepo gets a slug via the source's
`slug_template`. Default `{owner}-{name}` — lowercased, non-`[a-z0-9-_]`
stripped, truncated to 63 chars. Conflicts raise (caller picks a
different template or renames manually).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from ckg.db.postgres import (
    AuditLog,
    BulkSource,
    IngestRun,
    Repo,
    SourceRepo,
    get_sessionmaker,
)
from ckg.logging import get_logger
from ckg.secrets import decrypt, encrypt
from ckg.sources.base import DiscoveredRepo, SourceSpec
from ckg.sources.registry import get_provider

log = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9-_]+")


# ── Slug helpers ────────────────────────────────────────────────────────────


def render_slug(template: str, repo: DiscoveredRepo) -> str:
    raw = template.format(owner=repo.owner, name=repo.name, full=repo.full_name)
    s = raw.lower()
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-_")
    return s[:63] or "repo"


# ── Source registration ─────────────────────────────────────────────────────


@dataclass
class CreateSourceInput:
    kind: str
    name: str
    token: str | None
    url: str | None = None
    include_private: bool = True
    include_forks: bool = False
    include_archived: bool = False
    default_branch_override: str | None = None
    slug_template: str = "{owner}-{name}"


def create_source(input: CreateSourceInput, actor: str) -> int:
    Session = get_sessionmaker()
    with Session() as s:
        existing = s.execute(
            select(BulkSource).where(BulkSource.kind == input.kind, BulkSource.name == input.name)
        ).scalar_one_or_none()
        if existing:
            raise ValueError(
                f"source already exists with kind={input.kind} name={input.name} (id={existing.id})"
            )
        row = BulkSource(
            kind=input.kind,
            name=input.name,
            url=input.url,
            auth_secret=encrypt(input.token) if input.token else None,
            slug_template=input.slug_template or "{owner}-{name}",
            include_private=input.include_private,
            include_forks=input.include_forks,
            include_archived=input.include_archived,
            default_branch_override=input.default_branch_override,
        )
        s.add(row)
        s.flush()
        s.add(AuditLog(
            actor=actor, action="source.create",
            target=f"{input.kind}/{input.name}", detail={"id": row.id, "url": input.url},
        ))
        s.commit()
        return row.id


# ── Sync (discover + register + queue ingests) ──────────────────────────────


@dataclass
class SyncStats:
    discovered: int = 0
    added: int = 0
    already: int = 0
    skipped: int = 0
    queued: int = 0
    errors: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "discovered": self.discovered,
            "added": self.added,
            "already": self.already,
            "skipped": self.skipped,
            "queued": self.queued,
            "errors": self.errors or [],
        }


def sync_source(source_id: int, actor: str = "system") -> SyncStats:
    """Run the provider against the upstream, register new repos, queue ingests."""
    from ckg.worker.celery_app import celery_app  # local import

    Session = get_sessionmaker()
    with Session() as s:
        source = s.get(BulkSource, source_id)
        if not source:
            raise ValueError(f"source {source_id} not found")
        token = decrypt(source.auth_secret) if source.auth_secret else None
        spec = SourceSpec(
            kind=source.kind, name=source.name, token=token,
            include_private=source.include_private,
            include_forks=source.include_forks,
            include_archived=source.include_archived,
            default_branch_override=source.default_branch_override,
        )
        slug_template = source.slug_template
        s.add(AuditLog(actor=actor, action="source.sync.start", target=str(source_id)))
        s.commit()

    provider = get_provider(spec.kind)
    stats = SyncStats(errors=[])
    queued_repo_ids: list[tuple[str, int]] = []  # (repo_id, run_id)

    try:
        for discovered in provider.discover(spec):
            stats.discovered += 1
            slug = render_slug(slug_template, discovered)
            try:
                added, run_id = _link_repo(
                    source_id=source_id,
                    slug=slug,
                    discovered=discovered,
                    actor=actor,
                    default_branch_override=spec.default_branch_override,
                )
            except Exception as exc:
                stats.skipped += 1
                (stats.errors or []).append(f"{discovered.full_name}: {exc}")
                continue
            if added:
                stats.added += 1
            else:
                stats.already += 1
            if run_id is not None:
                stats.queued += 1
                queued_repo_ids.append((slug, run_id))
    finally:
        Session = get_sessionmaker()
        with Session() as s:
            source = s.get(BulkSource, source_id)
            if source is not None:
                source.last_synced_at = datetime.now(UTC)
                source.last_sync_stats = stats.to_dict()
                s.commit()

    # Now actually queue the ingests (we hold off until after the DB writes are
    # committed so the worker can find the run rows).
    for repo_id, run_id in queued_repo_ids:
        celery_app.send_task("ckg.ingest_repo", args=[repo_id, run_id, "full"])

    log.info("source_sync_done", source_id=source_id, **stats.to_dict())
    return stats


def _link_repo(
    *,
    source_id: int,
    slug: str,
    discovered: DiscoveredRepo,
    actor: str,
    default_branch_override: str | None,
) -> tuple[bool, int | None]:
    """Idempotent. Returns (was_added, run_id_to_queue_or_None)."""
    Session = get_sessionmaker()
    with Session() as s:
        # Already linked to this source?
        link = s.execute(
            select(SourceRepo).where(
                SourceRepo.source_id == source_id, SourceRepo.full_name == discovered.full_name,
            )
        ).scalar_one_or_none()
        if link is not None:
            # Already tracked. Don't auto-re-queue ingest; the polling layer
            # (Commit B) handles re-sync explicitly.
            return False, None

        # Slug collision with an existing repo?
        existing_repo = s.get(Repo, slug)
        if existing_repo is not None:
            if existing_repo.source_id is None:
                raise ValueError(
                    f"slug '{slug}' is already taken by a manually-registered repo. "
                    "Pick a different slug_template or rename that repo first."
                )
            if existing_repo.source_id != source_id:
                raise ValueError(
                    f"slug '{slug}' is already owned by source {existing_repo.source_id}"
                )
            # Same source, same slug, but the SourceRepo link is missing — recreate.
            link = SourceRepo(
                source_id=source_id, repo_id=slug,
                external_id=discovered.external_id,
                full_name=discovered.full_name,
                default_branch=discovered.default_branch,
                private=discovered.private, archived=discovered.archived, fork=discovered.fork,
            )
            s.add(link)
            s.commit()
            return False, None

        branch = default_branch_override or discovered.default_branch
        repo = Repo(
            id=slug, url=discovered.clone_url, default_branch=branch,
            source_id=source_id,
        )
        s.add(repo)
        link = SourceRepo(
            source_id=source_id, repo_id=slug,
            external_id=discovered.external_id,
            full_name=discovered.full_name,
            default_branch=branch,
            private=discovered.private, archived=discovered.archived, fork=discovered.fork,
        )
        s.add(link)
        run = IngestRun(repo_id=slug, status="queued", mode="full")
        s.add(run)
        s.add(AuditLog(
            actor=actor, action="repo.register.from_source",
            target=slug, detail={"source_id": source_id, "full_name": discovered.full_name},
        ))
        s.commit()
        s.refresh(run)
        return True, run.id


# ── Delete (cascade) ────────────────────────────────────────────────────────


def delete_source(source_id: int, actor: str) -> dict:
    """Cascade-delete: removes every Repo this source produced + their
    Neo4j sub-graph, plus the SourceRepo links + the BulkSource row."""
    from ckg.db.neo4j import session as neo_session

    Session = get_sessionmaker()
    with Session() as s:
        source = s.get(BulkSource, source_id)
        if not source:
            raise ValueError(f"source {source_id} not found")
        repo_ids = [r.repo_id for r in s.execute(
            select(SourceRepo).where(SourceRepo.source_id == source_id)
        ).scalars().all()]

        # Drop graph data for each repo (best-effort).
        try:
            with neo_session() as ns:
                for rid in repo_ids:
                    ns.run("MATCH (n) WHERE n.repo_id = $rid DETACH DELETE n", rid=rid)
        except Exception as exc:
            log.warning("source_delete_neo4j_failed", source_id=source_id, error=str(exc))

        # The Repo + SourceRepo rows go via FK cascade on `bulk_sources.id`
        # for SourceRepo, but we drop Repo explicitly so the relation cascades
        # cleanly to IngestRun rows.
        for rid in repo_ids:
            repo = s.get(Repo, rid)
            if repo is not None:
                s.delete(repo)
        s.delete(source)
        s.add(AuditLog(
            actor=actor, action="source.delete",
            target=str(source_id),
            detail={"kind": source.kind, "name": source.name, "repos_dropped": repo_ids},
        ))
        s.commit()
    return {"deleted_source_id": source_id, "repos_dropped": repo_ids}


# ── Auth lookup (used by worker on clone) ───────────────────────────────────


def credentialed_clone_url_for_repo(repo_id: str) -> str | None:
    """Returns a clone URL with credentials baked in for a repo discovered
    via a source. Returns None when the repo wasn't from a source or the
    source has no token."""
    Session = get_sessionmaker()
    with Session() as s:
        repo = s.get(Repo, repo_id)
        if not repo or not repo.source_id:
            return None
        source = s.get(BulkSource, repo.source_id)
        if not source or not source.auth_secret:
            return None
        token = decrypt(source.auth_secret)
        provider = get_provider(source.kind)
        return provider.credentialed_clone_url(repo.url, token)
