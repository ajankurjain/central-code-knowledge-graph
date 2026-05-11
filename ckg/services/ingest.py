"""Full-repo ingest pipeline.

1. Clone or pull the repo into the worker's repo cache.
2. Walk the tree; for each supported file, run the matching parser.
3. Batch-write nodes and edges to Neo4j.
4. (Optional) compute embeddings on parsed function bodies.

This is intentionally simple — a full re-parse on each ingest call.
Incremental update (only changed files) is a Phase 2 add-on; the schema
already supports it (each File has a sha).
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ckg.config import get_settings
from ckg.db.neo4j import init_schema as init_neo_schema
from ckg.db.neo4j import session as neo_session
from ckg.logging import get_logger
from ckg.parsers import get_parser
from ckg.parsers.base import ParseResult, all_languages, detect_language

log = get_logger(__name__)

# Files we never want to parse
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", "out", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target"}
SKIP_PATTERNS = ("*.min.js", "*.map", "*.lock", "*.snap")


@dataclass
class IngestStats:
    files_parsed: int = 0
    files_skipped: int = 0
    functions: int = 0
    classes: int = 0
    calls: int = 0
    imports: int = 0
    languages: set[str] = field(default_factory=set)
    head_sha: str | None = None

    def to_dict(self) -> dict:
        return {
            "files_parsed": self.files_parsed,
            "files_skipped": self.files_skipped,
            "functions": self.functions,
            "classes": self.classes,
            "calls": self.calls,
            "imports": self.imports,
            "languages": sorted(self.languages),
            "head_sha": self.head_sha,
        }


def ingest_repo(*, repo_id: str, url: str, branch: str, workdir: Path) -> IngestStats:
    settings = get_settings()
    init_neo_schema()

    workdir.parent.mkdir(parents=True, exist_ok=True)
    local_path = _checkout(url=url, branch=branch, dest=workdir)
    head_sha = _git_head(local_path)
    log.info("ingest_checkout_done", repo_id=repo_id, path=str(local_path), head=head_sha)

    # Wipe prior graph for this repo (full re-parse semantics)
    with neo_session() as s:
        s.run("MATCH (n) WHERE n.repo_id = $rid DETACH DELETE n", rid=repo_id)
        s.run("""
            MERGE (r:Repo {id: $rid})
              SET r.url = $url, r.default_branch = $branch
        """, rid=repo_id, url=url, branch=branch)

    enabled = set(settings.enabled_language_list) or set(all_languages())
    stats = IngestStats(head_sha=head_sha)

    file_batch: list[dict] = []
    class_batch: list[dict] = []
    fn_batch: list[dict] = []
    import_batch: list[dict] = []
    call_batch: list[dict] = []

    BATCH = 500

    for path in _walk_repo(local_path):
        lang = detect_language(path)
        if lang is None or lang not in enabled:
            stats.files_skipped += 1
            continue
        parser = get_parser(lang)
        if parser is None:
            stats.files_skipped += 1
            continue
        try:
            source = path.read_bytes()
            rel = path.relative_to(local_path)
            result = parser.parse(rel, source)
        except Exception as exc:
            log.warning("parse_failed", path=str(path), error=str(exc))
            stats.files_skipped += 1
            continue

        stats.files_parsed += 1
        stats.functions += len(result.functions)
        stats.classes += len(result.classes)
        stats.calls += len(result.calls)
        stats.imports += len(result.imports)
        stats.languages.add(result.language)

        file_batch.append({
            "repo_id": repo_id,
            "path": result.path,
            "language": result.language,
            "size_bytes": result.size_bytes,
        })
        for c in result.classes:
            class_batch.append({
                "repo_id": repo_id,
                "file_path": result.path,
                "name": c.name,
                "qualified_name": c.qualified_name,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "doc": c.doc,
            })
        for fn in result.functions:
            fn_batch.append({
                "repo_id": repo_id,
                "file_path": result.path,
                "name": fn.name,
                "qualified_name": fn.qualified_name,
                "start_line": fn.start_line,
                "end_line": fn.end_line,
                "is_method": fn.is_method,
                "is_async": fn.is_async,
                "doc": fn.doc,
                "body_sha": fn.body_sha,
                "class_qname": fn.class_qname,
            })
        for imp in result.imports:
            import_batch.append({
                "repo_id": repo_id,
                "file_path": result.path,
                "module": imp.module,
            })
        for call in result.calls:
            call_batch.append({
                "repo_id": repo_id,
                "caller_qname": call.caller_qname,
                "callee_name": call.callee_name,
                "line": call.line,
            })

        if len(file_batch) >= BATCH:
            _flush(file_batch, class_batch, fn_batch, import_batch, call_batch)

    _flush(file_batch, class_batch, fn_batch, import_batch, call_batch)
    _resolve_call_edges(repo_id)
    log.info("ingest_neo4j_written", repo_id=repo_id, stats=stats.to_dict())
    return stats


def _walk_repo(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if any(fnmatch.fnmatch(fn, pat) for pat in SKIP_PATTERNS):
                continue
            yield Path(dirpath) / fn


def _checkout(*, url: str, branch: str, dest: Path) -> Path:
    """Clone fresh, or fast-forward if already cloned. Supports file://, https://, ssh."""
    if url.startswith("file://"):
        src = Path(url.removeprefix("file://"))
        if not src.exists():
            raise RuntimeError(f"local repo path does not exist: {src}")
        # For a local path we use it in place (no copy) — but ensure it's a git dir if we want HEAD
        return src

    if dest.exists() and (dest / ".git").exists():
        subprocess.run(["git", "-C", str(dest), "fetch", "--depth=1", "origin", branch], check=True)
        subprocess.run(["git", "-C", str(dest), "checkout", branch], check=True)
        subprocess.run(["git", "-C", str(dest), "reset", "--hard", f"origin/{branch}"], check=True)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # not a git repo — wipe and reclone
        import shutil
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", "--depth=1", "--branch", branch, url, str(dest)], check=True)
    return dest


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


