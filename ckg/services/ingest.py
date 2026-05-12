"""Full + incremental ingest pipeline.

Two modes:

- **full**: wipe the repo's sub-graph and re-parse every file. Always safe;
  used the first time and when you want a clean rebuild.
- **incremental**: walk the checkout, sha-hash each file, compare against
  the existing File-node shas in Neo4j, and only re-parse files whose sha
  changed (plus delete files that were removed and add files that are new).

The CallSite-node pattern is what makes incremental safe: every call site
is stored as a node owned by its caller (with a `file_path` property), and
materialized into a `(:Function)-[:CALLS]->(:Function)` edge by
`_resolve_call_edges`. CallSites persist between ingests; only the
per-file sub-graph is rewritten on a change. After every ingest we re-run
the resolver repo-wide so cross-file edges stay correct even when a file
that's *referenced* changes but the *referencing* file doesn't.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ckg.config import get_settings
from ckg.db.neo4j import init_schema as init_neo_schema
from ckg.db.neo4j import session as neo_session
from ckg.logging import get_logger
from ckg.parsers import get_parser
from ckg.parsers.base import ParseResult, all_languages, detect_language

log = get_logger(__name__)

IngestMode = Literal["full", "incremental"]

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", "out", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target", "vendor"}
SKIP_PATTERNS = ("*.min.js", "*.map", "*.lock", "*.snap")

BATCH = 500


class PermanentIngestError(RuntimeError):
    """Raised for ingest failures that won't fix themselves on retry:
    wrong branch, repo deleted, auth permanently revoked, etc. The Celery
    worker catches this specifically and skips the usual retry-with-
    backoff so the queue doesn't get clogged with doomed-to-fail tasks.
    """


@dataclass
class IngestStats:
    mode: IngestMode = "full"
    files_parsed: int = 0
    files_added: int = 0
    files_changed: int = 0
    files_removed: int = 0
    files_unchanged: int = 0
    files_skipped: int = 0
    functions: int = 0
    classes: int = 0
    calls: int = 0
    imports: int = 0
    languages: set[str] = field(default_factory=set)
    head_sha: str | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "files_parsed": self.files_parsed,
            "files_added": self.files_added,
            "files_changed": self.files_changed,
            "files_removed": self.files_removed,
            "files_unchanged": self.files_unchanged,
            "files_skipped": self.files_skipped,
            "functions": self.functions,
            "classes": self.classes,
            "calls": self.calls,
            "imports": self.imports,
            "languages": sorted(self.languages),
            "head_sha": self.head_sha,
        }


# ── Entrypoint ──────────────────────────────────────────────────────────────


def ingest_repo(
    *,
    repo_id: str,
    url: str,
    branch: str,
    workdir: Path,
    mode: IngestMode = "full",
) -> IngestStats:
    init_neo_schema()
    workdir.parent.mkdir(parents=True, exist_ok=True)
    # If the repo was discovered via a bulk source, swap in a clone URL with
    # the source's PAT baked in. Falls back to the bare URL on any error.
    effective_url = url
    try:
        from ckg.services.sources import credentialed_clone_url_for_repo

        creds_url = credentialed_clone_url_for_repo(repo_id)
        if creds_url:
            effective_url = creds_url
    except Exception as exc:
        log.warning("source_auth_lookup_failed", repo_id=repo_id, error=str(exc))
    local_path = _checkout(url=effective_url, branch=branch, dest=workdir)
    # Fail loudly if the checkout has no parseable source code. This usually
    # means the configured branch is a skeleton commit (e.g. GitLab returns
    # `main` as the default but the team works on `develop`). Surfacing it
    # as a hard failure lets the operator fix it by editing the branch on
    # the source/repo, instead of silently producing an indexed-but-empty
    # repo and a blank /arch page.
    if not url.startswith("file://") and _count_source_files(local_path) == 0:
        available = sorted(_remote_branches(local_path))
        hint = (
            f" Available branches on origin: {', '.join(available[:8])}"
            + (f", … (+{len(available) - 8} more)" if len(available) > 8 else "")
            if available
            else ""
        )
        # PermanentIngestError so the worker doesn't burn three retries on
        # a config issue that won't fix itself.
        raise PermanentIngestError(
            f"Branch '{branch}' has no source files matching any registered "
            f"parser. Pick a different branch on the source or this repo."
            f"{hint}"
        )
    head_sha = _git_head(local_path)
    log.info("ingest_checkout_done", repo_id=repo_id, mode=mode, path=str(local_path), head=head_sha)

    if mode == "full":
        stats = _run_full(repo_id=repo_id, url=url, branch=branch, local_path=local_path)
    else:
        stats = _run_incremental(repo_id=repo_id, url=url, branch=branch, local_path=local_path)

    stats.head_sha = head_sha
    _resolve_call_edges(repo_id)

    # Optional LSP precision pass. Off by default; controlled by CKG_LSP_ENABLED.
    # Failures here NEVER fail the ingest — the name-based edges are already in place.
    try:
        from ckg.services.lsp_resolve import run_lsp_pass

        lsp_stats = run_lsp_pass(repo_id=repo_id, repo_root=local_path)
        if lsp_stats and not lsp_stats.get("skipped"):
            log.info("ingest_lsp_pass", repo_id=repo_id, **lsp_stats)
    except Exception as exc:
        log.warning("ingest_lsp_pass_failed", repo_id=repo_id, error=str(exc))

    log.info("ingest_done", repo_id=repo_id, **stats.to_dict())
    return stats


# ── Full ────────────────────────────────────────────────────────────────────


def _run_full(*, repo_id: str, url: str, branch: str, local_path: Path) -> IngestStats:
    # Wipe everything for this repo, then re-parse from scratch.
    with neo_session() as s:
        s.run("MATCH (n) WHERE n.repo_id = $rid DETACH DELETE n", rid=repo_id)
        s.run(
            "MERGE (r:Repo {id: $rid}) SET r.url = $url, r.default_branch = $branch",
            rid=repo_id, url=url, branch=branch,
        )

    stats = IngestStats(mode="full")
    enabled = _enabled_languages()

    file_b: list[dict] = []
    cls_b: list[dict] = []
    fn_b: list[dict] = []
    imp_b: list[dict] = []
    cs_b: list[dict] = []

    for path in _walk_repo(local_path):
        if not _process_path(
            path=path, local_path=local_path, repo_id=repo_id,
            enabled=enabled, stats=stats,
            file_b=file_b, cls_b=cls_b, fn_b=fn_b, imp_b=imp_b, cs_b=cs_b,
        ):
            continue
        if len(file_b) >= BATCH:
            _flush(file_b, cls_b, fn_b, imp_b, cs_b)

    _flush(file_b, cls_b, fn_b, imp_b, cs_b)
    return stats


# ── Incremental ─────────────────────────────────────────────────────────────


def _run_incremental(*, repo_id: str, url: str, branch: str, local_path: Path) -> IngestStats:
    """Diff on-disk shas against what's already in the graph."""
    with neo_session() as s:
        s.run(
            "MERGE (r:Repo {id: $rid}) SET r.url = $url, r.default_branch = $branch",
            rid=repo_id, url=url, branch=branch,
        )
        existing_rows = s.run(
            "MATCH (r:Repo {id: $rid})-[:CONTAINS]->(f:File) RETURN f.path AS p, f.sha AS sha",
            rid=repo_id,
        ).data()
    existing = {row["p"]: row["sha"] for row in existing_rows}

    stats = IngestStats(mode="incremental")
    enabled = _enabled_languages()

    file_b: list[dict] = []
    cls_b: list[dict] = []
    fn_b: list[dict] = []
    imp_b: list[dict] = []
    cs_b: list[dict] = []

    on_disk: set[str] = set()
    for path in _walk_repo(local_path):
        lang = detect_language(path)
        if lang is None or lang not in enabled:
            stats.files_skipped += 1
            continue
        try:
            source = path.read_bytes()
        except Exception as exc:
            log.warning("read_failed", path=str(path), error=str(exc))
            stats.files_skipped += 1
            continue
        rel_path = str(path.relative_to(local_path))
        new_sha = _sha1(source)
        on_disk.add(rel_path)

        old_sha = existing.get(rel_path)
        if old_sha == new_sha:
            stats.files_unchanged += 1
            continue

        if old_sha is None:
            stats.files_added += 1
        else:
            stats.files_changed += 1
            _purge_file_subgraph(repo_id, rel_path)

        if not _parse_and_collect(
            path=path, rel_path=rel_path, source=source, sha=new_sha,
            repo_id=repo_id, lang=lang, stats=stats,
            file_b=file_b, cls_b=cls_b, fn_b=fn_b, imp_b=imp_b, cs_b=cs_b,
        ):
            continue
        if len(file_b) >= BATCH:
            _flush(file_b, cls_b, fn_b, imp_b, cs_b)

    _flush(file_b, cls_b, fn_b, imp_b, cs_b)

    # Files removed from disk → delete from graph
    removed = set(existing) - on_disk
    for rel_path in removed:
        _purge_file_subgraph(repo_id, rel_path)
        with neo_session() as s:
            s.run(
                "MATCH (f:File {repo_id: $rid, path: $p}) DETACH DELETE f",
                rid=repo_id, p=rel_path,
            )
        stats.files_removed += 1

    return stats


