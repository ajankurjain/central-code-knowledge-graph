"""Inbound-webhook verification + payload parsing.

We support GitHub, GitLab, and Bitbucket today. The verifier is chosen
by inspecting request headers — providers each send a distinctive
`X-{provider}-*` header.

For each verified payload we extract `(full_name, ref)` and look up the
matching `SourceRepo`. We then enqueue an **incremental** ingest. If the
matching repo has never been ingested, we coerce to `full`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets as _stdlib_secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ckg.db.postgres import BulkSource, IngestRun, Repo, SourceRepo, get_sessionmaker
from ckg.logging import get_logger

log = get_logger(__name__)


@dataclass
class WebhookEvent:
    provider: str           # github | gitlab | bitbucket
    full_name: str          # "owner/name" as the provider reports it
    ref: str | None = None  # e.g. "refs/heads/main"


def detect_provider(headers: dict[str, str]) -> str | None:
    h = {k.lower(): v for k, v in headers.items()}
    if "x-github-event" in h or "x-hub-signature-256" in h:
        return "github"
    if "x-gitlab-event" in h or "x-gitlab-token" in h:
        return "gitlab"
    if "x-event-key" in h and "repo" in h["x-event-key"].lower():
        return "bitbucket"
    return None


def verify(provider: str, headers: dict[str, str], body: bytes, secret: str | None, query_token: str | None) -> bool:
    """Return True iff the request looks legitimate for the given provider.

    Providers' auth shapes differ:
      - GitHub : HMAC-SHA256 of body keyed by `secret`, compared timing-safe
                 against the value in `X-Hub-Signature-256` (`sha256=…`).
      - GitLab : `X-Gitlab-Token` header value MUST equal `secret`.
      - Bitbucket : URL/query token MUST equal `secret`. (Bitbucket Cloud's
                 built-in webhook signing is not universally enabled.)
    """
    if not secret:
        return False
    h = {k.lower(): v for k, v in headers.items()}
    if provider == "github":
        sig = h.get("x-hub-signature-256", "")
        if not sig.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    if provider == "gitlab":
        return hmac.compare_digest(h.get("x-gitlab-token", ""), secret)
    if provider == "bitbucket":
        return hmac.compare_digest(query_token or "", secret)
    return False


def parse(provider: str, headers: dict[str, str], body: bytes) -> WebhookEvent | None:
    """Pull `(full_name, ref)` out of a verified payload. Returns None for
    event kinds we don't act on (ping, non-push)."""
    h = {k.lower(): v for k, v in headers.items()}
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return None

    if provider == "github":
        event = h.get("x-github-event") or ""
        if event == "ping":
            return None
        if event != "push":
            # Only treat push events as triggers; PR / issue events don't change
            # ingested source.
            return None
        repo = payload.get("repository", {}) or {}
        full_name = repo.get("full_name") or ""
        ref = payload.get("ref")
        if not full_name:
            return None
        return WebhookEvent(provider="github", full_name=full_name, ref=ref)

    if provider == "gitlab":
        event = (h.get("x-gitlab-event") or "").lower()
        if "push" not in event:
            return None
        project = payload.get("project", {}) or {}
        full_name = project.get("path_with_namespace") or ""
        ref = payload.get("ref")
        if not full_name:
            return None
        return WebhookEvent(provider="gitlab", full_name=full_name, ref=ref)

    if provider == "bitbucket":
        event = (h.get("x-event-key") or "").lower()
        if event != "repo:push":
            return None
        repo = payload.get("repository", {}) or {}
        full_name = repo.get("full_name") or ""
        changes = (payload.get("push", {}) or {}).get("changes", []) or []
        ref = None
        if changes:
            new = changes[0].get("new") or {}
            if new.get("name"):
                ref = f"refs/heads/{new['name']}"
        if not full_name:
            return None
        return WebhookEvent(provider="bitbucket", full_name=full_name, ref=ref)

    return None


def handle_event(source_id: int, event: WebhookEvent) -> dict:
    """Look up the matching SourceRepo + enqueue an ingest."""
    from ckg.worker.celery_app import celery_app

    Session = get_sessionmaker()
    with Session() as s:
        link = s.execute(
            select(SourceRepo).where(
                SourceRepo.source_id == source_id,
                SourceRepo.full_name == event.full_name,
            )
        ).scalar_one_or_none()
        if link is None:
            return {"matched": False, "reason": f"no source-repo for {event.full_name}"}
        repo = s.get(Repo, link.repo_id)
        if repo is None:
            return {"matched": False, "reason": f"repo {link.repo_id} missing"}
        mode = "full" if repo.last_indexed_at is None else "incremental"
        run = IngestRun(repo_id=repo.id, status="queued", mode=mode)
        s.add(run)
        s.commit()
        s.refresh(run)
        repo_id = repo.id
        run_id = run.id
    celery_app.send_task("ckg.ingest_repo", args=[repo_id, run_id, mode])
    return {"matched": True, "repo_id": repo_id, "run_id": run_id, "mode": mode}


def new_secret() -> str:
    """Generate a fresh webhook secret (URL-safe, ~32 bytes)."""
    return _stdlib_secrets.token_urlsafe(32)