def _flush(files, classes, fns, imports, calls) -> None:
    if not any([files, classes, fns, imports, calls]):
        return
    with neo_session() as s:
        if files:
            s.run("""
                UNWIND $rows AS row
                MATCH (r:Repo {id: row.repo_id})
                MERGE (f:File {repo_id: row.repo_id, path: row.path})
                  SET f.language = row.language, f.size_bytes = row.size_bytes
                MERGE (r)-[:CONTAINS]->(f)
            """, rows=files)
            files.clear()
        if classes:
            s.run("""
                UNWIND $rows AS row
                MERGE (c:Class {repo_id: row.repo_id, qualified_name: row.qualified_name})
                  SET c.name = row.name, c.file_path = row.file_path,
                      c.start_line = row.start_line, c.end_line = row.end_line,
                      c.doc = row.doc
                WITH c, row
                MATCH (f:File {repo_id: row.repo_id, path: row.file_path})
                MERGE (f)-[:DEFINES]->(c)
            """, rows=classes)
            classes.clear()
        if fns:
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
            """, rows=fns)
            fns.clear()
        if imports:
            s.run("""
                UNWIND $rows AS row
                MERGE (m:Module {repo_id: row.repo_id, name: row.module})
                WITH m, row
                MATCH (f:File {repo_id: row.repo_id, path: row.file_path})
                MERGE (f)-[:IMPORTS]->(m)
            """, rows=imports)
            imports.clear()
        if calls:
            # We store *pending* call edges keyed by callee name; resolve later.
            s.run("""
                UNWIND $rows AS row
                MATCH (caller:Function {repo_id: row.repo_id, qualified_name: row.caller_qname})
                MERGE (pending:CallSite {
                  repo_id: row.repo_id,
                  caller_qname: row.caller_qname,
                  callee_name: row.callee_name,
                  line: row.line
                })
                MERGE (caller)-[:HAS_CALL]->(pending)
            """, rows=calls)
            calls.clear()


def _resolve_call_edges(repo_id: str) -> None:
    """Best-effort: match CallSite.callee_name -> Function.name in the same repo.

    Real-world projects need scope analysis to disambiguate. For now we wire up
    every callable that matches by short name; the next phase will use LSP /
    full qualified-name resolution.
    """
    with neo_session() as s:
        s.run("""
            MATCH (caller:Function {repo_id: $rid})-[:HAS_CALL]->(cs:CallSite)
            MATCH (callee:Function {repo_id: $rid, name: cs.callee_name})
            MERGE (caller)-[r:CALLS]->(callee)
              SET r.line = cs.line
        """, rid=repo_id)
        # Drop transient CallSite nodes — graph stays clean.
        s.run("MATCH (cs:CallSite {repo_id: $rid}) DETACH DELETE cs", rid=repo_id)