# ── Per-file processing (shared) ────────────────────────────────────────────


def _process_path(*, path, local_path, repo_id, enabled, stats, file_b, cls_b, fn_b, imp_b, cs_b) -> bool:
    lang = detect_language(path)
    if lang is None or lang not in enabled:
        stats.files_skipped += 1
        return False
    try:
        source = path.read_bytes()
    except Exception as exc:
        log.warning("read_failed", path=str(path), error=str(exc))
        stats.files_skipped += 1
        return False
    rel_path = str(path.relative_to(local_path))
    sha = _sha1(source)
    return _parse_and_collect(
        path=path, rel_path=rel_path, source=source, sha=sha,
        repo_id=repo_id, lang=lang, stats=stats,
        file_b=file_b, cls_b=cls_b, fn_b=fn_b, imp_b=imp_b, cs_b=cs_b,
    )


def _parse_and_collect(*, path, rel_path, source, sha, repo_id, lang, stats,
                       file_b, cls_b, fn_b, imp_b, cs_b) -> bool:
    parser = get_parser(lang)
    if parser is None:
        stats.files_skipped += 1
        return False
    try:
        result: ParseResult = parser.parse(Path(rel_path), source)
    except Exception as exc:
        log.warning("parse_failed", path=str(path), error=str(exc))
        stats.files_skipped += 1
        return False

    stats.files_parsed += 1
    stats.functions += len(result.functions)
    stats.classes += len(result.classes)
    stats.calls += len(result.calls)
    stats.imports += len(result.imports)
    stats.languages.add(result.language)

    file_b.append({
        "repo_id": repo_id,
        "path": result.path,
        "language": result.language,
        "size_bytes": result.size_bytes,
        "sha": sha,
    })
    for c in result.classes:
        cls_b.append({
            "repo_id": repo_id, "file_path": result.path,
            "name": c.name, "qualified_name": c.qualified_name,
            "start_line": c.start_line, "end_line": c.end_line,
            "doc": c.doc,
        })
    for fn in result.functions:
        fn_b.append({
            "repo_id": repo_id, "file_path": result.path,
            "name": fn.name, "qualified_name": fn.qualified_name,
            "start_line": fn.start_line, "end_line": fn.end_line,
            "is_method": fn.is_method, "is_async": fn.is_async,
            "doc": fn.doc, "body_sha": fn.body_sha,
            "class_qname": fn.class_qname,
        })
    for imp in result.imports:
        imp_b.append({
            "repo_id": repo_id, "file_path": result.path,
            "module": imp.module,
        })
    for call in result.calls:
        cs_b.append({
            "repo_id": repo_id, "file_path": result.path,
            "caller_qname": call.caller_qname,
            "callee_name": call.callee_name,
            "line": call.line,
            "character": call.character,
        })
    return True


# ── Neo4j writes ────────────────────────────────────────────────────────────


def _flush(file_b, cls_b, fn_b, imp_b, cs_b) -> None:
    if not any([file_b, cls_b, fn_b, imp_b, cs_b]):
        return
    with neo_session() as s:
        if file_b:
            s.run("""
                UNWIND $rows AS row
                MATCH (r:Repo {id: row.repo_id})
                MERGE (f:File {repo_id: row.repo_id, path: row.path})
                  SET f.language = row.language,
                      f.size_bytes = row.size_bytes,
                      f.sha = row.sha
                MERGE (r)-[:CONTAINS]->(f)
            """, rows=file_b)
            file_b.clear()
        if cls_b:
            s.run("""
                UNWIND $rows AS row
                MERGE (c:Class {repo_id: row.repo_id, qualified_name: row.qualified_name})
                  SET c.name = row.name, c.file_path = row.file_path,
                      c.start_line = row.start_line, c.end_line = row.end_line,
                      c.doc = row.doc
                WITH c, row
                MATCH (f:File {repo_id: row.repo_id, path: row.file_path})
                MERGE (f)-[:DEFINES]->(c)
            """, rows=cls_b)
            cls_b.clear()
        if fn_b:
            s.run("""
                UNWIND $rows AS row
                MERGE (fn:Function {repo_id: row.repo_id, qualified_name: row.qualified_name})
                  SET fn.name = row.name, fn.file_path = row.file_path,
                      fn.start_line = row.start_line, fn.end_line = row.end_line,
                      fn.is_method = row.is_method, fn.is_async = row.is_async,
                      fn.doc = row.doc, fn.body_sha = row.body_sha
                WITH fn, row
                MATCH (f:File {repo_id: row.repo_id, path: row.file_path})
                MERGE (f)-[:DEFINES]->(fn)
                WITH fn, row WHERE row.class_qname IS NOT NULL
                MATCH (c:Class {repo_id: row.repo_id, qualified_name: row.class_qname})
                MERGE (c)-[:HAS_METHOD]->(fn)
            """, rows=fn_b)
            fn_b.clear()
        if imp_b:
            s.run("""
                UNWIND $rows AS row
                MERGE (m:Module {repo_id: row.repo_id, name: row.module})
                WITH m, row
                MATCH (f:File {repo_id: row.repo_id, path: row.file_path})
                MERGE (f)-[:IMPORTS]->(m)
            """, rows=imp_b)
            imp_b.clear()
        if cs_b:
            # CallSites persist between ingests; they're the source of truth for
            # the resolver. `file_path` lets us scope per-file cleanup on incremental.
            s.run("""
                UNWIND $rows AS row
                MATCH (caller:Function {repo_id: row.repo_id, qualified_name: row.caller_qname})
                MERGE (cs:CallSite {
                  repo_id: row.repo_id,
                  caller_qname: row.caller_qname,
                  callee_name: row.callee_name,
                  line: row.line
                })
                  SET cs.file_path = row.file_path,
                      cs.character = row.character
                MERGE (caller)-[:HAS_CALL]->(cs)
            """, rows=cs_b)
            cs_b.clear()


def _purge_file_subgraph(repo_id: str, rel_path: str) -> None:
    """Delete every node owned by a single file before re-parsing it.

    Cascades remove DEFINES, HAS_METHOD, CALLS, IMPORTS edges automatically
    (Neo4j DETACH DELETE). CallSites are keyed by `file_path`, so they're
    purged here too.
    """
    with neo_session() as s:
        # 1. Classes + Functions defined in this file
        s.run("""
            MATCH (f:File {repo_id: $rid, path: $p})-[:DEFINES]->(n)
            DETACH DELETE n
        """, rid=repo_id, p=rel_path)
        # 2. CallSites that originated in this file
        s.run("""
            MATCH (cs:CallSite {repo_id: $rid, file_path: $p})
            DETACH DELETE cs
        """, rid=repo_id, p=rel_path)
        # 3. IMPORTS edges from this file (modules with no other importers will
        #    become orphaned but harmless; we leave them since they're cheap).
        s.run("""
            MATCH (f:File {repo_id: $rid, path: $p})-[r:IMPORTS]->()
            DELETE r
        """, rid=repo_id, p=rel_path)


def _resolve_call_edges(repo_id: str) -> None:
    """Materialize (caller)-[:CALLS]->(callee) edges from CallSite nodes.

    Idempotent — uses MERGE, so re-running on the same repo is safe. Runs after
    every ingest so cross-file edges remain correct even when an unchanged
    file's CallSite suddenly resolves to a newly-added function (or stops
    resolving to a deleted one).
    """
    with neo_session() as s:
        # Drop CALLS edges that point to non-existent functions (defensive
        # cleanup; rare in practice because DETACH DELETE handles most cases).
        s.run("""
            MATCH (caller:Function {repo_id: $rid})-[r:CALLS]->(callee:Function)
            WHERE NOT EXISTS {
              MATCH (cs:CallSite {repo_id: $rid, caller_qname: caller.qualified_name})
              WHERE cs.callee_name = callee.name
            }
            DELETE r
        """, rid=repo_id)
        # (Re-)create CALLS for every pending CallSite that has a name match.
        s.run("""
            MATCH (caller:Function {repo_id: $rid})-[:HAS_CALL]->(cs:CallSite {repo_id: $rid})
            MATCH (callee:Function {repo_id: $rid, name: cs.callee_name})
            MERGE (caller)-[r:CALLS]->(callee)
              SET r.line = cs.line
        """, rid=repo_id)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _enabled_languages() -> set[str]:
    s = get_settings()
    explicit = set(s.enabled_language_list)
    return explicit or set(all_languages())


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _walk_repo(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if any(fnmatch.fnmatch(fn, pat) for pat in SKIP_PATTERNS):
                continue
            yield Path(dirpath) / fn


def _checkout(*, url: str, branch: str, dest: Path) -> Path:
    if url.startswith("file://"):
        src = Path(url.removeprefix("file://"))
        if not src.exists():
            raise RuntimeError(f"local repo path does not exist: {src}")
        return src
    if dest.exists() and (dest / ".git").exists():
        subprocess.run(["git", "-C", str(dest), "fetch", "--depth=1", "origin", branch], check=True)
        subprocess.run(["git", "-C", str(dest), "checkout", branch], check=True)
        subprocess.run(["git", "-C", str(dest), "reset", "--hard", f"origin/{branch}"], check=True)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", "--depth=1", "--branch", branch, url, str(dest)], check=True)
    return dest


def _count_source_files(dest: Path) -> int:
    """Count files under `dest` that match any registered parser's extension.
    Skips `.git/` and node_modules-style hot-spots so a repo of generated
    artefacts doesn't masquerade as 'has source'."""
    from ckg.parsers.base import detect_language

    if not dest.exists():
        return 0
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target"}
    count = 0
    for p in dest.rglob("*"):
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.is_file() and detect_language(p):
            count += 1
            if count >= 2:
                # Two is enough to decide it's not a skeleton — saves walking
                # gigabyte repos when we already know the answer.
                return count
    return count


def _remote_branches(dest: Path) -> set[str]:
    """All `origin` branches reachable from this clone. One ls-remote — no
    network traffic if the refs are already locally cached, otherwise one
    cheap HTTPS round-trip."""
    try:
        out = subprocess.run(
            ["git", "-C", str(dest), "ls-remote", "--heads", "origin"],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except subprocess.SubprocessError:
        return set()
    names: set[str] = set()
    for line in out.stdout.splitlines():
        # "<sha>\trefs/heads/<branch>"
        ref = line.split("\t", 1)[-1].strip()
        if ref.startswith("refs/heads/"):
            names.add(ref[len("refs/heads/"):])
    return names


def _git_head(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None
